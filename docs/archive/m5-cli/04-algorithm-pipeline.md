# 04 算法流水线：检测 → 对齐 → 嵌入 → 聚类

> 文档版本：v0.1（预研稿） · 2026-07-30

## 1. 全流程概览

```
原始图片
  │  (EXIF rotate, downsample to max-side 1600; RAW 先 EXIF thumbnail)
  ▼
检测 (YuNet / SCRFD, det_thresh=pack-tuned, det_size=320–640)
  │  bbox, 5 landmarks
  ▼
对齐 (相似变换 → 112×112)
  │  aligned chip
  ▼
嵌入 (MobileFaceNet 128-D / ArcFace 512-D, L2-normalized = normed_embedding)
  │
  ▼
聚类 (HDBSCAN, cosine, with constraints) + 簇质心二次合并
  │
  ▼
人物 (person_id) + 链接
```

### 路线 B 流水线代码骨架

> 路线 B 后核心包不再 `import insightface`；detector / embedder 由 model pack 插件提供，详见 [14 §2](14-model-pack-plugins.md) 与 [10 §2.1](10-model-stack.md)。

**默认 pack `yunet-mfn`（Apache-2.0）**：

```python
from pick_face.platform.pack import discover_packs
import cv2

pack = discover_packs()["yunet-mfn"]            # entry-points 解析
detector = pack.build_detector(model_dir)        # cv2.FaceDetectorYN (YuNet)
embedder = pack.build_embedder(model_dir)        # MobileFaceNet INT8
aligner = pack.build_aligner()                   # ArcFace 5-pt

img = cv2.imread("photo.jpg")
for det in detector.detect(img):
    chip = aligner.warp(img, det.landmarks)      # 112x112 RGB
    emb = embedder.embed(chip)                   # 128-D L2-normalized
    # 写入 SQLite face 表
```

**opt-in pack `buffalo_l`（NC-research，需 `accept_noncommercial_model_license = true`）**：

```python
pack = discover_packs()["buffalo_l"]            # 需先装 pick-face-modelpack-insightface
detector = pack.build_detector(model_dir, det_size=(640, 640))  # SCRFD-10G
embedder = pack.build_embedder(model_dir)        # ArcFace w600k_r50 512-D
# ... 业务代码同上
```

要点：
- `normed_embedding` 已 L2 归一化，**直接 cosine**
- `det_size=(640,640)` 召回高（`buffalo_l`）；`yunet-mfn` 默认 `(320,320)` 已经够用且 ARM 友好
- 合影/极小脸：`det_score` 起步 0.5–0.6（不同 pack 阈值需 [detection] section 调）

## 2. 各阶段细节

### 2.1 检测
- 模型：默认 `yunet-mfn`（Apache-2.0，Pi 3B 可跑）；opt-in `buffalo_l`（SCRFD-10G，高精度，个人/学术）；opt-in `buffalo_sc`（SCRFD-500MF，速度优先）。详见 [10 §2](10-model-stack.md)。
- 输入：长边 ≤ 1600 的 BGR ndarray。
- 阈值：`det_thresh` 由 pack 决定；`yunet-mfn` 推荐 0.5（按真实数据集可调），`buffalo_l` 起步 0.5；阈值过低引入大量假脸，过高漏小脸。
- 输出：`Detection(bbox=(x1,y1,x2,y2), det_score, landmarks=[(x,y)×5])`（`yunet-mfn` 不输出 age/gender）

### 2.2 对齐
- 5 点关键点 → 112×112 仿射变换（ArcFace 标准参考点；复用 [src/pick_face/ingest/align.py](../src/pick_face/ingest/align.py)，不依赖任何 pack）
- 关键点置信度低的脸直接打 `quality<low>` 标记，但不剔除（v0.1 仍参与聚类）

