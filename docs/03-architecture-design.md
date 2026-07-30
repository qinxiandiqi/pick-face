# 03 系统架构与模块设计

> 文档版本：v0.1（预研稿） · 2026-07-30

## 1. 设计原则

- **离线优先**：默认完全本地运行；任何网络行为必须显式 opt-in。
- **幂等可重入**：同一份输入多次运行结果一致；运行可中断/恢复。
- **关注点分离**：`scan → detect → embed → cluster → link` 五阶段解耦，每阶段可独立替换。
- **可观察**：每个阶段输出可校验中间产物；CLI 与 JSON 双格式进度。
- **少依赖**：核心运行只依赖 numpy/Pillow/SQLite；ONNX 推理与聚类作为可选 extras。

## 2. 系统架构总览

```
                 ┌──────────────────────────────────────────┐
                 │           pick-face CLI / API            │
                 └──────────────────────────────────────────┘
                                   │
                ┌──────────────────┼────────────────────┐
                ▼                  ▼                    ▼
         ┌────────────┐     ┌────────────┐        ┌────────────┐
         │   Scan     │ ──▶ │  Detect &  │ ──▶   │  Cluster   │
         │ (walk fs)  │     │   Embed    │        │ (HDBSCAN)  │
         └────────────┘     └────────────┘        └────────────┘
                │                  │                     │
                ▼                  ▼                     ▼
         ┌────────────────────────────────────────────────────┐
         │  Index Store  (SQLite + 文件 hash + Annoy/HNSW)    │
         └────────────────────────────────────────────────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │  Linker / Reporter  │
                        └─────────────────────┘
                                   ▲
                                   │
                         ┌─────────┴─────────┐
                         │  Review (人工校正) │
                         │  merge/split/rm   │
                         └───────────────────┘
```

> 校对通路：`review apply` → 写入 `review_decision` 表 → 下次 `cluster` 读出作为 must/cannot-link 强约束。

## 3. 模块划分

| 模块 | 路径（建议） | 职责 |
|------|-------------|------|
| `pick_face.config` | `src/pick_face/config.py` | 配置 schema 校验、CLI 解析 |
| `pick_face.scanner` | `src/pick_face/scanner.py` | 目录遍历、glob 过滤、content hash、增量 diff |
| `pick_face.images` | `src/pick_face/images.py` | 解码、EXIF 旋转、降采样 |
| `pick_face.detector` | `src/pick_face/detector.py` | 检测接口 `FaceDetector` |
| `pick_face.embedder` | `src/pick_face/embedder.py` | 嵌入接口 `FaceEmbedder` |
| `pick_face.align` | `src/pick_face/align.py` | 关键点对齐裁剪 |
| `pick_face.cluster` | `src/pick_face/cluster.py` | 聚类 + 约束注入 + 置信度 |
| `pick_face.index` | `src/pick_face/index.py` | SQLite schema、Annoy 索引 |
| `pick_face.linker` | `src/pick_face/linker.py` | 软链接/回退；输出目录原子写入 |
| `pick_face.reporter` | `src/pick_face/reporter.py` | `report.md/json/html` |
| `pick_face.review` | `src/pick_face/review.py` | 人工校正子命令 |
| `pick_face.runtime` | `src/pick_face/runtime.py` | 模型下载/缓存、device 选择 |
| `pick_face.errors` | `src/pick_face/errors.py` | 异常层级 + 退出码契约 |
| `pick_face.progress` | `src/pick_face/progress.py` | JSON 进度事件协议 |
| `pick_face.hashing` | `src/pick_face/hashing.py` | xxh3_64 + 文件 ID 拼接 |
| `pick_face.paths` | `src/pick_face/paths.py` | 跨平台缓存目录 |
| `pick_face.cli` | `src/pick_face/cli.py` | Typer/Click 命令入口 |

## 4. 工程结构树状图

### 4.1 仓库布局（src layout）

