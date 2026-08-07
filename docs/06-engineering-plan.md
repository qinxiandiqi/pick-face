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
| **M5 路线 B** | Model Pack 插件架构 + 默认 `yunet-mfn` | 2 周 | Pi 3B 跑通 + AC-1 不降 + 商业零摩擦默认 |

> 合计 6 周；可视团队规模与人力增减。

## 2. 任务分解（节选）

### M1 原型
- [ ] T-001 仓库脚手架（`pyproject.toml`、lint、test、pre-commit、`uv` 锁定与 `uv venv` 环境）
- [ ] T-002 CLI 骨架（Typer）+ 14 个子命令：`init / init-models / scan / index / cluster / link / run / report / review / review apply / gc / prune / rollback / rebuild`（与 03 §7 / 08 §6.5 一致）
- [ ] T-003 配置加载（toml，含 schema 校验 pydantic）+ 错误码；**含 `[runtime] accept_noncommercial_model_license: bool = False` 字段（fail-safe 默认；详见 11 §3.2）**
- [ ] T-004 扫描器 + content hash（xxh3_64）+ 增量 diff + JSON 进度事件
- [ ] T-005 Model Pack 抽象：Detector/Embedder Protocol（v0.1 落 InsightFace 实现，路线 B 后抽象为 `pick_face.platform.pack`）
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

### M5 路线 B：Model Pack 插件架构（详见 docs/14 + docs/13）

- [ ] T-501 ModelPack Protocol + `discover_packs()` entry-points loader
- [ ] T-502 脱钩 core：`insightface` / `onnxruntime` 移出默认依赖
- [ ] T-503 `yunet-mfn` pack 落地（默认 Apache-2.0，5 MB 模型）
- [ ] T-504 `pick-face-modelpack-insightface` 独立包（保留 buffalo_l/sc/antelopev2 走 NC-research 路径）
- [ ] T-505 LicenseClass 驱动 AC-9 gate 改造
- [ ] T-506 Pi 3B 实测通过（400 张 PGM < 60 min，AC-1 ≥ 0.85）
- [ ] T-507 文档更新（[10](10-model-stack.md) / [11](11-commercial-compliance.md) / [13 新](13-raspberry-pi-support.md) / [14 新](14-model-pack-plugins.md) / AGENTS / README）
- [ ] T-508 CI 新增 `test_arm_friendly_default.py`（守默认 pack 回归）
- [ ] T-509 `pick-face doctor` 子命令：列出已注册 pack + license + 状态
- [ ] T-510 v2.0.0 发布：CHANGELOG 写迁移说明，老用户 `pip install pick-face-modelpack-insightface` 保留原行为

## 3. 测试策略

| 层级 | 内容 | 工具 |
|------|------|------|
| 单元 | 配置、扫描器、链接器、SQLite schema 迁移、约束注入、xxh3 哈希、staging rename | `pytest` |
| 集成 | detect/embed/cluster/link 端到端，使用 50–200 张合成数据 + mock 推理后端（`MockDetector`） | `pytest` + 内存 ONNX |
| 验收 | 真实人脸 fixture（见 §3.3）跑出 `report.md` 与 `eval_report.json`；AC-1 软阈值由 `tests/integration/test_real_faces_ac1.py` 守护 | `tests/acceptance/run_eval.py` |
| 平台 | GitHub Actions matrix：ubuntu-latest / macos-latest / windows-latest | `ci.yml` |
| 性能 | benchmark 脚本，附 10k 张基准图（合成） + CPU/GPU 两份报告 | `bench/run.py` |

测试覆盖率门槛：核心模块 ≥ 80%，CLI ≥ 50%（GUI/TUI 之后再说）。

### 3.1 关键 fixture

- `tests/fixtures/synth_faces/`: 用合成人脸图（小图 + 噪声）跑扫描/聚类，单测无需真模型。
- `tests/fixtures/mock_insightface.py`: 实现 `FaceDetector`/`FaceEmbedder` Protocol，生成确定性的伪 embedding（基于图像内容的 hash），用于 CI smoke。
- `tests/fixtures/real_faces/`: 真实人脸测试集（见 §3.3），**不进 git**，由 `scripts/fetch_face_dataset.py` 按需拉取。
- `tests/fixtures/mock_pack/`: 实现一个 mock `ModelPack`（LicenseClass.PERMISSIVE），用于测试 `discover_packs()` / `require_compliance()` 逻辑（[14 §3](14-model-pack-plugins.md)），不依赖任何真模型。

### 3.2 CI 缓存

- 缓存 `~/.insightface/models/` 与 `~/.cache/uv`（如用 uv）。
- 公开基准数据集走 `actions/cache` + `pytest-benchmark` 增量比对。

