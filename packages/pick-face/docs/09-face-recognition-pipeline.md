# 09 人脸识别流水线总览（v3.0）

> 文档版本：v3.0 · 2026-08-12
> 范围：从一张图到"这个人是谁"的端到端可视图（Web 服务化）
> 关联：[04 算法流水线](04-algorithm-pipeline.md) · [05 §数据](05-data-and-storage.md)

## 0. 流水线图

```
   扫描根下的图片文件
       │
       ▼
 ┌──────────────────────┐
 │ ① ingest/scanner     │  Pillow / pillow-heif / rawpy
 │    列出 + 解码       │  content_hash + size + format
 └────────┬─────────────┘
          │
 ┌────────▼─────────────┐
 │ ② ingest/detector     │  YuNet (SFace pack) / SCRFD (ArcFace pack)
 │    找出人脸 + 关键点 │  bbox + 5 landmarks + det_score
 └────────┬─────────────┘
          │
 ┌────────▼─────────────┐
 │ ③ ingest/align        │  warp_to_112() → 112×112 RGB
 │    标准化脸 + 缩略图 │  + Pillow thumbnail() 256×256
 └────────┬─────────────┘
          │
 ┌────────▼─────────────┐
 │ ④ ingest/embedder     │  SFace 128-D / ArcFace 512-D
 │    嵌入向量           │  L2 normalized float32
 └────────┬─────────────┘
          │
 ┌────────▼─────────────┐
 │ ⑤ store/index_hnsw    │  hnswlib.cosine, KNN
 │    向量索引           │  持久化 .hnsw
 └────────┬─────────────┘
          │
 ┌────────▼─────────────┐
 │ ⑥ ingest/cluster      │  HDBSCAN on cosine
 │    按人聚类           │  faces.person_id 填入
 └────────┬─────────────┘
          │
 ┌────────▼─────────────┐
 │ ⑦ store/review        │  人工 review: rename / merge / delete
 │    Review              │
 └────────┬─────────────┘
          │
 ┌────────▼─────────────┐
 │ ⑧ Web API             │  FastAPI + SPA
 │    提供虚拟相册        │
 └──────────────────────┘
```

## 1. 八阶段总览

### 1.1 阶段 ① 扫描（`ingest/scanner.py`）

```python
from pick_face.ingest.scanner import iter_images

async def iter_images(root: Path) -> AsyncIterator[Path]:
    for p in root.rglob("*"):
        if p.suffix.lower() in SUPPORTED_EXTS:
            yield p
```

- **SUPPORTED_EXTS**：jpg / jpeg / png / heic / heif / webp / tiff / dng / cr2 / nef / arw / orf / rw2
- **解码异常** → log + skip
- **content_hash**（xxh3_64）：增量扫描用

### 1.2 阶段 ② 检测（`ingest/detector.py`）

```python
from pick_face.platform.packs.yunet_sface import YuNetDetector

detector = YuNetDetector(yunet_path, det_size=(320, 320))
detections = detector.detect(image_bgr)  # list[Detection]
```

- `det_score < 0.3` → 丢弃
- 输出 `Detection(bbox, landmarks, det_score, chip, quality)`

### 1.3 阶段 ③ 对齐（`ingest/align.py`）

```python
from pick_face.ingest.align import warp_to_112

chip_rgb = warp_to_112(image_bgr, landmarks)  # (112, 112, 3) RGB uint8
```

- 5-point landmarks → affine warp to 112×112
- 同时生成缩略图 256×256

### 1.4 阶段 ④ 嵌入（`ingest/embedder.py`）

```python
from pick_face.platform.packs.yunet_sface import SFaceEmbedder

embedder = SFaceEmbedder(sface_path, providers=["CPUExecutionProvider"])
vec = embedder.embed(chip_rgb)  # (128,) float32 L2-normalized
```

- 128-D（SFace）或 512-D（ArcFace）
- L2 normalized → cosine distance = L2 distance

### 1.5 阶段 ⑤ 索引（`store/index_hnsw.py`）

```python
import hnswlib
index = hnswlib.Index(space="cosine", dim=128)
index.add_items(vecs, ids=face_ids)
index.save_index("index.hnsw")
```

- KNN 查询：`index.knn_query(vec, k=20)`
- 持久化：`save_index` / `load_index`

### 1.6 阶段 ⑥ 聚类（`ingest/cluster.py`）

```python
from pick_face.ingest.cluster import cluster_embeddings

clusters = cluster_embeddings(embeddings, min_cluster_size=3)
```

- HDBSCAN on cosine distance
- `min_cluster_size` 默认 3
- 输出 `cluster_id` → `list[face_id]`

### 1.7 阶段 ⑦ Review（`store/review.py`）

```python
from pick_face.store.review import rename_person, merge_persons, delete_person

rename_person(person_id, "Alice")
merge_persons([src1, src2], target_id)
delete_person(person_id)  # 软删除
```

- 所有 review 操作记录到 `review` 表（审计日志）

### 1.8 阶段 ⑧ Web API（`api/persons.py`）

```python
@app.get("/api/persons")
async def list_persons(cursor: str | None = None, limit: int = 50):
    return await person_service.list(cursor=cursor, limit=limit)
```

- 虚拟相册 list、瀑布流分页、查看器流
- **前端通过 SSE 订阅新事件**

## 2. 完整数据生命周期

```
1. 用户加路径  →  scan_paths 表插入
2. watchdog     →  push 到 asyncio.Queue
3. scan_worker  →  ingest 五个阶段 → SQLite + HNSW
4. cluster_worker 周期  →  HDBSCAN 跑完 → faces.person_id 填入
5. 用户打开     →  GET /api/persons 读 SQLite
6. 点开相册     →  GET /api/persons/{id}/photos 读 photo_persons 表
7. 查看器流     →  GET /api/photos/{id}  FileResponse（Range）
8. 用户合并     →  POST /api/persons/merge  写 review 表
```

## 3. 复用与差异（v2.x → v3）

| 阶段 | v2.x CLI | v3 Web | 复用点 |
|---|---|---|---|
| ① scanner | ✅ 复用 | ✅ 复用 | 完全 |
| ② detector | ✅ 复用 | ✅ 复用 | session 长驻 |
| ③ align | ✅ 复用 | ✅ 复用 | + 缩略图 |
| ④ embedder | ✅ 复用 | ✅ 复用 | session 长驻 |
| ⑤ hnsw | ✅ 复用 | ✅ 复用 | 增量添加 |
| ⑥ cluster | ✅ 复用 | ✅ 周期 + 增量触发 | 新 |
| ⑦ review | ✅ CLI 命令 | ✅ Web UI | API 包装 |
| ⑧ output | 硬链接目录 | HTTP API | 完全重做 |

## 4. 关键不变量（v3 强制）

1. `faces.embedding` 必填（128 或 512 float32）
2. `faces.person_id` NULL 表示"未聚类"或"聚类失败"
3. `persons.face_count` 与 `count(faces WHERE person_id = ?)` 必须一致（触发器 / 应用层校验）
4. `persons.thumbnail_face_id` 必须属于该 person
5. `photos.deleted = 0` 才会出现在瀑布流

## 5. 引用与延伸阅读

- [01 PRD](01-product-requirement.md) — US-2/3/4/5
- [03 §服务架构](03-architecture-design.md) — service / api / worker 划分
- [04 §聚类流水线](04-algorithm-pipeline.md) — 算法细节
- [05 §数据与存储](05-data-and-storage.md) — SQLite schema