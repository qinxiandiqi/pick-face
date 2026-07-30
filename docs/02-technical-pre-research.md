# 02 技术预研报告

> 文档版本：v0.1（预研稿） · 2026-07-30 · 状态：**待评审**

## 1. 调研范围与方法

- **目标**：为「本地离线按人脸整理图片」挑选成熟、可维护、合规的 Python 技术栈；明确关键算法参数与风险。
- **方法**：对比主流人脸识别/聚类库的当前状态、许可证、性能与生态；参考公开 benchmark（InsightFace 官方报告、face_recognition 文档、HDBSCAN/AGNES 论文与社区实践）。
- **结论属性**：建议性结论，不绑定到具体实现细节；待 v0.1 原型验证后定稿。

## 2. 候选技术栈对比

### 2.1 人脸检测 + 嵌入（主任务）

| 方案 | 维护/活跃 | 许可证 | 嵌入维度 | 备注 | 结论 |
|------|---------|-------|---------|------|------|
| **InsightFace (buffalo_l/sc) + ONNX Runtime** | deepinsight/insightface 持续更新；2024–2026 仍在出新权重 | 代码 **MIT**；预训练模型 **非商业研究用途** | 512 | SCRFD 检测 + ArcFace(w600k_r50)；LFW 99.78%+ | **MVP 推荐**：可自托管 ONNX、CPU 默认、可换 EP |
| **DeepFace (serengil)** | 活跃，本质是多后端 wrapper | MIT（注意各 backend 自带许可） | 视 backend | 经常自动下载模型；与 InsightFace 共用同一 backend 时能力等价 | 备选 / 用于多模型实验 |
| **face_recognition (dlib)** | 长期低活跃；Py 3.11/3.12 缺 wheel，需自编译 | MIT / Boost(BSD) | 128 | dlib 编译链在 Windows / Apple Silicon / Linux 频繁踩坑；LFW 99.38% | 不推荐 |
| **OpenCV DNN + 自拼 FaceNet/ONNX** | OpenCV 活跃 | Apache-2.0 | 自定 | 工程量大 | 仅作学习/极端定制 |
| **MediaPipe Face Mesh** | Google 活跃 | Apache-2.0 | 468 关键点 | 偏关键点；无识别嵌入 | 不适用（可作检测兜底） |

**判断依据**：
- 离线/隐私要求：InsightFace 允许自托管 ONNX 模型 + 本地缓存 (`~/.insightface/models/` 或 `INSIGHTFACE_HOME`)，首启后完全可控。
- 准确率：InsightFace 在 IJB-C / MegaFace 等公开榜单长期领先（多份复现与官方报告一致）。
- 跨平台：ONNX Runtime 提供 CPU/CUDA/DirectML/TensorRT/ROCm EP；Windows 无 NVIDIA 可走 DirectML，macOS/Apple Silicon 走 CPU EP。
- 可替换性：抽象 `FaceDetector` / `FaceEmbedder` 接口，未来切换到 w600k_r100、新 MobileFaceNet、AdaFace 等成本低。
- 风险与缓解：buffalo_l 模型许可非商用 → 文档/UI 中明示来源；若后续要商用，预留替换为自训/商权模型的路径。

来源：InsightFace python-package README、ONNX Runtime Execution Providers、Microsoft Learn Windows ML。完整 URL 见文末「参考资料」一节。

#### InsightFace 推荐调用形态

```python
from insightface.app import FaceAnalysis
app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
app.prepare(ctx_id=0, det_size=(640, 640))
faces = app.get(cv2_image)  # bbox, kps, normed_embedding (512d), det_score
```

- `normed_embedding` 已 L2 归一化，**直接用 cosine**。
- `det_size=(640,640)` 召回高；`(320,320)` 更快但漏小脸。
- 极小图/合影：`det_score` 阈值起步 0.5–0.6。

### 2.2 聚类（未知人数）