```
pick-face/
├── pyproject.toml              # 项目元数据 + 依赖 + extras（[heic]/[raw]/[gpu]/[dev]）
├── requirements.lock           # uv pip compile 锁定（提交到仓）
├── README.md                   # 5 分钟 quickstart
├── CHANGELOG.md                # Keep a Changelog 风格
├── LICENSE                     # Apache-2.0（与模型许可解耦）
├── .python-version             # 3.10/3.11/3.12
├── .pre-commit-config.yaml
├── ruff.toml                   # lint 配置
├── mypy.ini                    # 类型检查
├── mkdocs.yml                  # 文档站
├── docs/                       # 见 docs/AGENTS.md
│   ├── 01-product-requirement.md
│   ├── 02-technical-pre-research.md
│   ├── 03-architecture-design.md
│   ├── 04-algorithm-pipeline.md
│   ├── 05-data-and-storage.md
│   ├── 06-engineering-plan.md
│   ├── 07-risk-and-decisions.md
│   ├── 08-review-notes.md
│   ├── 09-face-recognition-pipeline.md
│   ├── 10-model-stack.md
│   ├── 11-commercial-compliance.md
│   └── AGENTS.md                # 文档总览 (入口)
├── migrations/                 # 不可变 SQL，按版本号升序
│   ├── 0001_init.sql
│   ├── 0002_add_review_decision.sql
│   └── ...
├── src/
│   └── pick_face/              # 主包
│       ├── __init__.py
│       ├── cli.py              # Typer 入口
│       ├── config.py           # pydantic schema + toml 加载
│       ├── scanner.py
│       ├── images.py           # 解码/EXIF/降采样
│       ├── detector.py         # FaceDetector Protocol + InsightFace 实现
│       ├── embedder.py         # FaceEmbedder Protocol
│       ├── align.py            # 关键点对齐
│       ├── cluster.py          # HDBSCAN + 约束
│       ├── index.py            # SQLite + HNSW
│       ├── linker.py           # 软链接三段回退
│       ├── reporter.py         # report.md / .json / .html
│       ├── review.py           # review 子命令
│       ├── runtime.py          # 模型下载/缓存/device 选择
│       ├── errors.py           # 异常层级 + 退出码
│       ├── progress.py         # JSON 事件协议
│       ├── hashing.py          # xxh3_64 + 文件 ID 拼接
│       ├── paths.py            # 跨平台缓存目录
│       └── py.typed
├── tests/
│   ├── unit/                   # 单测
│   ├── integration/            # 端到端（含 mock 推理）
│   ├── acceptance/             # AC-1~AC-9 评测脚本（含 11 §3.5 test_no_model_in_distribution.py）
│   │   └── run_eval.py
│   ├── fixtures/
│   │   ├── synth_faces/        # 合成人脸图
│   │   ├── mock_insightface.py # MockDetector / MockEmbedder
│   │   └── demo_dataset/       # 50 人 / 约 1000 张去标识化（git-lfs，详见 08 §6.3 AC-6）
│   └── conftest.py
├── bench/                      # 性能基准
│   ├── run.py
│   ├── dataset_synth/          # 10k 合成图
│   └── reports/
├── ci/
│   ├── lint.yml
│   ├── test.yml                # ubuntu/macos/windows × py 3.10/3.11/3.12
│   ├── smoke.yml               # 三平台 mock 端到端
│   └── eval.yml                # 公开基准（仅 ubuntu + GPU runner）
└── .github/
    ├── workflows/
    └── CODEOWNERS
```

### 4.2 运行期数据布局（用户机器上）

```
<output>/
├── .cache/
│   ├── index.sqlite            # 权威元数据
│   ├── index.sqlite-wal        # WAL 日志
│   ├── faces.hnsw              # ANN 缓存（可由 SQLite 重建）
│   ├── thumbs/<face_id>.jpg    # 报告用缩略图（GC 清理）
│   └── diagnostics-<ts>.zip    # 仅 --diagnostics 时产出
├── .staging-<run_id>/          # 半成品，原子切换前不可见
├── .prev-<run_id>/             # 上一版输出（最多保留 3 个，供 rollback）
├── .lock                       # flock 互斥（CLI 启动时持有）
├── index.json                  # SQLite 镜像，调试用
├── report.md
├── report.html
├── person-0001/
│   ├── meta.json
│   └── <src_rel_path> -> <abs_src>
├── person-0002/...
├── _review/                    # 宽松同人或低置信度（--emit-review 启用时）
└── _archive/                   # 被合并/废弃簇的旧链接
```

模型与全局缓存（跨 `<output>` 共享）：