### 3.3 真实人脸测试集（T-307）

为 AC-1 验收准备一个**真实人脸** fixture；不放进 git，按需拉取。

```
# 一次性准备（要求可访问 cl.cam.ac.uk 或 figshare）
uv run python scripts/fetch_face_dataset.py

# 跑真实端到端
uv run pytest tests/integration/ -v -m real_data

# 默认 fixture：40 人 × 10 张 = 400 张 PGM（92×112 灰度） / ~4.5MB compressed
# 来源 1：https://www.cl.cam.ac.uk/research/dtg/attarchive/pub/data/att_faces.tar.Z
# 来源 2：https://ndownloader.figshare.com/files/5976027  (sklearn 用的镜像)
# License：CC-BY 4.0（仅需 attribution，无 source-disclosure 义务）
# Attribution：AT&T Laboratories Cambridge (formerly Olivetti Research Laboratory)
```

数据集选型理由（在所有备选中唯一同时满足六项约束的）：

| 备选 | License | 体量 | 裁剪度 | 人数 | 抓取 | 类内差异 |
|------|---------|------|--------|------|------|----------|
| **AT&T/ORL/Olivetti** | CC-BY 4.0 ✓ | 4.5MB ✓ | 已裁 ✓ | 40 ✓ | 2 个镜像 ✓ | 表情/眼镜/姿态 ✓ |
| 5-Celebrity-Faces | 不清 ✗ | 5MB | 已裁 | 5 | HF | 弱 |
| LFW | CC-BY 4.0（但 700MB）| 过大 | 仅人脸框 | 5k+ | 多源 | 一般 |
| Yale Face | 学术使用声明 | 1MB | 已裁 | 15 | 单源 | 一般 |
| Caltech Faces 1999 | 不允许再分发 | 1MB | 已裁 | 27 | 无公开链接 | 一般 |

约束：

- 图集**不**进 git、`pyproject.toml` 也不打包；CI 默认跳过（`pytest -m "not real_data"`）。
- 集成测试加 `@pytest.mark.real_data`，由 `tests/integration/conftest.py` 在 `manifest.json` 缺失时自动 `pytest.skip()`。
- AC-1 阈值先按 **软阈值**（precision ≥ 0.80 / recall ≥ 0.60 / B³ F1 ≥ 0.70）落地，避免小 fixture 抖动触发 CI 红；换上更大图集后再向合同阈值（0.95 / 0.85 / 0.90）收紧。
- fixture 目录内自带 `NOTICE` 文件（CC-BY 4.0 attribution），与 pick-face 的 Apache-2.0 NOTICE 兼容（Apache §4(d) 显式保留 NOTICE 文本）。

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
  - **核心**：`numpy>=1.24`、`Pillow>=10.0`、`opencv-python>=4.9`、`typer>=0.12`、`rich>=13`、`pydantic>=2.6`、`xxhash>=3.4`、`hnswlib>=0.7`、`hdbscan>=0.8.33`、`onnxruntime>=1.17`（路线 B 后**只**装 onnxruntime，不强依赖 insightface）
  - **Model Pack**（每个 pack 自带依赖，不进核心）：`yunet-mfn` → `onnxruntime + opencv-python`；`pick-face-modelpack-insightface` → `insightface + onnxruntime-gpu (可选)`
  - **可选 extras**：`pillow-heif>=0.16`（heic）、`rawpy>=0.18`（raw）、`onnxruntime-gpu>=1.17`（gpu）、`onnxruntime-directml>=1.17`（gpu-directml）
  - **dev**：`pytest>=8`、`pytest-cov`、`pytest-benchmark`、`ruff>=0.6`、`mypy>=1.10`、`pre-commit>=3.8`、`pip-audit>=2.7`、`types-Pillow`

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

- `pick-face init-models` 路线 B 后**必须指定 `--pack <pack_id>`**；走 pack 的 `download_to()` 拉权重
- 默认 `pack = yunet-mfn` → 走 OpenCV Zoo GitHub release，5 MB
- opt-in 装 `pick-face-modelpack-insightface` 后可用 `buffalo_l` / `buffalo_sc` / `antelopev2`
- 完全离线：在 `model_dir/<pack_id>/` 预放 ONNX 文件，CLI 跳过下载
- 离线安装文档：在 `docs/troubleshooting.md` 给出「下载 `.zip` → 解压到 `model_dir/<pack_id>/`」步骤
- 详见 [10 §7](10-model-stack.md) + [13 §3 Pi 完整安装](13-raspberry-pi-support.md) + [14 §4 发布](14-model-pack-plugins.md)