| 算法 | 复杂度 | 关键参数 | 优点 | 缺点 | 结论 |
|------|-------|---------|------|------|------|
| **HDBSCAN** | O(n log n) | `min_cluster_size`, `min_samples`, `cluster_selection_epsilon` | 无需指定 k；对噪声鲁棒；自动选阈值 | sklearn 实现较慢，需 `hdbscan` 原生包；初始距离矩阵大 | **推荐** |
| **Agglomerative（ChineseWhispers / 凝聚）** | O(n²) | 距离阈值 | 可解释；常用于人脸聚类 | OOM 风险大；阈值需手工调 | 备选（数据量 < 5k 适用） |
| **DBSCAN** | O(n log n) | `eps`, `min_samples` | 简单 | `eps` 难调；变密度下表现差 | 不推荐单独使用 |
| **谱聚类** | O(n³) | k | 几何直观 | 必须给 k；大 n 不可行 | 不推荐 |
| **k-NN 图 + 联通分量** | O(n log n) | k | 极快；适合大规模 | 需要良好向量 | 可作 HDBSCAN 的快速近似 |

**判断依据**：
- 1000–50000 张图规模下，HDBSCAN 在 CPU 上 1–3 分钟可完成。
- 距离度量建议使用余弦距离（在 InsightFace 嵌入上效果稳定）。

### 2.3 存储与缓存

| 候选 | 用途 | 选择 |
|------|------|------|
| SQLite | 索引库/元数据 | **推荐**（无服务、易分发、足够支撑百万级脸） |
| FAISS / Annoy / hnswlib | 近似最近邻加速 | **推荐** hnswlib（纯 C++ 绑定，轻量，跨平台） |
| LMDB / LevelDB | 大规模嵌入缓存 | 可选（>100 万脸时考虑） |
| 文件系统 + JSON | 轻量元数据 | 仅用于小规模或调试 |

### 2.4 图像解码

| 格式 | 推荐 | 备注 |
|------|------|------|
| JPEG/PNG/WebP | Pillow 或 OpenCV | Pillow 易用；OpenCV 解码更快 |
| HEIC | pillow-heif 或 imagecodecs | Windows/Linux 需装 libheif |
| TIFF | tifffile 或 Pillow | Pillow 对多页 TIFF 支持有限 |
| RAW (CR2/NEF/ARW) | rawpy | 体积大、依赖 libraw；v1 不强制 |
| GIF | Pillow（取首帧） | 动态人脸不在 v1 范围 |

### 2.5 软链接回退策略

> 单一权威在 [05-data-and-storage.md §4](05-data-and-storage.md)；本节给结论性引述。

| 平台 | 首选 | 回退顺序 |
|------|------|---------|
| Linux/macOS | `os.symlink` | 失败 → `shutil.copy2` |
| Windows 管理员/开发人员模式 | `os.symlink` | 文件 → `os.link`（硬链接）；目录 → `mklink /J`（junction）；最后 → `shutil.copy2` |
| Windows 普通用户 | `shutil.copy2` | 显式 warning 写入 `report.md` 顶部 |

- junction 仅在 symlink 失败后使用，因其「被复制/移动后会搬空原目标」的副作用对源图库有破坏性。
- 跨卷场景：硬链接不可用，直接 copy 并打 warning。
- 实现伪代码与 ONNX EP 选型表见 [05-data-and-storage.md §4](05-data-and-storage.md)。

## 3. 算法关键参数（v0.1 起步值）

- 检测：`det_thresh=0.5`，`det_size=(640,640)`（CPU 起步）；如速度敏感可降为 `(320,320)`。
- 嵌入：L2 归一化 512 维（InsightFace `normed_embedding`）。
- 度量：**cosine**（在归一化嵌入上等价于 Euclidean：`cos ≈ 1 - dist²/2`）。
- 聚类：HDBSCAN，`min_cluster_size=3`，`min_samples=2`（[01 AC-1](01-product-requirement.md) 锁定），`metric='cosine'`，`cluster_selection_method='leaf'`。
- 距离合并（同人判定）：
  - `cos ≥ 0.6` —— 强同人
  - `0.45 ≤ cos < 0.6` —— 宽松同人
  - `cos < 0.3` —— 不同人
- 二次合并：HDBSCAN 给出初始簇后，**两簇质心 cos ≥ 0.55** 强制合并（可配置）；这一步骤救回「同一人被切两簇」的常见问题。
- 孤儿：`cos < 0.4` 到簇质心的成员，标记为 `low_confidence`，进入 `output/_review/`。

> 这些值需要在 v0.1 阶段通过家庭相册 demo 数据集调优，记录在 [04-algorithm-pipeline.md](04-algorithm-pipeline.md)。