### 2.3 嵌入
- 输出维度由 pack 决定：`yunet-mfn` 128-D，`buffalo_l` / `buffalo_sc` 512-D
- L2 归一化（`embed /= np.linalg.norm(embed) + 1e-12`）
- 质量分（quality）由检测置信度 × 关键点分数 × 模糊度（Laplacian 方差）合成，范围 0–1
- `quality < 0.2` 的脸标记为 `low_quality`，不参与聚类但保留在 `face` 表（供 review）

### 2.4 聚类
- 算法：HDBSCAN，`metric='cosine'`，`min_cluster_size=3`，`min_samples=2`（[01 AC-1](01-product-requirement.md) 锁定为 2），`cluster_selection_method='leaf'`。
- 距离矩阵：因 n 很大时构造 n×n 内存爆炸，**先**用 hnswlib 取 top-50 近邻构图，**再**用 HDBSCAN 的 `metric='precomputed'` 接受预计算距离（仅保留 top-k 边，其余置为 1.0）。
- **二次合并（关键）**：HDBSCAN 输出初始簇后，对所有簇的质心两两算 cosine，**cos ≥ 0.55** 视为同人并合并（可配置）。这一步救回「同一人被切成两簇」的常见问题。
- **触发时机**：
  - **全量重聚类**：每次 `pick-face cluster` 显式触发，或 `--rebuild` 隐式触发。
  - **增量分配**：run 阶段若新增 face ≥ `--recluster-threshold N`（默认 50）或累计距上次聚类 ≥ `--recluster-interval 24h`，则仅对新增 face 调 `Clusterer.incremental_assign`，与现有簇质心比对；否则只对新增 face 找最近簇（cos ≥ 0.55 归入，否则新建候选簇，下次聚类再合并/丢弃）。
- **ID 稳定性**：人物 ID（`cluster.id`）一旦生成即「粘性」—— 二次合并或拆分时，**保留体量较大者的 ID**，合并入的簇 ID 标记为 `merged_into=<survivor>` 并写回 `cluster`。这样输出目录 `person-0007` 即使合并到 `person-0001` 也会在 `<output>/_archive/person-0007/` 留一份旧链接快照（v0.2 提供 `prune` 子命令清理）。
- **人工约束**：
  - `must_link`（合并）：把若干 face 强制并入同一 cluster。
  - `cannot_link`（拆分）：把若干 face 强制不在同一 cluster。
  - 通过 `hdbscan.approximate_predict` + 一遍后处理修复实现。
- 输出：`ClusterResult(labels: np.ndarray[int32], probs: np.ndarray[float])`，`-1` 表示噪声。

### 2.5 置信度
- 簇内一致性 = 簇内所有嵌入到簇中心的平均余弦相似度。
- 单脸归属置信度 = 该脸到其簇中心的余弦相似度（0–1）。
- 报告输出 `low_confidence_faces.json`，**单脸归属相似度 < 0.40** 的脸列出供 review（与 §3 阈值表 `low_confidence=0.40` 一致）。

## 3. 调参指引（后续 v0.1 验证期）

### 3.1 统一阈值表（与 [02 §3](02-technical-pre-research.md) / [01 AC-1](01-product-requirement.md) 保持一致）

| 阈值名 | 值 | 含义 | 调整方向 |
|--------|----|------|----------|
| `det_thresh` | 0.5 | 检测最低置信度 | 误检多 → ↑；漏脸多 → ↓（≥0.3 即可） |
| `quality_min` | 0.2 | 参与聚类的最低质量分 | 噪声多 → ↑ |
| `min_cluster_size` | 3 | HDBSCAN 最小成簇样本 | 漏人 → ↓ 到 2；簇太多 → ↑ 到 5 |
| `min_samples` | 2 | HDBSCAN 核心点要求 | 噪声多 → ↑ |
| `cluster_selection_epsilon` | 0.0 | HDBSCAN 簇合并容差 | 簇过碎 → ↑ 到 0.05 |
| `merge_threshold` | 0.55 | 簇质心二次合并阈值 | 误并多 → ↓ 到 0.45；漏人多 → ↑ 到 0.65 |
| `strong_match` | 0.60 | 强同人：相似度 ≥ 此值不需 review | 视数据校准 |
| `loose_match` | 0.45 | 宽松同人：写入 `output/_review/` | 视数据校准 |
| `different` | 0.30 | 低于此值视为不同人 | 一般不调 |
| `low_confidence` | 0.40 | 单脸到簇质心相似度低于此进 `low_confidence_faces.json` | 一般不调 |

