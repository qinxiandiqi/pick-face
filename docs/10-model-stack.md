# 10 模型栈：人脸识别涉及哪些模型、为什么选它们

> 文档版本：v0.1（评审稿） · 2026-07-30
> 范围：把分散在 02/03/04/05/06/09 里的"模型 + 选型理由"集中收口。
> 单一权威解读在 [08 §6 最终方案](08-review-notes.md)。

## 0. 摘要

`pick-face` 涉及**两类**模型：
1. **机器学习模型**（GPU/CPU 推理）—— 5 个：SCRFD 检测、ArcFace 嵌入、AdaFace 备选、MediaPipe 备选、ONNX Runtime（推理框架而非模型）。
2. **算法 / 数据结构**（不依赖训练好的神经网络）—— 3 个：hnswlib（ANN）、HDBSCAN（聚类）、xxh3（content hash）。本节一并说明它们为什么出现在栈里。

ML 模型默认全用 **InsightFace `buffalo_l`** 包（含 SCRFD-10G 检测 + 5 点关键点 + ArcFace w600k_r50 嵌入 + 性别/年龄属性），由 **ONNX Runtime** 跑。

## 1. 模型栈总览

```
                       ┌─────────────────────────────────────────────┐
                       │              pick-face pipeline             │
                       └─────────────────────────────────────────────┘
                                       │           │           │
                ┌──────────────────────┘           │           └────────────────────┐
                ▼                                  ▼                                ▼
         ① 图像解码                         ② 人脸检测                        ③ 人脸对齐
   Pillow + pillow-heif + rawpy     InsightFace SCRFD-10G            InsightFace 内置 5点仿射
   (纯算法, 无 ML)                   (buffalo_l 包含)                (确定性几何变换)

                                       │
                                       ▼
                                ④ 人脸嵌入
                          InsightFace ArcFace w600k_r50
                                (buffalo_l 包含)
                                       │
                                       ▼
                                ⑤ 模糊度评估
                          Laplacian 方差 (无 ML)

                                       │
                                       ▼
                                ⑥ ANN 检索
                             hnswlib (无 ML)

                                       │
                                       ▼
                                ⑦ 聚类
                            HDBSCAN (无 ML)

                                       │
                                       ▼
                          ⑧ content hash 去重
                              xxh3_64 (无 ML)
```

## 2. ML 模型（神经网络）

### 2.1 InsightFace `buffalo_l`（默认） / `buffalo_sc`（`--fast`）

**是什么**：
InsightFace 官方打包的一组预训练 ONNX 模型，名字叫"水牛"。`buffalo_l` = SCRFD-10G 检测 + 5 点关键点定位 + ArcFace(w600k_r50) 嵌入 + 年龄/性别属性头。`buffalo_sc` = 同样的组件但用更轻量骨干（mobilefacenet/mobilenet），速度优先。

**文件大小**：
- `buffalo_l`：检测 ~92 MB + 嵌入 ~261 MB ≈ 350 MB
- `buffalo_sc`：合计约 100 MB

**为什么是它**（[02 §2.1](02-technical-pre-research.md) 选型矩阵）：

| 维度 | InsightFace buffalo_l | face_recognition (dlib) | DeepFace wrapper | OpenCV DNN + 自拼 | MediaPipe |
|------|----------------------|------------------------|------------------|------------------|-----------|
| 准确率（LFW） | 99.78%+ | 99.38% | 视 backend | 视模型 | 仅检测/关键点 |
| 维护活跃度 | 高，2024–2026 仍在出权重 | 长期低活跃；Py 3.11/3.12 缺 wheel | 活跃 | 散落 | 高 |
| 部署难度 | 中（首次需联网下载 ONNX） | 高（dlib 编译链 Win/AS/Linux 都踩坑） | 低 | 高 | 低 |
| 许可证 | 代码 MIT / **模型非商业研究** | MIT + Boost | MIT + 视 backend | Apache-2.0 | Apache-2.0 |
| 离线能力 | ✅（自托管 ONNX） | ✅ | ⚠（每次新会话可能下载） | ✅ | ✅ |
| 跨平台 | CPU/CUDA/DirectML/TensorRT | 受限于 dlib | 多 backend | 自拼 | 全 |

**结论**：在「离线 + 跨平台 + 高准确率 + 可替换接口」四点上同时胜出，**MVP 唯一主线**。