## 4. 关键风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| 跨年龄段、化妆、口罩导致漏识 | 高 | 保留人工校正；阈值可调；定期重建 |
| Windows 软链接权限 | 中 | 实现 junction/copy 双路径；README 文档化 |
| HEIC/RAW 依赖系统库 | 中 | 提供可选 extras（`pick-face[heic,raw]`） |
| 模型/数据出境合规 | 中 | 默认全本地；网络仅在显式 `--update-models` 时启用 |
| 单进程内存爆炸（n 很大） | 中 | 分批 embedding + Annoy 索引；流式聚类 |
| 同卵双胞胎 / 极相似误并 | 低 | 提供 `--high-precision` 模式（更高阈值 + 双趟合并） |

## 5. 最小可行性建议（MVP 切片）

1. CLI：`pick-face scan --src <dir> --src <dir> --out <dir> --model buffalo_l --workers 4`
2. 检测+嵌入：InsightFace `buffalo_l` + ONNX Runtime CPU EP（可加 `--provider auto` 自动探测）
3. 聚类：HDBSCAN + 簇质心二次合并（阈值 0.55）
4. 格式：JPG/PNG/HEIC/HEIF/WebP/GIF（首帧）/ RAW（先 EXIF thumbnail，失败再 rawpy）
5. 输出：软链接（symlink → hardlink → copy 三段回退，Windows 额外 junction）+ index.sqlite + report.md + clusters.html
6. 增量：幂等键 = `(abs_path, size, mtime_ns, sha1_8)`，命中即 skip
7. 校正：仅 CLI（merge/split/remove），v0.2 再做 TUI/Web
8. 模型下载：首次 `--init-models` 一次性拉取 buffalo_l（~300–600MB），之后全离线
9. README 顶部明记：许可（InsightFace 模型非商用研究）、首次需联网、Windows 软链接特权

详见 [06-engineering-plan.md](06-engineering-plan.md) 的 M1 任务分解与「依赖与 CI」章节（[06 §7](06-engineering-plan.md#7-依赖与-ci)）。

## 6. 验证指标（建议基线）

| 指标 | 目标 | 测量方式 |
|------|------|---------|
| 端到端单图平均耗时（CPU） | ≤ 1.5s（中端 x86），RAW 走 thumbnail 后 ≤ 0.3s | 加时间戳日志 |
| 增量重扫（无变更） | ≤ 5s / 万张 | 仅 DB 查询 |
| 簇纯净度（precision） | ≥ 95%（top-20 大簇人工抽检） | 100 张/簇 |
| 簇召回（recall@family） | ≥ 90% | 抽检家人 |
| 误合并率 | ≤ 1% | 抽检 |
| `_review/` 占比 | ≤ 5% 面孔 | DB 统计 |
| 软链接成功率 | Linux/macOS 100% symlink；Windows ≥ 95% symlink + ≤ 5% junction | 日志 |

## 7. 参考资料

- InsightFace python-package README — https://github.com/deepinsight/insightface/blob/master/python-package/README.md
- InsightFace 主仓 — https://github.com/deepinsight/insightface
- InsightFace-REST (SthPhoenix) — https://github.com/SthPhoenix/InsightFace-REST
- face_recognition (ageitgey) — https://github.com/ageitgey/face_recognition
- DeepFace (serengil) — https://github.com/serengil/deepface
- ONNX Runtime Execution Providers — https://onnxruntime.ai/docs/execution-providers/
- DirectML with ONNX Runtime — https://learn.microsoft.com/en-us/windows/ai/windows-ml/
- Windows Symbolic Links (Developer Mode) — https://learn.microsoft.com/en-us/windows/uwp/get-started/file-mgmt#symlinks
- Windows Hard Links and Junctions — https://learn.microsoft.com/en-us/windows/win32/fileio/hard-links-and-junctions
- Python `os.symlink` — https://docs.python.org/3/library/os.html#os.symlink
- pillow-heif PyPI — https://pypi.org/project/pillow-heif/
- rawpy PyPI — https://pypi.python.org/pypi/rawpy
- HDBSCAN vs DBSCAN (Towards Data Science 2024) — https://towardsdatascience.com/hdbscan-vs-dbscan-a-comparative-analysis-2ebbd45f9e1e
- Agglomerative + HDBSCAN for face clustering (arXiv 2403.12677) — https://arxiv.org/abs/2403.12677
- Chinese Whispers for face clustering — https://www.vision-rybnik.eu/publications/cw_face.pdf
- Review of clustering algorithms for face recognition (Springer 2020) — https://link.springer.com/article/10.1007/s10462-020-09943-9
- imagehash (perceptual hash) — https://pypi.org/project/Imagehash/
