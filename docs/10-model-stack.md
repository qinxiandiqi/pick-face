# 10 模型栈：人脸识别涉及哪些模型、为什么选它们

> 文档版本：v0.2（路线 B 落地稿） · 2026-08-07
> 范围：把分散在 02/03/04/05/06/09 里的"模型 + 选型理由"集中收口，按 **model pack** 维度组织。
> **本文是单一权威解读**。任何与本文件冲突的章节（README / 01 / 03 / 06 / 08 / 09 / 11），以本文件为准。
> 关联：[02 §2.1 库对比矩阵](02-technical-pre-research.md) · [11 §2 商业合规](11-commercial-compliance.md) · [13 Pi / ARM 支持](13-raspberry-pi-support.md) · [14-model-pack-plugins.md](14-model-pack-plugins.md)

## 0. 摘要（60 秒版）

`pick-face` 从 v2.0 起（路线 B）采用 **model pack 插件架构**：

- **核心包** (`pick-face`) 通过 Python entry-points `pick_face.model_packs` 发现已安装的 model pack
- **每个 pack** 是独立 PyPI 包，自带 detector + embedder + 权重 URL + SHA256 + license 声明
- **默认 pack** 是 `yunet-mfn`（OpenCV Zoo YuNet + MobileFaceNet INT8，Apache-2.0）—— 让树莓派 3B 1 GB RAM 也能跑
- **可选 pack** `buffalo_l` / `buffalo_sc` / `antelopev2` 来自 InsightFace，独立插件包，**默认不安装**
- **AC-9 商业合规护栏**仍生效，但仅对 `LicenseClass.NC_RESEARCH` 的 pack 触发 —— `yunet-mfn` 默认放行

| Pack id | 体积 | RAM | LFW | LicenseClass | Pi 3B 1GB |
|---|---|---|---|---|---|
| **yunet-mfn**（默认） | **5 MB** | **150 MB** | 99.50% | PERMISSIVE | ✅ |
| buffalo_sc (InsightFace) | 35 MB | 500 MB | 99.65% | NC_RESEARCH | ⚠️ |
| buffalo_l (InsightFace) | 325 MB | 2.5 GB | 99.83% | NC_RESEARCH | ❌ |

## 1. 模型栈总览（路线 B 视角）

