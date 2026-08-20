# 09 人脸识别流程详解（端到端）

> 文档版本：v0.1（评审稿） · 2026-07-30
> 范围：从「用户在终端敲一行 `pick-face run`」到「`<output>/person-0001/` 里出现软链接」之间的**每一步**。
> 单一权威解读在 [08 §6 最终方案](08-review-notes.md)；本文展开**为什么这样做**和**怎么做**。

## 0. 摘要（一分钟版）

```
scan → detect → align → embed → persist → cluster(+二次合并) → link → report
   │       │       │      │        │             │                │       │
 文件    model pack  ArcFace  model pack  SQLite    HDBSCAN      软链接   Markdown
 树     detector   5点仿射   embedder    权威     簇质心合并    原子切换   报告
         (YuNet     纯几何   (MobileNet                │
         /SCRFD)             /ArcFace)               │
                       (默认 yunet-mfn / opt-in buffalo_l 等, 详见 10 §2 / 14)
```

6 个核心阶段，2 个横切关注点（错误处理 + 进度事件）。`pick-face run` 串起来一次性执行；`scan / index / cluster / link / report` 子命令允许分步调试。**detector / embedder 由 model pack 插件提供**（路线 B），不绑定任何具体实现 —— 详见 [10](10-model-stack.md) + [14](14-model-pack-plugins.md)。

---

## 1. 启动与配置加载

**触发**：用户在终端执行
```
pick-face run \
  --src /Volumes/Photos/2023 \
  --src /Volumes/Photos/2024 \
  --out /Volumes/Photos/by_face \
  --provider auto
```

**做了什么**：
1. `cli` 解析 Typer 参数；`config` 模块用 pydantic 校验 `pick-face.toml` + CLI flag 的合并结果。
2. 启动 PRAGMA（`journal_mode=WAL`, `foreign_keys=ON` 等，见 [05 §2.1](05-data-and-storage.md)），打开 `<out>/.cache/index.sqlite`。
3. 启动 hnswlib，载入 `<out>/.cache/faces.hnsw`（首次运行则为空索引）。
4. 加载 model pack（**路线 B 后不再写死 InsightFace**）：
   - `pick_face.platform.pack.discover_packs()` 解析 `[runtime] pack` 对应的 entry-point
   - 优先用 `PICK_FACE_MODEL_DIR` 或 `[runtime] model_dir` 指向的本地目录（路径布局 `model_dir/<pack_id>/<file>.onnx`）
   - 否则（仅在 `--allow-network`）触发 `init-models --pack <id>` 下载逻辑
   - pack 的 `LicenseClass.NC_RESEARCH` 时启动强校验 `accept_noncommercial_model_license`（详见 [11 §3.2](11-commercial-compliance.md)）
   - 默认 `pack = "yunet-mfn"`（Apache-2.0，不需 ack）；opt-in `buffalo_l` 走 `pick-face-modelpack-insightface` 插件
   - 失败抛 `ModelLoadError`（退出码 3，见 [03 §9](03-architecture-design.md)）
5. 获取 `<out>/.lock` 文件锁，阻止多实例。
6. 写一条 `run` 行（`started_at = now`, `mode = 'full' | 'incremental' | 'rebuild'`, `config_hash` = 配置文件 SHA256）。

---

## 2. 扫描（scan）

**目标**：把 `--src` 下所有允许的图片列出来，并和 SQLite 已有记录比对，决定每张图属于 ADD / MOD / UNCHANGED / DEL。

**步骤**（`pick_face.ingest.scanner`）：

1. **遍历**：用 `os.scandir` 递归扫描每个 `--src` 根目录。
2. **过滤**：
   - 后缀白名单（默认 jpg/jpeg/png/webp/heic/tiff/bmp/gif）。
   - glob exclude（来自 `pick-face.toml` 的 `exclude` 段）。
   - 跳过符号链接、`.` 开头文件、零字节文件。
3. **快速指纹**：对每张图取 `(size, mtime)` 元组；与 `source` 表的 `(size, mtime, hash)` 比较：
   - 命中且未变 → UNCHANGED。
   - 命中但 mtime/size 变化 → MOD，**重新计算 `hash` 后再确认**（避免单纯 mtime 漂移）。
   - 未命中 → ADD。