```
# Linux
$XDG_CACHE_HOME/pick-face/models/        # 默认 ~/.cache/pick-face/models
# macOS
~/Library/Caches/pick-face/models/
# Windows
%LOCALAPPDATA%\pick-face\models\
# 任意平台可用 INSIGHTFACE_HOME 指向本地模型根目录
```

### 4.3 包内依赖方向

```
cli ──▶ config ──▶ scanner ──▶ images ──▶ detector ──▶ embedder
                                          │             │
                                          ▼             ▼
                                       align         cluster
                                          │             │
                                          └────┬────────┘
                                               ▼
                                             index  ◀── review
                                               │
                                               ▼
                                             linker ──▶ reporter
```

约束：
- `detector` / `embedder` / `cluster` 只依赖 `index`（写入 + 读 face）；不直接读源目录。
- `linker` 与 `reporter` 只读 `index`；不写 `face` 表。
- `review` 写 `review_decision` 表，由 `cluster` 在下次 run 消费。
- `cli` 是唯一允许 import `runtime`（模型下载）的入口，便于审计「网络 IO 调用点」。

## 5. 数据流（一次完整 run）

1. **Config 加载** —— 读 `pick-face.toml`、合并 CLI flag，校验源/输出目录。
2. **Scan** —— 遍历所有 `--src`，按后缀白名单与 exclude glob 过滤；计算 `xxh3` content hash；与 `index` 比对决定 ADD/MOD/UNCHANGED/DEL。
3. **Image Decode** —— 对 ADD/MOD 项做 EXIF 旋转 + 降采样到最大边 1600px（保留原图以备后续精细化）。
4. **Detect & Embed** —— 调 `Detector.detect()` 得到 bbox+landmarks；`Aligner` 裁剪；`Embedder.embed()` 得 512 维向量并 L2 归一化。
5. **Persist** —— 写入 `index.sqlite`：`source(id,path,hash,mtime)`、`face(id,source_id,bbox,landmarks,embedding,quality,cluster_id)`。
6. **Cluster** —— 取出全部 embedding（已存在 + 新增），用人工约束（merge/split）更新后跑 HDBSCAN；写回 `face.cluster_id`。
7. **Link** —— 根据 `face.cluster_id` 生成/更新 `output/<person-id>/<source-relative>` 软链接；多余链接进入待清理列表。
8. **GC** —— 删除指向已不存在的源的链接；记录被清理的路径到运行日志。
9. **Report** —— 写 `report.md`：`total_sources / total_faces / persons / noise_faces / confidence_histogram`。

## 6. 关键接口契约

```python
# detector.py
class FaceBox(NamedTuple):
    bbox: tuple[float, float, float, float]   # x1, y1, x2, y2
    score: float
    landmarks: tuple[tuple[float, float], ...]  # 5/68 points
    quality: float                              # 0..1

class FaceDetector(Protocol):
    def warmup(self) -> None: ...
    def detect(self, image: np.ndarray) -> list[FaceBox]: ...
    def detect_batch(self, images: list[np.ndarray]) -> list[list[FaceBox]]: ...
    @property
    def model_name(self) -> str: ...           # 'buffalo_l' 等
    @property
    def provider(self) -> str: ...             # 'cpu' / 'cuda' / 'directml'

# embedder.py
class FaceEmbedder(Protocol):
    def embed(self, chip: np.ndarray) -> np.ndarray: ...        # 1D, L2-normalized
    def embed_batch(self, chips: list[np.ndarray]) -> np.ndarray: ...  # (B, D)

# cluster.py
@dataclass
class Constraints:
    must_link: list[tuple[int, int]] = field(default_factory=list)   # (face_a, face_b)
    cannot_link: list[tuple[int, int]] = field(default_factory=list)
    excluded_faces: set[int] = field(default_factory=set)

@dataclass
class ClusterResult:
    labels: np.ndarray   # int32, -1 = noise
    probs: np.ndarray    # float32
    centroid: np.ndarray # (k, D)

class Clusterer(Protocol):
    def fit(self, embeddings: np.ndarray, constraints: Constraints) -> ClusterResult: ...
    def incremental_assign(self, new_emb: np.ndarray, existing: ClusterResult) -> tuple[np.ndarray, np.ndarray]: ...

# linker.py
class Linker(Protocol):
    def ensure(self, dst: Path, src: Path) -> LinkResult: ...
    def cleanup(self, dangling: Iterable[Path]) -> int: ...
```