### 3.2 风险

| 参数 | 起点 | 调整方向 | 风险 |
|------|------|----------|------|
| `det_thresh` | 0.5 | 误检多 → 调高；漏脸多 → 调低 | 调低增加噪声簇 |
| `min_cluster_size` | 3 | 漏人 → 调小到 2；簇太多 → 调大到 5 | 调小加剧误并 |
| `min_samples` | 2 | 噪声多 → 调高 | 调高丢失小簇 |
| `cluster_selection_epsilon` | 0.0 | 簇过碎 → 调高到 0.05 | 调高加剧误并 |
| `merge_threshold` | 0.55 | 误并多 → 调小到 0.45；漏人多 → 调大到 0.65 | 双向影响 |

参考经验值（来自社区 InsightFace 实践与 LFW 验证）：
- `cos ≥ 0.6` —— 强同人
- `0.45 ≤ cos < 0.6` —— 宽松同人
- `cos < 0.3` —— 不同人
- Euclidean 在 L2 归一化向量上**不推荐**单独使用（等价关系：`cos ≈ 1 - dist²/2`）

## 4. 性能预期

- SCRFD 检测 ≈ 几十毫秒 / 图（中端 GPU）到 200–500ms（CPU，中端 x86 1080p JPG）；embedding 比检测快。
- 1080×1500 JPEG，CPU（i7-12700 单核 ~3.5GHz）：约 0.4–0.6 秒/图（buffalo_l）。
- GPU（RTX 3060）：约 0.03–0.05 秒/图。
- 10k 张图 1080p：CPU ≈ 1.5–2.5 小时；GPU ≈ 10 分钟。
- HDBSCAN（10k 脸）：CPU ≈ 30–90 秒。
- RAW 加速：**先读 EXIF thumbnail**，thumbnail 上能检出脸就跳过 rawpy；否则中端 CPU 解码一张 24MP RAW 约 0.5–2s，**对 RAW 必须 thumbnail + 缓存**，否则扫描动辄数小时。
- 关键加速手段：InsightFace 批处理（`FaceAnalysis` 自带）、降低 `det_size`、EXIF 缩略图优先、ONNX 推理线程池。

主要瓶颈在 CPU 推理与 IO 解码。

## 5. 评测方法

- **公开基准**（CI 自动化跑，输出 `eval_report.json`）：
  - LFW 5,749 人 13,233 张（sanity check，ROC AUC ≥ 0.99）。
  - CALFW（跨年龄）10,000 张（pairwise 准确率）。
  - CPLFW（跨姿态）5,749 人 11,652 张。
  - 1:1 验证：1,000 随机同人/不同人对，TPR@FPR=1e-3 ≥ 0.95。
- **聚类评估**：在公开基准子集上做聚类（已知 ground-truth person 标签），计算 pairwise precision/recall、B³ F1、ARI。
- **真实基准**：项目内置一个去标识化 demo 集（**50 个不同人，每人在 5–30 张之间随机；总图数约 1000 张**），用于回归与 AC-1 验证（与 [01 §5](01-product-requirement.md) / [06 §3 fixture](06-engineering-plan.md#3-测试策略) 同源）。
- **指标**：
  - Pairwise Precision = 「被分到同一簇的人脸对中，真为同人的比例」
  - Pairwise Recall = 「真为同人的人脸对中，被分到同一簇的比例」
  - B³ F1 / Adjusted Rand Index 作为补充
- **基线**：face_recognition + DBSCAN、InsightFace + 阈值凝聚，作为 v0.1 的对比参考。