4. **content hash**：ADD/MOD 项用 `xxh3_64` 计算前 64KB 的 hash（即 `hash = xxh3_64(path.read_bytes()[:65536])`），存入 `source.hash` 字段。这是一个**快速幂等键**：同图改名/移位也认得出来。完整 SHA-256 在 v0.2 视需要再补。
5. **DEL 检测**：所有遍历中**没出现**但 `status='active'` 的 `source` 标记为 `status='missing'`；后续 `link` 阶段会回收对应软链接。
6. **错误**：权限不足 / 符号链接循环 → 记 `error_log`，继续。

**输出**：在内存里得到一个 `ScanDiff` 结构：

```python
@dataclass
class ScanDiff:
    added:     list[SourceRow]
    modified:  list[SourceRow]
    unchanged: list[SourceRow]
    deleted:   list[int]  # source.id
```

---

## 3. 图像解码（image decode）

**目标**：把 ADD/MOD 项解码成 BGR ndarray，并降采样到推理友好的尺寸。

**步骤**（`pick_face.core.images`）：

1. **格式路由**：
   - JPG/PNG/WebP/BMP/GIF → Pillow（`Image.open` + `ImageOps.exif_transpose`）。
   - HEIC/HEIF → `pillow-heif` 注册 opener 后 Pillow 直读（依赖 `[heic]` extras）。
   - TIFF 多页 → Pillow 取第一帧。
   - RAW（CR2/NEF/ARW/DNG/RAF）→ **先**读 EXIF thumbnail（Pillow `Image.open` 自动用 thumbnail）；thumbnail 上能检出脸就**跳过 rawpy**；否则 `rawpy.imread().postprocess()` 解全图。
2. **EXIF 旋转**：`ImageOps.exif_transpose(img)` 把方向归位（手机照片 90% 是这个坑）。
3. **降采样**：长边 ≤ 1600 px（双线性）。**为什么是 1600**：InsightFace 检测在更大尺寸上收益递减，1600 是经验拐点。
4. **BGR 转换**：Pillow 是 RGB；OpenCV / InsightFace 要 BGR，最后 `cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)`。
5. **失败兜底**：解码失败 → `error_log(stage='decode')`，跳过本图。

**输出**：`list[(source_id, bgr_image, pil_image_for_thumb)]` 流到下一阶段。

---

## 4. 检测（detect）

**目标**：在 BGR 图上找到所有人脸的位置与关键点。

**模型**：由 model pack 决定。默认 `yunet-mfn` 用 **YuNet**（OpenCV Zoo，~363 KB）；opt-in `buffalo_l` 用 **SCRFD-10G**（InsightFace，16 MB）。两者都输出 5 个关键点（左/右眼、鼻尖、左/右嘴角），直接喂给 ArcFace 5-pt 对齐器。详见 [10 §2.1 / §2.2](10-model-stack.md)。

**调用形态**（[02 §2.1 代码](02-technical-pre-research.md)）：

```python
from insightface.app import FaceAnalysis
app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
app.prepare(ctx_id=0, det_size=(640, 640))
faces = app.get(bgr_image)  # 1..N 个 Face
```

**每张 `Face` 包含**：
```python
bbox        (x1, y1, x2, y2)      # 整数像素矩形
det_score   float                 # 0..1
kps         ndarray (5, 2)        # 5 个关键点 (x, y)
embedding   ndarray (512,)        # **已 L2 归一化**，可直接 cosine
```

**关键参数**（[04 §3.1 阈值表](04-algorithm-pipeline.md)）：
- `det_thresh=0.5`：低于此分的候选框丢弃。`buffalo_l` 在 0.5 给出最高精度/召回平衡；调低会增加误检（钟表、卡通脸）。
- `det_size=(640,640)`：输入到检测器的最短边；越大召回越高、越慢。CPU 起步 640；如要快可降到 320。
- 合影里的小脸：靠 `det_size` 调大、或者对原图做 tile（v0.2 再说）。

**输出**：`list[FaceBox]` 流入下一阶段。

---

## 5. 对齐（align）

**目标**：把检测到的人脸裁剪到「标准化的 112×112 RGB 图像」，送进嵌入网络。

**做法**（`pick_face.ingest.align`）：
1. 取 5 个关键点（双眼、鼻尖、嘴角）。
2. 用 InsightFace 内置的「参考关键点 + 仿射矩阵」做 warp，把人脸摆正 + 缩放到 112×112。
3. 这一步把「同一人的不同角度/尺度」变成「近似同分布的输入」，是 ArcFace 识别能力的关键。

**为什么不直接用 bbox 裁剪？**
直接裁剪会把人脸姿态/尺度差异都留给嵌入网络；模型再强也吃力。先对齐 5 个关键点，**人脸的语义位置被强制对齐**，嵌入网络的负担大幅降低，识别准确率显著上升。