**错误语义**：
- 检测/嵌入错误以 `FaceError`（含 `path`, `stage`, `cause`）抛回；不静默吞。
- 批处理接口对单张失败返回 `[]`/`None` 而不中断整批。
- 模型加载失败抛 `ModelLoadError`；CLI 捕获后提示 `--init-models` 与离线安装指引。

## 7. CLI 命令（v0.1）

```
pick-face init                # 生成默认 pick-face.toml
pick-face init-models         # 下载 InsightFace buffalo_l（需 --allow-network）
pick-face scan                # 扫描 + 写 source 表
pick-face index               # 检测+嵌入
pick-face cluster             # 聚类
pick-face link                # 生成/更新软链接
pick-face run                 # scan+index+cluster+link 一步执行
pick-face report              # 输出 report.md
pick-face review              # 启动交互式校正（TUI）
pick-face review apply FILE   # 应用预先编辑的 review.json
pick-face gc                  # 清理悬挂链接 + 过期缩略图
pick-face prune               # 清理 _archive（v0.2）
pick-face rollback --to ID    # 回滚到指定 run_id
pick-face rebuild             # 强制全量重建
```

## 8. 进程模型与并行

- **CPU 推理（默认）**：每 worker 独立加载 ONNX session；多 worker 多进程；GIL 不影响推理。
- **GPU 推理（`--provider cuda/directml`）**：单进程 + `ThreadPoolExecutor`；多 worker 会因 ONNX session 不共享反而拖累。
- **检测/嵌入 vs 聚类**：检测/嵌入是 CPU/GPU 重活；HDBSCAN 聚类是纯 Python/CPU 短任务，单进程跑。
- **流水线**：`asyncio.Queue` 串联 scan → decode → detect/embed → persist；CPU 后端用 `ProcessPoolExecutor`，GPU 后端用 `ThreadPoolExecutor`。
- **并行度建议**：
  - CPU：`--workers = min(os.cpu_count(), 4)`（每 worker 内存 ~500MB）。
  - GPU：`--workers = 1`（不并行），但 `--prefetch 4` 提高 GPU 利用率。
- **降级**：`--provider auto` 时尝试 `cuda` → `directml` → `cpu`；失败链路在 `report.md` 顶部 `Warnings` 列出。
- **ONNX EP 选择**：见 [02 §2.5 EP 选型表](02-technical-pre-research.md)（亦将在 [05 §4](05-data-and-storage.md) 重复一次以保证模块内自洽）。

## 9. 错误处理

- 单张图解码失败 → 记入 `error_log`，继续其它图。
- 模型加载失败 → 显式提示 `--init-models` 或离线安装路径。
- 链接权限失败 → 自动回退为 `copy` 并在 `report.md` 顶部 `Warnings` 节列出。
- 聚类无簇（全部噪声）→ 不创建任何 `person-*` 目录，但保留 `face` 表数据，可在 `review` 子命令中调阈值重试。
- 外部破坏链接（用户删除或修改）→ `link` 阶段在 `link.actual_target IS NULL OR != source.path` 时记入 `dangling_links`；`pick-face gc` 周期清理。
- **退出码契约**：
  - `0` 全流程成功（含可恢复 warning）
  - `2` 严重配置/参数错误（源/输出路径不可写、配置 schema 失败）
  - `3` 模型不可用（首次未联网且未 `--init-models`）
  - `4` 关键阶段（detect/embed/cluster）整体失败率 > 50%
  - `5` 中断（SIGINT/SIGTERM）后的「部分完成」状态，下次可恢复
- **JSON 进度事件协议**（`--progress json`）：
  ```json
  {"ts": 1722345678, "stage": "embed", "done": 1234, "total": 5000, "rate_fps": 4.1, "errors": 0}
  ```
  解析端按 `stage` 切分进度条；`errors` 字段与 `error_log` 计数一致。
- **临时文件**：`.cache/thumbs/` 仅在 `report` 生成时落地；运行结束 24h 后或下次 `gc` 时清理未被引用的缩略图。

## 10. 安全与隐私