**可替换性**：v0.1 通过 [03 §5 `FaceDetector` / `FaceEmbedder` Protocol](03-architecture-design.md) 抽象，未来要换 AdaFace / MobileFaceNet / 自训模型只需实现 Protocol，无需改业务代码（[ADR-001](07-risk-and-decisions.md)）。

### 2.2 SCRFD-10G（buffalo_l 内的检测器）

**是什么**：InsightFace 2021 年发布的检测器，**S**ample and **C**omputation **R**edistribution for **F**ace **D**etection。论文：https://arxiv.org/abs/2105.04714

**为什么用它**（不是 RetinaFace、MTCNN、YOLO-face、MediaPipe BlazeFace）：
- **精度 SOTA** 在 WIDER FACE 三个子集（easy / medium / hard）均第一。
- **轻量**：10G FLOPs 的版本在 CPU 上也能跑（100~200ms/图）。
- **输出带 5 个关键点**（双眼、鼻尖、嘴角）—— 下游 ArcFace 对齐直接用，省一个模型。
- **ONNX 友好**：InsightFace 官方已转好；可纯本地运行。

**输入**：BGR ndarray + 检测尺度 `det_size`（默认 640×640）。
**输出**：每张图若干 `bbox + 5 kps + det_score`。

**替代 / 兜底**：
- `buffalo_sc` 用更小骨干（mobilenet 系）做 `--fast` 选项。
- v0.2 评估 MediaPipe BlazeFace 作大图（>4K）兜底（更快但无 5 点关键点，得自己接 landmark 模型）。

### 2.3 ArcFace w600k_r50（buffalo_l 内的嵌入）

**是什么**：InsightFace 2018 年提出的损失函数 + 配套骨干。在 MS-Celeb-1M 清洗后的 ~60 万人 / ~190 万张图上预训练，骨干是 ResNet-50。
- 论文：https://arxiv.org/abs/1801.07698
- 输出 512 维 L2 归一化向量。

**为什么用它**（不是 FaceNet、VGG-Face、CosFace、SphereFace、AdaFace）：
- **几何清晰**：训练时强制同人在单位球上的夹角 ≥ 某角度（m），不同人的夹角 ≤ 另一角度（m+α）。推理时直接 cosine 即可。
- **大预训练集**：w600k（60 万人）是当时公开最大；今天仍是。
- **OnPar 性能** 在 LFW、CALFW、CPLFW、IJB-C 上长期领先或并列第一。
- **InsightFace 包装完善**：与 SCRFD 同包，无缝拼接。

**输入**：112×112 RGB 对齐人脸。
**输出**：512-D float32 向量（**已 L2 归一化**）。

**替代 / 兜底**：
- **AdaFace**（ICCV 2022）：对低质量人脸更鲁棒，可作 v0.2 升级选项（需自转 ONNX）。
- **MobileFaceNet**：极小（~5MB），适合嵌入式 / 端侧；v0.1 不考虑。
- **ArcFace-R100 / R200**：更大骨干，准确率略高但 CPU 推理 1.5–2× 慢；v0.1 不考虑。

### 2.4 MediaPipe Face Detection（v0.2 备选，不在 v0.1 流水线）

**为什么提它**：当输入是超大图（手机 RAW 50MP、扫描件）和要快速粗筛时，BlazeFace 极快。**v0.1 不引入**；若 v0.2 评估发现 RAW 解码是瓶颈再补。

### 2.5 ONNX Runtime（推理框架，非模型）

**为什么是它**（不是直接用 PyTorch / TensorFlow / TensorRT 独占）：
- **多 EP**：同一份 ONNX 能在 CPU / CUDA / DirectML / TensorRT / ROCm 上跑，**用户机器差异被 ONNX EP 抽象掉**。
- **跨平台 wheel**：Linux/macOS/Windows、x86_64/arm64 都有官方预编译。
- **轻量**：相比 PyTorch ~800MB、TF ~500MB，ONNX Runtime CPU 仅 ~25MB。
- **InsightFace 官方支持**：`providers=["CPUExecutionProvider" | "CUDAExecutionProvider" | ...]`。

**EP 选型**（[05 §4.2 权威表](05-data-and-storage.md)）：