**输出**：112×112 RGB 的人脸 chip（numpy 数组），流到嵌入。

---

## 6. 嵌入（embed）

**目标**：把对齐后的 112×112 chip 映射到 embedding 空间，使**同人相聚、异人相远**。

**模型**：由 model pack 决定。默认 `yunet-mfn` 用 **MobileFaceNet INT8**（OpenCV Zoo，128-D，LFW 99.50%）；opt-in `buffalo_l` 用 **ArcFace w600k_r50**（InsightFace，512-D，LFW 99.83%）。详见 [10 §2.1 / §2.2](10-model-stack.md)。

**数学本质**（为什么 ArcFace 强）：
- 最后一层把 embedding 投影到 512 维单位球上（L2 归一化）。
- 训练时强制「同人之间的夹角 ≥ 某角度 margin + 不同人之间的夹角 ≤ 某角度」。
- 推理时用余弦相似度（cosine）即可度量"同一人"。

**调用**（同 `FaceAnalysis` 一条管线）：

```python
# 来自 faces = app.get(bgr_image)
for f in faces:
    e = f.normed_embedding  # shape (512,), L2-normalized
    sim = float(e @ existing_centroid.T)   # 直接 cosine
```

**质量分（quality）**：组合三路信号到 0..1：
- `det_score`（0.5..1）
- 关键点对齐残差（warp 后的平均像素误差，越小越好）
- 模糊度（chip 灰度图的 Laplacian 方差，> 100 算清晰）

`quality < 0.20` 的脸打 `face.low_quality=1`，**不参与聚类**但保留在 SQLite，供 `review` 子命令调取。

**输出**：512 维 float32 数组，**直接写 BLOB 到 `face.embedding` 列**（不序列化为 JSON，见 [ADR-009](07-risk-and-decisions.md)）。

---

## 7. 落库（persist）

**目标**：把第 2–6 步的产物写入 SQLite，并同步增量更新 HNSW 索引。

**事务**（`pick_face.store.index`）：
```sql
BEGIN IMMEDIATE;
INSERT INTO source (...) VALUES (...) ON CONFLICT(path) DO UPDATE SET ...;
INSERT INTO face (source_id, bbox_*, lmk_*, quality, ...) VALUES (...);
COMMIT;
```

**HNSW 同步**（[05 §3](05-data-and-storage.md)）：
- 新脸 → `hnsw.add_items(emb, ids=[face.id])`。
- 删除的脸（用户 `review remove`） → `hnsw.mark_deleted(face_id)`，**不物理删除**。
- 累积到 10% → 后台 `rebuild_hnsw` 一次（O(n) 可接受）。

**幂等保证**：写入以 `face.id` 为主键；同一张图重新跑不会产生重复 face（`(source_id, bbox)` 上有 UNIQUE 兜底）。

---

## 8. 聚类（cluster）

**目标**：把全部人脸向量分成若干簇，每个簇代表「同一人」。

**算法**（[04 §2.4](04-algorithm-pipeline.md)）：

### 8.1 为什么是 HDBSCAN（而不是 DBSCAN / k-means / 谱聚类）

| 算法 | 痛点 | HDBSCAN 的解法 |
|------|------|----------------|
| k-means | 必须给 k | 无需指定 k，自动出簇 |
| DBSCAN | `eps` 难调、密度变化敏感 | HDBSCAN 用「层次稳定度」选阈值 |
| 谱聚类 | O(n³) | 改成 HNSW 构图，O(n log n) |
| 层次凝聚 | 阈值靠经验 | 同上，但 HDBSCAN 还能返回「每点的归属概率」 |

### 8.2 两阶段实施

**阶段 A — HDBSCAN 初始簇**：
1. 用 hnswlib 取出每个 face 的 top-50 近邻（cosine 距离），构图。
2. 距离矩阵只保留 top-k 边，其余置 1.0（"最不相似"）以避免 n² 内存。
3. 调 `hdbscan.fit(预计算距离)`，参数 `min_cluster_size=3`、`min_samples=2`、`cluster_selection_method='leaf'`。
4. 输出 `labels`（int32，-1 = 噪声）和 `probs`（float32）。

**阶段 B — 簇质心二次合并（关键步骤）**：
1. 对每个非噪声簇，算质心 `centroid[k] = mean(embedding[label==k])`，再 L2 归一化。
2. 两两算 cosine 矩阵 `C[i,j] = centroid[i] @ centroid[j]`。
3. `C[i,j] ≥ 0.55` → 合并两簇（**保留体量较大者的 ID**，被合并者 `cluster.merged_into = survivor.id`）。
4. 重新计算新质心，迭代到收敛（一般 2–3 轮）。

