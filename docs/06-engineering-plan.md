# 06 工程规划与里程碑

> 文档版本：v0.1（预研稿） · 2026-07-30

## 1. 阶段划分

| 阶段 | 目标 | 周期（建议） | 出口标准 |
|------|------|-------------|---------|
| **M0 预研** | 完成技术选型与文档 | 已基本完成 | docs/ 全部文档就位并评审通过 |
| **M1 原型 v0.1** | 单线程 CLI、JPEG/PNG、WebP；CPU；软链接 | 2 周 | 200 张样本验收 ≥ 80% 一致 |
| **M2 增量 + 校正** | 增量、review 子命令、HEIC 基础支持 | 1.5 周 | AC-3 / AC-5 通过 |
| **M3 GPU + 性能** | GPU 加速、并行、长任务进度 | 1.5 周 | 1 万张 ≤ 1h（GPU） |
| **M4 1.0** | 报告完善、文档、跨平台 CI、pip 打包 | 1 周 | 三个平台 smoke test 全过 |

> 合计 6 周；可视团队规模与人力增减。

## 2. 任务分解（节选）

### M1 原型
- [ ] T-001 仓库脚手架（`pyproject.toml`、lint、test、pre-commit、`uv` 锁定与 `uv venv` 环境）
- [ ] T-002 CLI 骨架（Typer）+ 14 个子命令：`init / init-models / scan / index / cluster / link / run / report / review / review apply / gc / prune / rollback / rebuild`（与 03 §7 / 08 §6.5 一致）
- [ ] T-003 配置加载（toml，含 schema 校验 pydantic）+ 错误码；**含 `[runtime] accept_noncommercial_model_license: bool = False` 字段（fail-safe 默认；详见 11 §3.2）**
- [ ] T-004 扫描器 + content hash（xxh3_64）+ 增量 diff + JSON 进度事件
- [ ] T-005 InsightFace 集成（detector + embedder + aligner + warmup）
- [ ] T-006 SQLite schema v0 + PRAGMA + 迁移框架 + WAL
- [ ] T-007 HDBSCAN 聚类 + 簇质心二次合并 + 人工约束
- [ ] T-008 软链接 / 回退（含 Windows junction 兜底）
- [ ] T-009 report.md / report.html 生成（含 Warnings / 置信度直方图 / **顶部 Model+License 字段 (11 §3.4)**）
- [ ] T-010 demo 数据集 + 验收脚本 + eval_report.json
- [ ] T-011 退出码契约 + SIGINT/SIGTERM 处理 + staging 原子切换
- [ ] T-012 pyproject extras 切分：`[heic]`、`[raw]`、`[gpu]`、`[gpu-cuda12]`、`[gpu-directml]`、`[dev]`、`[all]`（包管理统一 `uv`，详见 [03 §11](03-architecture-design.md#11-包管理设计)）

### M2 增量与校正
- [ ] T-101 增量模式（add/mod/del）+ 增量分配 (`Clusterer.incremental_assign`)
- [ ] T-102 HEIC 解码（pillow-heif）
- [ ] T-103 RAW thumbnail 优先 + rawpy 兜底
- [ ] T-104 review 子命令（merge / split / remove / rename）+ `review_decision` 表
- [ ] T-105 `low_confidence_faces.json` 输出
- [ ] T-106 dry-run / rebuild / rollback 模式
- [ ] T-107 Windows 链接回退与 warning 文档化
- [ ] T-108 `meta.json` 与 `index.json` 镜像生成

### M3 GPU 与性能
- [ ] T-201 onnxruntime-gpu / DirectML / TensorRT 适配
- [ ] T-202 进程级并行 + 进度条（`--progress json` + TUI 进度）
- [ ] T-203 hnswlib 切换与持久化 + 崩溃重建路径
- [ ] T-204 长任务断点续跑（基于 `face.id` 检查点）
- [ ] T-205 10k 张基准 + 性能报告（CPU/GPU 各一份）

### M4 1.0
- [ ] T-301 报告 HTML 化（含暗色模式、人物缩略图墙）
- [ ] T-302 CI：lint + 单测 + 三平台 smoke + 公开基准评估 + **`tests/acceptance/test_no_model_in_distribution.py` (AC-9 守卫, 11 §3.5)**
- [ ] T-303 文档站（mkdocs）+ README 重写 + 故障排查
- [ ] T-304 PyPI 打包（`pyproject.toml` + `MANIFEST.in` + `uv build` + sdist/wheel 多平台 + `uv publish`）
- [ ] T-305 发布 1.0 + 兼容性承诺

## 3. 测试策略

| 层级 | 内容 | 工具 |
|------|------|------|
| 单元 | 配置、扫描器、链接器、SQLite schema 迁移、约束注入、xxh3 哈希、staging rename | `pytest` |
| 集成 | detect/embed/cluster/link 端到端，使用 50–200 张合成数据 + mock 推理后端（`MockDetector`） | `pytest` + 内存 ONNX |
| 验收 | 50 人 / 约 1000 张家庭相册 demo 数据集（与 [01 AC-1](01-product-requirement.md) 同源），跑出 `report.md` 与 `eval_report.json` | `tests/acceptance/run_eval.py` |
| 平台 | GitHub Actions matrix：ubuntu-latest / macos-latest / windows-latest | `ci.yml` |
| 性能 | benchmark 脚本，附 10k 张基准图（合成） + CPU/GPU 两份报告 | `bench/run.py` |

测试覆盖率门槛：核心模块 ≥ 80%，CLI ≥ 50%（GUI/TUI 之后再说）。

### 3.1 关键 fixture

- `tests/fixtures/synth_faces/`: 用合成人脸图（小图 + 噪声）跑扫描/聚类，单测无需真模型。
- `tests/fixtures/mock_insightface.py`: 实现 `FaceDetector`/`FaceEmbedder` Protocol，生成确定性的伪 embedding（基于图像内容的 hash），用于 CI smoke。
- `tests/fixtures/demo_dataset/`: 50 人 / 约 1000 张去标识化真实图（每人在 5–30 张之间随机），仅本地缓存（git-lfs 或下载脚本），用于 AC-1 验证。

### 3.2 CI 缓存

- 缓存 `~/.insightface/models/` 与 `~/.cache/uv`（如用 uv）。
- 公开基准数据集走 `actions/cache` + `pytest-benchmark` 增量比对。

## 4. 文档矩阵

- README：5 分钟 quickstart
- docs/01–07：本文档体系
- models.md：模型下载与离线安装指引
- troubleshooting.md：Windows 软链接、HEIC 缺失等常见问题

## 5. 发布策略

- 语义化版本：`0.y.z` 阶段允许小重构；进入 `1.x` 后仅修 bug 与新特性。
- 变更日志：`CHANGELOG.md`（Keep a Changelog 风格）。
- 兼容性：CLI 命令、SQLite schema、输出目录布局在 `1.x` 内保持稳定。

## 6. 团队分工（建议）

| 角色 | 占比 | 职责 |
|------|------|------|
| 算法 | 30% | 模型集成、聚类调参、评测 |
| 后端 | 40% | 流水线、CLI、SQLite、链接 |
| 平台/工具 | 20% | 跨平台 CI、打包、文档 |
| 产品/测试 | 10% | 验收数据集、文档评审 |

## 7. 依赖与 CI

### 7.1 Python 与包管理

- Python：3.10 / 3.11 / 3.12（CI 矩阵覆盖）。
- 包管理：**统一使用 `uv`**（依赖解析 / lockfile / venv / 安装 / 发布），详见 [03 §11](03-architecture-design.md#11-包管理设计)。
- 锁定：所有依赖在 `pyproject.toml` 中给约束区间；**生产构建**额外维护 `requirements.lock`（`uv pip compile` 生成，提交到仓），CI 与发布统一用 lockfile。
- 关键三方库（写明大致版本下限，到 v0.1 时按 ABI/CUDA 兼容性细化）：
  - `insightface>=0.7.3`（含 buffalo_l/sc）
  - `onnxruntime>=1.17`（CPU）/ `onnxruntime-gpu>=1.17`（CUDA，可选）
  - `opencv-python>=4.9`（图像解码）
  - `Pillow>=10.0`（EXIF/转码）
  - `pillow-heif>=0.16`（可选，extras `heic`）
  - `rawpy>=0.18`（可选，extras `raw`）
  - `numpy>=1.26`、`scipy>=1.11`
  - `hnswlib>=0.7`（ANN 索引）
  - `hdbscan>=0.8.33`（聚类）
  - `typer>=0.12`、`rich>=13`（CLI）
  - `pydantic>=2.6`（配置 schema 校验）
  - `xxhash>=3.4`（content hash）
  - `pytest>=8`、`pytest-benchmark`、`pytest-cov`（测试）

### 7.2 extras 切分（与 [03 §11.2](03-architecture-design.md#11-包管理设计) 一致）

- `pick-face[heic]`：HEIC 解码（`pillow-heif`）。
- `pick-face[raw]`：RAW 解码（`rawpy`）。
- `pick-face[gpu]`：`onnxruntime-gpu`。
- `pick-face[gpu-cuda12]`：`onnxruntime-gpu>=1.17,<1.18` + 文档 `cuda==12.x` 校验。
- `pick-face[gpu-directml]`：`onnxruntime-directml`（Windows 无 NVIDIA）。
- `pick-face[dev]`：lint / test / pre-commit。
- `pick-face[all]`：除 `[gpu*]` 系列外的所有可选（GPU 仍按硬件手动选）。

### 7.3 CI（GitHub Actions）

- 矩阵：`ubuntu-latest` × `python {3.10, 3.11, 3.12}`；`macos-latest` × `python 3.12`；`windows-latest` × `python 3.12`。
- Job：`lint`（ruff/black/mypy）、`unit`（pytest + 覆盖率）、`smoke`（mock 后端跑通），`eval`（仅 ubuntu + GPU runner 可选跑 LFW/CALFW/CPLFW 公开基准）。
- 缓存：`~/.insightface/models/`、`~/.cache/uv`。
- 发布：`uv build` + `uv publish`；tag 触发；签名 + 校验和（详见 [03 §11.6](03-architecture-design.md#11-包管理设计)）。

### 7.4 模型与离线

- `pick-face init-models`（默认走 InsightFace 模型下载器，可指向自托管 HTTP）需显式 `--allow-network`。
- 离线安装文档：在 `docs/troubleshooting.md` 给出「下载 `.zip` → 解压到 `INSIGHTFACE_HOME`」步骤。