```
                       ┌─────────────────────────────────────────────┐
                       │              pick-face pipeline             │
                       └─────────────────────────────────────────────┘
                                       │           │           │
                ┌──────────────────────┘           │           └────────────────────┐
                ▼                                  ▼                                ▼
         ① 图像解码                         ② Detector                       ③ Aligner
   Pillow + pillow-heif + rawpy         (pack.build_detector)             (pack.build_aligner,
   (纯算法, 无 ML)                       └─ SCRFD-10G (buffalo_l)              纯几何, 无 ML)
                                          └─ SCRFD-500MF (buffalo_sc)              ArcFace 5-pt
                                          └─ YuNet (yunet-mfn)               复用核心代码

                                       │
                                       ▼
                                ④ Embedder
                          (pack.build_embedder)
                          └─ ArcFace w600k_r50 512-D (buffalo_l)
                          └─ MobileFaceNet 512-D (buffalo_sc)
                          └─ MobileFaceNet INT8 128-D (yunet-mfn)

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

**关键变化**：②③④ 三个模块在 v1.x 是固定 InsightFace 实现；v2.0 起通过 `pick_face.platform.pack.discover_packs()` 加载任意已注册的 pack，业务代码**完全不变**。

## 2. Model Pack 列表

### 2.1 `yunet-mfn`（默认 / Apache-2.0）

**Detector**：YuNet (`face_detection_yunet_2023mar.onnx`)
- **来源**：OpenCV Zoo — https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
- **作者**：ShiqiYu, et al. (2022)
- **论文**：[YuNet: A Tiny Millisecond-level Face Detector](https://github.com/ShiqiYu/OpenSFD)
- **体积**：~363 KB
- **输入**：任意尺寸 BGR ndarray
- **输出**：每张图若干 `(x, y, w, h, *5 landmarks, score)` 行
- **Pi 3B 推理**：~150 ms / 图（Cortex-A53 NEON）

**Embedder**：MobileFaceNet INT8 (`face_recognition_mobilefacenet_20221220_int8.onnx`)
- **来源**：OpenCV Zoo — https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_mobilefacenet
- **作者**：WuZhen, InsightFace 训练（2020），OpenCV Zoo 量化（2022）
- **论文**：[MobileFaceNets: Efficient CNNs for Accurate Real-Time Face Verification on Mobile Devices](https://arxiv.org/abs/1804.07573)
- **体积**：~5 MB（INT8 量化版）
- **输入**：112×112 BGR float32 in [-1, 1]
- **输出**：128-D float32 (L2-normalized)
- **LFW 精度**：99.50%（INT8 量化后）

**为什么是它**（[02 §2.1](02-technical-pre-research.md) + [13 §2](13-raspberry-pi-support.md) 选型矩阵）：

| 维度 | yunet-mfn | buffalo_l | buffalo_sc |
|---|---|---|---|
| 体积 | **5 MB** | 325 MB | 35 MB |
| RAM 常驻 | **150 MB** | 2.5 GB | 500 MB |
| Pi 3B 跑 | **✅** | ❌ | ⚠️ |
| LFW 精度 | 99.50% | 99.83% | 99.65% |
| License | **Apache-2.0** | NC-research | NC-research |
| 商用零摩擦 | **✅** | ❌ | ❌ |
| AC-9 gate | **不触发** | 触发 (要 ack) | 触发 (要 ack) |
| 5-pt landmark | YuNet 自带 | InsightFace 2d106det (16 MB) | 同上 |
| 维度 | 128-D | 512-D | 512-D |
| ARM NEON | ✅ (INT8 SDOT) | ⚠️ 仅 ONNX ARM64 | ✅ |

**结论**：LFW 掉 0.33 pp 换来 **Pi 3B 能跑 + 商用零摩擦 + 100× 体积减小**，对个人照片整理场景**绝对划算**。

### 2.2 `buffalo_l`（InsightFace / NC-research，opt-in）

**Detector**：SCRFD-10G (`det_10g.onnx`)
- **论文**：[Sample and Computation Redistribution for Efficient Face Detection](https://arxiv.org/abs/2105.04714)
- **体积**：16 MB
- **优点**：WIDER FACE hard subset 第一；带 5-pt landmark

**Embedder**：ArcFace w600k_r50 (`w600k_r50.onnx`)
- **论文**：[ArcFace: Additive Angular Margin Loss for Deep Face Recognition](https://arxiv.org/abs/1801.07698)
- **体积**：166 MB
- **输入**：112×112 RGB float32 in [-1, 1]
- **输出**：512-D float32 (L2-normalized)
- **训练**：MS-Celeb-1M 清洗后 ~60 万人 / ~190 万张
- **LFW 精度**：99.83%

**为什么用它**（在 x86-64 + NVIDIA GPU 上仍然是精度天花板）：

- **精度 SOTA**：LFW / CALFW / CPLFW / IJB-C 上长期领先
- **InsightFace 包装完善**：与 SCRFD 同包
- **缺点**：体积大 / RAM 多 / NC-research license / 在 ARM 上弱

### 2.3 `buffalo_sc`（InsightFace / NC-research，opt-in）

**Detector**：SCRFD-500MF (`det_500m.onnx`)
- **体积**：~1.3 MB
- **优点**：体积小，精度 ~99.65% LFW
- **缺点**：仍是 InsightFace，license 同样 NC-research

**Embedder**：MobileFaceNet (`w600k_mbf.onnx`)
- **体积**：~16 MB
- **输出**：512-D

**为什么用它**：在 Pi 4B 4 GB / RK3588 / x86 上能跑的"老牌小 pack"，但商用仍然被 InsightFace license 卡。

### 2.4 `antelopev2`（InsightFace / NC-research，opt-in）

跟 buffalo_l/sc 类似但抗遮挡更强；体积 ~180 MB；商用 license 同样 NC-research。

### 2.5 自训 pack（商业首选）

```toml
[runtime]
pack = "my-arcface-r50"   # 你自己训的
model_dir = "/srv/models/commercial"
```

详见 [11 §2.2 选项 A](11-commercial-compliance.md)。自训权重一般是 `LicenseClass.PERMISSIVE`（看你训练数据的 license），由你控制 license。

## 3. ONNX Runtime（推理框架，非模型）

**为什么是它**（不是 PyTorch / TensorFlow / TensorRT 独占）：

- **多 EP**：同一份 ONNX 能在 CPU / CUDA / DirectML / TensorRT 上跑，**用户机器差异被 ONNX EP 抽象掉**
- **跨平台 wheel**：Linux/macOS/Windows、x86_64/arm64 都有官方预编译
- **轻量**：相比 PyTorch ~800MB、TF ~500MB，ONNX Runtime CPU 仅 ~25 MB
- **pack 自带依赖**：核心包不再 `import onnxruntime`，**每个 pack 自己声明依赖**

**EP 选型**：

| 平台 | 首选 EP | 备选 | Pack 需声明 |
|---|---|---|---|
| Windows + NVIDIA | CUDA / TensorRT | DirectML | `onnxruntime-gpu` |
| Windows 无 NVIDIA | DirectML | CPU | `onnxruntime-directml` |
| Linux + NVIDIA | CUDA / TensorRT | CPU | `onnxruntime-gpu` |
| macOS Apple Silicon | CPU (NEON) | CoreML (自绑) | `onnxruntime` |
| **ARM Linux (Pi / RK3588)** | **CPU (NEON)** | NPU (M6+) | `onnxruntime` |
| Linux + AMD | ROCm / MIGraphX | CPU | `onnxruntime-gpu` |

`--provider auto` 探测顺序：`cuda` → `directml` → `cpu`，失败链路在 `report.md` 顶部 `Warnings` 列出。

## 4. 算法 / 数据结构（不依赖神经网络）

虽然不是 ML 模型，但同样出现在人脸识别流程里、影响准确率与性能。

### 4.1 hnswlib（ANN 索引）

**是什么**：Hierarchical Navigable Small World 图的 C++ 实现 + Python 绑定。

**为什么用它**：
- **轻量**：纯 C++，单 .so/wheel
- **速度快**：1 万次 query 在 10 万 512-D 向量上 < 50ms
- **持久化**：可直接 `save_index` / `load_index`
- **可增量更新**：`add_items` 追加、`mark_deleted` 软删

**在本项目的作用**：
- HDBSCAN 距离矩阵构造：n² 内存爆炸 → 用 hnswlib 取 top-50 近邻构图
- 增量分配：新脸与现有质心比对不用全表扫

**备选**：Annoy（更慢但更易调试）、FAISS（生态最全但 wheel 体积大）。

### 4.2 HDBSCAN（层次密度聚类）

**是什么**：基于层次密度估计 + 簇稳定度选阈值的无监督聚类算法。

**为什么用它**：
- **无需指定 k**（人数未知，符合"按人整理"场景）
- **对密度变化鲁棒**（家庭合影中既有大头照又有远景小脸）
- **能标噪声**（-1 标签直接进 `_review/`）
- **可注入人工约束**（must_link/cannot_link）

**参数**（[04 §3.1 阈值表](04-algorithm-pipeline.md)）：
- `min_cluster_size=3`（单人也保留簇需要降到 2）
- `min_samples=2`
- `metric='cosine'`
- `cluster_selection_method='leaf'`

**维度差异**：yunet-mfn 输出 128-D，buffalo_l/sc 输出 512-D。HDBSCAN 对维度不敏感，但 cosine 阈值在不同维度下数值意义不同。**`yunet-mfn` 的 merge_threshold = 0.55 是默认；用 buffalo_l 时调到 0.45 更稳**（[04 §3.1 调整表](04-algorithm-pipeline.md)）。

### 4.3 xxh3_64（content hash）

**是什么**：Yann Collet 设计的非加密极快哈希，64-bit 版本。

**为什么用它**：
- **快**：单核 ≥ 10 GB/s；扫 1 万张图 1 秒内出 hash
- **64-bit 足够**：用作幂等键，碰撞概率可忽略
- **Python 原生绑定**：`xxhash` 包

**在本项目的作用**：幂等键 `(abs_path, size, mtime, hash)`；快速判定"是不是同一图"。

### 4.4 Laplacian 方差（模糊度）

**是什么**：图像二阶导数的方差，>100 算清晰，< 20 算糊。

**为什么用它**：
- **零成本**：opencv 1 行代码
- **可解释**：调参人员一眼看懂
- **足够好**：作为 `quality = f(det_score, kps_residual, blur)` 的一个分量

## 5. 许可与合规

| Pack / 库 | 许可证 | 商业可用 | AC-9 gate |
|---|---|---|---|
| **yunet-mfn**（OpenCV Zoo） | **Apache-2.0** | **✅** | 不触发 |
| buffalo_l / buffalo_sc / antelopev2 权重 | InsightFace 自定义 | ❌ | 触发 |
| onnxruntime | MIT | ✅ | — |
| hnswlib | Apache-2.0 | ✅ | — |
| HDBSCAN | BSD | ✅ | — |
| Pillow / OpenCV / NumPy / xxhash | HPND / Apache-2.0 / BSD | ✅ | — |
| pillow-heif | BSD | ✅ | — |
| rawpy (LibRaw) | LGPL + LibRaw 许可 | ⚠ 视使用方式 | — |
| face_recognition (备选) | MIT | ✅ | — |

**默认 pack 已经是 Apache-2.0** —— pick-face 项目**不**分发 `yunet-mfn` 权重（5 MB onnx 不入仓），但**整个核心包不再诱导用户使用 NC-research 模型**。LICENSE / README 顶部明记"默认商用合规"。

> 📌 **商业部署的完整路径（含自训脚本、合规配置、检测项）见 [11-commercial-compliance.md](11-commercial-compliance.md)**。本文仅给技术选型与许可事实。

## 6. Model 版本与升级策略

- **版本字段**：`face.model_version` 形如 `"yunet-mfn@2026-08"` 或 `"buffalo_l@2023-11"`，embedding 不兼容时**重算**而不是混用
- **换 pack**：跑 `pick-face rebuild --pack <new_pack>`，写一条 migration 把 `face.model_version != 当前` 全部重算
- **双轨验证期**：新 pack 与旧 pack 并行跑 1 周，B³ F1 在 demo 集上不降才能切默认（[04 §5 评测方法](04-algorithm-pipeline.md)）

## 7. 模型下载与离线部署

**在线**：
```bash
pick-face init-models --pack yunet-mfn --allow-network --yes
# 拉 ~5 MB from GitHub release
```

**离线**（4 种部署形态）：
1. 环境变量：`PICK_FACE_MODEL_DIR=/srv/models`。
2. `pick-face.toml` 的 `[runtime] model_dir = "/srv/models"`。
3. 内网 HTTP 镜像（自部署 pick-face-pack-registry）。
4. 完全离线：所有资源本地化。

CI 用 `actions/cache` 缓存 `model_dir/`，避免每次 job 重新下载。

> ⚠ **商业部署警告**：CI 缓存会让 `*.onnx` 长期驻留在 CI runner 缓存里——**发布到公开 PyPI / 公开 docker 镜像前，务必清空** `model_dir`、容器内一切 `*.onnx`。详见 [11 §3.7](11-commercial-compliance.md)。

## 8. 模型总成本与体积（v2.0 默认安装）

| 项 | 体积 | 备注 |
|---|---|---|
| `pick-face` 核心 wheel | ~3 MB | 不含 onnxruntime |
| `onnxruntime` (CPU) | ~25 MB | 走 pip |
| `yunet-mfn` 权重 | **~5 MB** | 运行时下载 |
| **`pip install pick-face` 合计** | **~30 MB** | — |
| `onnxruntime-gpu` (可选) | ~250 MB | 走 pip（CUDA 库另需 ~3GB） |
| `pick-face-modelpack-insightface` 插件 | ~5 MB | 仅作 Python 适配层；权重另下 |
| `buffalo_l` 权重 (opt-in) | ~325 MB | 单独下载；仅个人/研究 |

## 9. 引用与延伸阅读

- [02 §2.1 库对比矩阵](02-technical-pre-research.md)
- [04 §2 检测/对齐/嵌入/聚类参数](04-algorithm-pipeline.md)
- [05 §3 HNSW 同步与崩溃恢复](05-data-and-storage.md)
- [07 ADR-001/002/006/009](07-risk-and-decisions.md) — HDBSCAN / 进程模型 / SQLite 权威
- [09 人脸识别流程](09-face-recognition-pipeline.md)
- [11 §2.2 商业合规四条路径](11-commercial-compliance.md)
- [13 Pi / ARM 支持](13-raspberry-pi-support.md)
- [14-model-pack-plugins.md](14-model-pack-plugins.md) — 插件契约
- SCRFD 论文 — https://arxiv.org/abs/2105.04714
- ArcFace 论文 — https://arxiv.org/abs/1801.07698
- YuNet 项目 — https://github.com/ShiqiYu/OpenSFD
- MobileFaceNet — https://arxiv.org/abs/1804.07573
- OpenCV Zoo — https://github.com/opencv/opencv_zoo
- ONNX Runtime EPs — https://onnxruntime.ai/docs/execution-providers/
- HDBSCAN docs — https://hdbscan.readthedocs.io/
- hnswlib — https://github.com/nmslib/hnswlib
- xxhash — https://github.com/Cyan4973/xxHash