**为什么需要阶段 B**：HDBSCAN 经常把"同一个人"切到两个簇（光照明暗差、年龄跨度大）。**二次合并**用更松的阈值把"显然同人"的相邻簇救回来，召回率大幅提升（precision 略降、整体 B³ F1 上升）。

### 8.3 人工约束

`review_decision` 表里的 `must_link` / `cannot_link` 在 cluster 阶段读出：
- `must_link`：强制把两个 face 标到同一 label。
- `cannot_link`：强制拆开。

实现方式：把 face 的最终 label 在 HDBSCAN 输出后做一遍 union-find / 拆边修复。

### 8.4 触发策略

- **全量重聚类**：`pick-face cluster` 显式，或 `--rebuild` 隐式。
- **增量分配**（默认）：`pick-face run` 时若新增 face ≥ 50 或距上次聚类 ≥ 24h，触发 `Clusterer.incremental_assign`：每个新脸与现有质心比 cosine，≥ 0.55 归入；否则作为"候选簇"等下次聚类。
- **ID 粘性**：合并用 survivor ID，被合并者进 `_archive/`。这保证 `person-0001` 不会因为聚类变化而消失。

**输出**：每个 face 有一个确定的 `cluster_id`（= `cluster.id` → 标签 `person-0001`）。

---

## 9. 链接（link）

**目标**：根据 `face.cluster_id` 在 `<output>/<person-id>/<src_rel_path>` 创建软链接，指向原图。

**步骤**（`pick_face.output.linker`）：

1. **逐 face 处理**（多人合影可能产生多个 face → 同一张图出现在多个人物下）：
   - 对每个 face 的 (cluster_id, source_id)：
     - 若 `link` 表已有同 `(cluster_id, source_id)` → 跳过（幂等）。
     - 否则在 `<out>/person-XXXX/<src_rel_path>` 创建链接 → `<abs_src>`。
2. **软链接三段回退**（[05 §4 权威](05-data-and-storage.md)）：
   - 优先 `os.symlink`；失败 →
   - Windows 目录 → `mklink /J`（junction）；文件 → `os.link`（硬链接）；最后 →
   - `shutil.copy2`（拷贝）并 `report.md` 顶部 `Warnings` 列出。
3. **命名冲突**：`person-0007/2023-trip/IMG_0001.jpg` 已存在时追加 `-1`、`-2` 后缀。
4. **跨设备**：检测 `os.path.samefile` 失败 → 跳过 hardlink，直接 copy + warning。
5. **写 link 表**：`link_kind` 字段记实际使用的模式（symlink / hardlink / junction / copy），便于审计与回滚。

**GC**：扫描阶段标 `status='missing'` 的 source → `link.actual_target` 解析失败或不再指向原路径 → `link` 阶段记入 `dangling_links`；`pick-face gc` 物理删除并写日志。

---

## 10. 报告（report）

**目标**：产出一份人类能读、机器能 grep 的总览。

**产物**：
- `report.md`（默认）：人物数、人脸数、噪声数、置信度直方图、Warnings（链接回退 / 模型降级 / 错误率）、`low_confidence_faces.json` 路径。
- `report.html`（v0.4 完善）：人物缩略图墙、点开看每张图、点击合并/拆分进入 review。
- `low_confidence_faces.json`：所有 `cos < 0.40` 到簇质心的脸（含缩略图路径），供 review 子命令快速定位。
- `index.json`：SQLite 中 cluster + link 关系的镜像，**不含 embedding**（[ADR-009](07-risk-and-decisions.md)）。

**Stats 计算**（写回 `run.stats_json`）：
```
total_sources, total_faces, persons, noise_faces,
link_kind_counts, error_count, recluster_triggered, duration_sec
```

---

## 11. 原子切换（ADR-008）

`pick-face run` 实际写的是 `<out>/.staging-<run_id>/`。**全部完成后**才做：

```
<out>/<旧版>           → <out>/.prev-<run_id>     # 旧版本改名保留
<out>/.staging-<run_id> → <out>                    # atomic rename
```

- 失败：删除 `.staging-<run_id>/`，旧版保持不动。
- 回滚：`pick-face rollback --to <run_id>` 把 `.prev-<run_id>` 改回 `<out>`。
- 保留最近 3 个 `.prev-`，更老的由 `gc` 清理。

**为什么需要**：让用户**永远不会看到半成品**；任何时刻 `<out>/` 都是一致的、可被外部脚本消费的。