| 平台 | 首选 EP | 备选 |
|------|---------|------|
| Windows + NVIDIA | CUDA / TensorRT | DirectML |
| Windows 无 NVIDIA | DirectML | CPU(MLAS) |
| Linux + NVIDIA | CUDA / TensorRT | CPU |
| macOS Apple Silicon | CPU | CoreML（需自绑） |
| Linux + AMD | ROCm / MIGraphX | CPU |

`--provider auto` 探测顺序：`cuda` → `directml` → `cpu`，失败链路在 `report.md` 顶部 `Warnings` 列出。

## 3. 算法 / 数据结构（不依赖神经网络）

虽然不是 ML 模型，但同样出现在人脸识别流程里、影响准确率与性能。

### 3.1 hnswlib（ANN 索引）

**是什么**：Hierarchical Navigable Small World 图的 C++ 实现 + Python 绑定。**不是 ML**，是"在百万级向量里找最近邻"的近似算法。

**为什么用它**（不是 FAISS / Annoy / scikit-learn NearestNeighbors）：
- **轻量**：纯 C++，单 .so/wheel，无 CUDA 强依赖；Win/macOS/Linux 都有预编译。
- **速度快**：1 万次 query 在 10 万 512-D 向量上 < 50ms。
- **持久化**：可直接 `save_index` / `load_index` 到磁盘（[05 §3](05-data-and-storage.md)）。
- **可增量更新**：`add_items` 追加、`mark_deleted` 软删。

**在本项目的作用**：
- HDBSCAN 距离矩阵构造（[04 §2.4](04-algorithm-pipeline.md)）：n² 内存爆炸 → 用 hnswlib 取 top-50 近邻构图。
- 增量分配（[04 §2.4](04-algorithm-pipeline.md)）：新脸与现有质心比对不用全表扫。

**备选**：Annoy（更慢但更易调试）、FAISS（生态最全但 wheel 体积大）。

### 3.2 HDBSCAN（层次密度聚类）

**是什么**：基于层次密度估计 + 簇稳定度选阈值的无监督聚类算法。论文：https://link.springer.com/article/10.1007/s10994-013-5422-0

**为什么用它**（不是 k-means / DBSCAN / 谱聚类 / 凝聚层次）：
- **无需指定 k**（人数未知，符合"按人整理"场景）。
- **对密度变化鲁棒**（家庭合影中既有大头照又有远景小脸）。
- **能标噪声**（-1 标签直接进 `_review/`）。
- **可注入人工约束**（[04 §2.4 must_link/cannot_link](04-algorithm-pipeline.md)）。

**参数**（[04 §3.1 阈值表](04-algorithm-pipeline.md)）：
- `min_cluster_size=3`（单人也保留簇需要降到 2）
- `min_samples=2`（[01 AC-1](01-product-requirement.md) 锁定）
- `metric='cosine'`
- `cluster_selection_method='leaf'`（更细粒度，便于二次合并救回）

### 3.3 xxh3_64（content hash）

**是什么**：Yann Collet 设计的非加密极快哈希，64-bit 版本。**不是 ML**，是"两个文件是不是字节级一致"的判定。

**为什么用它**（不是 SHA-256 / MD5）：
- **快**：单核 ≥ 10 GB/s；扫 1 万张图 1 秒内出 hash。
- **64-bit 足够**：用作幂等键，**碰撞概率可忽略**（50% 碰撞需要 ~50 亿文件）。
- **Python 原生绑定**：`xxhash` 包。

**在本项目的作用**：[03 §5 数据流](03-architecture-design.md) 的幂等键 `(abs_path, size, mtime, hash)`；快速判定"是不是同一图"。

### 3.4 Laplacian 方差（模糊度）

**是什么**：图像二阶导数的方差，>100 算清晰，< 20 算糊。**不是 ML**，是经典图像质量度量。

**为什么用它**（不引 CNN 质量模型）：
- **零成本**：opencv 1 行代码。
- **可解释**：调参人员一眼看懂。
- **足够好**：作为 `quality = f(det_score, kps_residual, blur)` 的一个分量。

**替代**：v0.2 评估 BRISQUE / NIMA 等学习型质量模型，但收益不一定值得引入新依赖。

## 4. 许可与合规