- 不写注册表、不读全局配置；仅写 `<output>` 与 `<output>/.cache/`。
- 进程退出时清理临时缩略图。
- 模型与缓存目录遵循 `XDG_CACHE_HOME` / `~/Library/Caches/pick-face` / `%LOCALAPPDATA%\pick-face` 跨平台约定。
- 文档明示：所有处理在本地完成，开发者承诺不内置任何遥测。

## 11. 包管理设计

> 范围：开发期依赖、生产构建、模型/插件 extras、本地离线缓存、CI 与 PyPI 发布的统一管理。与 [06 §7 依赖与 CI](06-engineering-plan.md#7-依赖与-ci) 互补——本节给**原则 + 工作流**，06 给**具体版本下限**。

### 11.1 工具选型（**包管理器统一使用 `uv`**）

| 用途 | 工具 | 理由 |
|------|------|------|
| 依赖解析 / lockfile / venv / 安装 / 发布 | **`uv`**（**唯一主线**） | 单一工具覆盖 `pip` / `pip-tools` / `pipx` / `virtualenv` / `twine` 全部能力；lockfile 兼容 PEP 621；CI 与本地行为一致；减少「本地能跑 CI 失败」类问题 |
| 项目元数据 | `pyproject.toml`（PEP 621） | 标准、可被 `pip` / `uv` 共同识别 |
| 打包 | `hatchling`（`build-system`） | PEP 621 友好、wheel/sdist 干净；通过 `uv build` 调用 |
| 校验 | `uv pip check` + `uv run pip-audit` | CI 必跑；安全审计 |
| 环境隔离 | `uv venv` + `.venv/`（不提交） | 启动快、磁盘省 |

> **决策（已合并到本节）**：**包管理器统一使用 `uv`**——`uv pip compile` 生成 `requirements.lock`、`uv pip sync` 消费 lockfile、`uv venv` 隔离环境、`uv build` 打包、`uv publish` 发布。**不**再使用 `pip-tools` / `pip-compile` / `twine` / `pypa/build` / `pipx` 作为工具名出现在文档与 CI 中；如确需用纯 `pip` 回放，`uv` 生成的 lockfile 与 `pip install -r requirements.lock` 兼容，但推荐使用 `uv pip sync`。

### 11.2 依赖分组（extras 矩阵）

| extras | 关键依赖 | 何时安装 | 默认？ |
|--------|---------|---------|--------|
| `pick-face`（核心） | `numpy`, `Pillow`, `opencv-python`, `typer`, `rich`, `pydantic`, `xxhash`, `hnswlib`, `hdbscan`, `insightface`, `onnxruntime` | 始终 | ✅ |
| `[heic]` | `pillow-heif` | 用户声明 | ❌ |
| `[raw]` | `rawpy`（含 libraw 绑定） | 用户声明 | ❌ |
| `[gpu]` | `onnxruntime-gpu` | 用户声明（替换 `onnxruntime`） | ❌ |
| `[gpu-cuda12]` | `onnxruntime-gpu==1.17.*` + 文档 `cuda==12.x` 校验脚本 | Linux + NVIDIA | ❌ |
| `[gpu-directml]` | `onnxruntime-directml`（Windows） | Windows + 无 CUDA | ❌ |
| `[dev]` | `pytest`, `pytest-cov`, `pytest-benchmark`, `ruff`, `mypy`, `pre-commit`, `pip-audit` | 开发者 | ❌ |
| `[all]` | 上述全部 | 全量自检 | ❌ |

**互斥约束**：
- `[gpu]` 与 `[gpu-directml]` 互斥；CI 在同一环境只装其一，缺则降级。
- `[all]` 不强制安装 `[gpu]` 系列——GPU 仍需用户按硬件手动选。

**示例**（`pyproject.toml` 节选）：

```toml
[project]
name = "pick-face"
requires-python = ">=3.10,<3.13"
dynamic = ["version"]

[project.optional-dependencies]
heic        = ["pillow-heif>=0.16"]
raw         = ["rawpy>=0.18"]
gpu         = ["onnxruntime-gpu>=1.17"]
gpu-cuda12  = ["onnxruntime-gpu>=1.17,<1.18"]
gpu-directml= ["onnxruntime-directml>=1.17"]
dev         = ["pytest>=8", "pytest-cov>=5", "pytest-benchmark>=4",
               "ruff>=0.6", "mypy>=1.10", "pre-commit>=3.8",
               "pip-audit>=2.7", "types-Pillow"]

[project.scripts]
pick-face = "pick_face.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### 11.3 本地工作流

```
# 一次性
uv venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install -e ".[dev,heic]"

# 改依赖后
# 1) 改 pyproject.toml
# 2) 重新编译 lockfile
uv pip compile pyproject.toml -o requirements.lock
# 3) 同步到本地 venv
uv pip sync requirements.lock
# 4) 提交 pyproject.toml + requirements.lock
```

`pre-commit` hook：
- `uv-lock-check`：CI 与本地若 `requirements.lock` 与 `pyproject.toml` 不一致则失败。
- `pip-audit --strict`：本地每次提交扫描已知漏洞。

### 11.4 CI 消费

- **lint / unit / smoke**：使用 `requirements.lock`（`uv pip sync`）以保证可复现。
- **GPU job**（`ci/eval.yml`，仅 ubuntu + 自托管 GPU runner）：`uv pip install -e ".[all,gpu-cuda12]"`；不消费 lockfile，因为 CUDA/cuDNN 与 `onnxruntime-gpu` 版本需一一对应，**锁文件跨 GPU runner 难维护**。
- **缓存键**：`pyproject.toml` + `requirements.lock` 的 SHA256；失效即重建。
- **矩阵**：见 [06 §7.3](06-engineering-plan.md#7-依赖与-ci)。

### 11.5 模型与本地离线镜像

模型**不通过包管理器分发**，避免「几百 MB 模型拖慢 `uv pip install`」。`pick-face init-models` 走 [10 §7 模型下载与离线部署](10-model-stack.md) 与 [11 §3.2 启动时强校验](11-commercial-compliance.md)，但允许管理员预置本地镜像：

| 形态 | 配置 | 用途 |
|------|------|------|
| 单一环境变量 | `INSIGHTFACE_HOME=/path/to/models` | 指向已下载的模型根目录 |
| 配置项 | `[runtime] model_dir = "/srv/models"` | 项目级覆盖环境变量 |
| HTTP 镜像 | `[runtime] model_index_url = "https://internal.corp/models/"` | 内网部署；需 `--allow-network` |
| 完全离线 | 不配置 + `uv pip install` 走内网 PyPI 镜像 | 全部资源本地化 |

CI 中通过 `actions/cache` 缓存 `~/.insightface/models/`，避免每次 job 重新下载。

### 11.6 发布

- **版本号**：SemVer；`0.y.z` 阶段允许小重构；进入 `1.x` 后仅修 bug 与新特性。
- **tag 触发**：`git tag v0.1.0` → GitHub Actions `release.yml` → `uv build` → `uv publish`（OIDC trusted publishing，不存凭据）。
- **产物**：`pick-face-0.1.0-py3-none-any.whl` + `pick-face-0.1.0.tar.gz` + `SHA256SUMS`。
- **签名**：可选 `sigstore` cosign 签名 wheel。
- **预发布**：`v0.1.0rc1` 走 TestPyPI；正式版推 PyPI。
- **变更日志**：`CHANGELOG.md` 由 `git-cliff` 或 `towncrier` 自动生成。

### 11.7 不可变约束

- **不引入**任何运行时依赖与 InsightFace / ONNX 无关的「重量级」库（PyTorch、TensorFlow）。
- **不**在核心 `requires-python` 中放 `numpy<2` 之类的硬约束；版本兼容性在 `requirements.lock` 中固定。
- **不**用 `setup.py`；新代码只在 `pyproject.toml` 声明。
- **不**默认安装 `[gpu]`；用户按硬件显式选择，避免 CPU 机器下载 CUDA 库失败。
- **包管理器统一使用 `uv`**——文档、CI、发布、pre-commit 钩子中**只**出现 `uv` 子命令（`uv venv` / `uv pip compile` / `uv pip sync` / `uv pip install` / `uv run` / `uv build` / `uv publish` / `uv pip check`），不再使用 `pip-tools` / `pip-compile` / `twine` / `pypa/build` / `pipx` 等工具名。`uv` 生成的 `requirements.lock` 与 `pip install -r` 兼容，作为回退通道。