---

## 12. 错误处理与可恢复性

**退出码契约**（[03 §9](03-architecture-design.md)）：

| 码 | 含义 | 处置 |
|----|------|------|
| 0 | 全流程成功（含可恢复 warning） | — |
| 2 | 严重配置 / 参数错误 | 检查 `pick-face.toml` / CLI |
| 3 | 模型不可用（首次未联网且未 init-models） | 重跑 `pick-face init-models --allow-network` |
| 4 | 关键阶段失败率 > 50% | 检查 `error_log` 表与系统资源 |
| 5 | SIGINT / SIGTERM 中断的「部分完成」 | 重跑同一命令可继续 |

**JSON 进度事件**（`--progress json`，供 TUI 解析）：

```json
{"ts": 1722345678, "stage": "embed", "done": 1234, "total": 5000, "rate_fps": 4.1, "errors": 0}
```

`errors` 字段与 `error_log` 表计数一致。

**SIGTERM 处理**：
- 收到信号 → 立刻写 `run.finished_at = NULL`（标识"未完成"），关闭 session。
- 下次启动：检测到 `finished_at IS NULL` 的 run → 触发 `gc` 清理 `.staging-<run_id>/`，然后正常进入「增量」模式（基于 `source` 表的 mtime/hash 自然 continue）。

---

## 13. 端到端示例

```
$ pick-face run --src /Volumes/Photos/2023 --out /Volumes/Photos/by_face

[scan]    1234 sources, 0 new, 0 mod, 0 missing
[index]   1234/1234 [00:42]  29.3 fps  errors=0
[cluster] 50 new faces → incremental_assign (no rebuild)
[link]    412 symlinks, 0 hardlinks, 0 junctions, 0 copies
[report]  → /Volumes/Photos/by_face/report.md
[run]     finished in 1m 18s, exit 0

# 验证
$ ls /Volumes/Photos/by_face/
.cache/  index.json  report.md  person-0001/  person-0002/  _review/

$ cat /Volumes/Photos/by_face/person-0001/meta.json | jq .
{
  "schema_version": 1,
  "cluster_id": 1,
  "label": "person-0001",
  "size": 87,
  "mean_sim": 0.62,
  "merged_into": null,
  "first_seen": "2023-04-12T08:30:00Z",
  "last_seen":  "2023-12-30T19:12:00Z",
  "review_state": "auto"
}
```

---

## 14. 关键调参与踩坑

| 现象 | 调谁 | 改多少 |
|------|------|--------|
| 误检太多（钟表、玩偶） | `det_thresh` | ↑ 到 0.6 |
| 漏掉小脸、合影 | `det_size` | ↑ 到 (1024, 1024)；或 tile 输入 |
| 同一人被切两簇 | `merge_threshold` | ↑ 到 0.6（救回更多） |
| 不同人被合到一簇 | `merge_threshold` | ↓ 到 0.5 + 调高 `det_thresh` |
| 簇数过多（噪声过敏感） | `min_cluster_size` | ↑ 到 4 |
| 簇数过少（漏人） | `min_cluster_size` | ↓ 到 2；`min_samples` 降到 1 |
| 内存爆 | HNSW 构图 / 流式聚类 | 已有；如仍爆 → 缩小批处理 |
| Windows 软链接失败 | 权限 | README 提示开「开发人员模式」或以管理员运行 |
| HEIC 解码失败 | extras | `uv pip install -e ".[heic]"` |

---

## 15. 引用与延伸阅读

- [04 算法流水线](04-algorithm-pipeline.md) — 各阶段细节 + 阈值表
- [05 数据与存储](05-data-and-storage.md) — SQLite / HNSW / 软链接 / 原子切换
- [03 §5 关键接口契约](03-architecture-design.md) — `FaceDetector` / `FaceEmbedder` / `Clusterer` / `Linker` Protocol
- [02 技术预研](02-technical-pre-research.md) — InsightFace / HDBSCAN 选型理由
- [07 ADR](07-risk-and-decisions.md) — ADR-006 进程模型 / ADR-008 原子切换 / ADR-009 SQLite 权威
- [08 §6 最终方案](08-review-notes.md) — 单一权威解读
- InsightFace python-package README — https://github.com/deepinsight/insightface/blob/master/python-package/README.md
- HDBSCAN docs — https://hdbscan.readthedocs.io/
- ArcFace 论文 — https://arxiv.org/abs/1801.07698
- SCRFD 论文 — https://arxiv.org/abs/2105.04714