| 模型 / 库 | 许可证 | 商业可用？ |
|----------|--------|-----------|
| InsightFace 代码 | MIT | ✅ |
| InsightFace `buffalo_*` 模型权重 | **非商业研究用途** | ❌（README 顶明记） |
| ONNX Runtime | MIT | ✅ |
| hnswlib | Apache-2.0 | ✅ |
| HDBSCAN | BSD | ✅ |
| Pillow / OpenCV / NumPy | HPND / Apache-2.0 / BSD | ✅ |
| pillow-heif | BSD | ✅ |
| rawpy (LibRaw) | LGPL + LibRaw 许可 | ⚠ 视使用方式 |
| xxhash | BSD | ✅ |
| face_recognition (备选) | MIT | ✅ |

**pick-face 主包建议许可**：Apache-2.0。模型许可与代码许可解耦，README 顶部明记「默认不联网 + 模型来源 + 非商用提示」（[01 §6](01-product-requirement.md)）。

> 📌 **商业部署的完整路径（含自训脚本、合规配置、检测项）见 [11-commercial-compliance.md](11-commercial-compliance.md)**。本文仅给技术选型与许可事实，合规边界、用户义务、配置项语义由 11 单一权威。

## 5. 模型版本与升级策略

- **版本字段**：在 `face` 表加 `model_version`（如 `"buffalo_l@2023-11"`），embedding 不兼容时**重算**而不是混用。
- **升 buffalo_l**：改 pyproject 依赖 + 写一条 migration 把 `face` 表 `model_version != 当前` 全部重算（`pick-face reindex --model buffalo_l`）。
- **换模型族**（如换 AdaFace）：直接重算全部 `face.embedding`，**不动 SQLite schema**（BLOB 不变）。
- **双轨验证期**：新模型与旧模型并行跑 1 周，B³ F1 在 demo 集上不降才能切默认（[04 §5 评测方法](04-algorithm-pipeline.md)）。

## 6. 模型总成本与体积

| 项 | 体积 | 备注 |
|----|------|------|
| `buffalo_l` 检测 | ~92 MB | 一次性下载 |
| `buffalo_l` 嵌入 | ~261 MB | 一次性下载 |
| `buffalo_sc` | ~100 MB | 一次性下载（备选） |
| `onnxruntime` (CPU) | ~25 MB | 走 pip |
| `onnxruntime-gpu` | ~250 MB | 走 pip（CUDA 库另需 ~3GB） |
| **首次安装合计** | **~600 MB（CPU）/ ~4 GB（GPU）** | — |

## 7. 模型下载与离线部署

**在线**（[03 §11.5](03-architecture-design.md)）：
```
pick-face init-models --allow-network   # 触发 InsightFace 下载器
```

**离线**（4 种部署形态）：
1. `INSIGHTFACE_HOME=/srv/models` 环境变量。
2. `pick-face.toml` 的 `[runtime] model_dir = "/srv/models"`。
3. 内网 HTTP 镜像：`[runtime] model_index_url = "https://internal.corp/models/"`。
4. 完全离线：所有资源本地化（pip 镜像 + 模型文件 + extras 离线安装）。

CI 用 `actions/cache` 缓存 `~/.insightface/models/`，避免每次 job 重新下载。

> ⚠ **商业部署警告**：CI 缓存会让 `buffalo_l` 长期驻留在 CI runner 缓存里——**发布到公开 PyPI / 公开 docker 镜像前，务必清空** `~/.insightface/`、`pick-face` 容器内一切 `*.onnx`。详见 [11 §3.7 文档显眼位置](11-commercial-compliance.md)。

## 8. 引用与延伸阅读

- [02 技术预研 §2.1](02-technical-pre-research.md) — 库对比矩阵
- [04 算法流水线 §2](04-algorithm-pipeline.md) — 检测/对齐/嵌入/聚类参数
- [05 数据与存储 §3](05-data-and-storage.md) — HNSW 同步与崩溃恢复
- [07 ADR-001/002/006/009](07-risk-and-decisions.md) — InsightFace / HDBSCAN / 进程模型 / SQLite 权威
- [09 人脸识别流程](09-face-recognition-pipeline.md) — 模型出现在哪个阶段
- InsightFace python-package — https://github.com/deepinsight/insightface/blob/master/python-package/README.md
- SCRFD 论文 — https://arxiv.org/abs/2105.04714
- ArcFace 论文 — https://arxiv.org/abs/1801.07698
- ONNX Runtime EPs — https://onnxruntime.ai/docs/execution-providers/
- HDBSCAN docs — https://hdbscan.readthedocs.io/
- hnswlib — https://github.com/nmslib/hnswlib
- xxhash — https://github.com/Cyan4973/xxHash
