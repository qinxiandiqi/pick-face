# 07 风险登记与技术决策记录（ADR）

> 文档版本：v0.1（预研稿） · 2026-07-30

## 1. 风险登记

| ID | 风险 | 等级 | 触发条件 | 缓解 | 负责人 | 状态 |
|----|------|------|----------|------|--------|------|
| R-01 | 跨年龄/化妆/口罩导致漏识 | 高 | v0.1 验收 < 80% 一致 | 保留人工校正；提供 `merge/split`；持续调参 | 算法 | 监控 |
| R-02 | Windows 软链接权限 | 中 | 普通用户运行 | 自动回退 copy + warning；README 文档化 | 后端 | 已设计 |
| R-03 | HEIC/RAW 系统依赖 | 中 | Linux/Windows 用户 | extras 安装；CI 跨平台矩阵 | 平台 | 已设计 |
| R-04 | 内存爆炸（>10 万脸） | 中 | 大型家庭相册 | HNSW + 分批聚类；流式写入 | 后端 | 已设计 |
| R-05 | 模型/数据出境合规 | 中 | 用户网络受限 | 默认离线；显式 opt-in 下载 | 产品 | 已设计 |
| R-06 | 同卵双胞胎误并 | 低 | 真实用户反馈 | 提高阈值 + `review` 拆分 | 算法 | 监控 |
| R-07 | ONNX 与 InsightFace 版本不匹配 | 中 | 升级依赖 | 锁定版本；CI smoke 跑过 | 后端 | 已设计 |
| R-08 | 输出目录被外部破坏 | 低 | 用户手动编辑 | 每次 run 启动时自检 + 自愈 | 后端 | 已设计 |

## 2. 技术决策记录（ADR）

> 格式：Context / Decision / Consequences。每条 ADR 一旦写入不再修改，仅追加新的覆盖。

### ADR-001 选用 InsightFace (buffalo_l/sc) 作为默认识别模型
- **Context**：需要高准确率且纯本地的人脸检测+嵌入。
- **Decision**：默认 InsightFace `buffalo_l`（高精度），`buffalo_sc` 作为 `--fast` 选项。
- **Consequences**：
  - 优：SOTA 准确率；ONNX 自托管可控；社区活跃。
  - 劣：模型 100MB+；CPU 推理较慢。
  - 后续：可替换为更新模型（`MobileFaceNet` 备选）。

### ADR-002 聚类算法默认 HDBSCAN
- **Context**：n 大、未知人数、噪声不可避免。
- **Decision**：HDBSCAN + cosine + 人工约束；先用 HNSW 构图避免 n² 内存。
- **Consequences**：
  - 优：自动选阈值；对密度变化鲁棒。
  - 劣：参数仍需调；与距离度量耦合。

### ADR-003 输出以软链接为主、拷贝为回退
- **Context**：用户期望「源不动 + 整理结果可独立访问」。
- **Decision**：默认 `os.symlink`；Windows 普通用户回退 `copy2`；失败时显式 warning。
- **Consequences**：
  - 优：不修改源；跨平台行为可解释。
  - 劣：Windows 用户在非管理员下体验降级。

### ADR-004 元数据以 SQLite 为主、JSON 镜像
- **Context**：检索 / 增量 / 关系查询；需要可读可移植。
- **Decision**：SQLite 作为权威；`index.json` 镜像关键关系便于调试；不在 JSON 中存 embedding。
- **Consequences**：
  - 优：可移植、可单文件备份；性能优于纯文件。
  - 劣：JSON 大集合时反向序列化慢；只放必要字段。

### ADR-005 默认完全离线、显式 opt-in 网络
- **Context**：隐私承诺与最小可用。
- **Decision**：除非 `--allow-network`，禁止任何网络 IO（模型下载/遥测全部禁）。
- **Consequences**：
  - 优：与产品目标 G2 一致；合规简单。
  - 劣：首次使用需手动下载模型或在文档指引下启用一次。

### ADR-006 进程内 ONNX session、IO 与推理流水线化
- **Context**：单进程内存控制与吞吐。
- **Decision**：
  - CPU 推理：`ProcessPoolExecutor`，每 worker 独立 ONNX session；`--workers = min(os.cpu_count(), 4)`。
  - GPU 推理：单进程 + `ThreadPoolExecutor`，`--workers = 1`，通过 `--prefetch` 提吞吐。
  - `asyncio.Queue` 串联 scan → decode → detect/embed → persist。
  - HDBSCAN 聚类单进程跑；不与推理并行（避免内存峰值叠加）。
- **Consequences**：
  - 优：CPU/GPU 行为可预测；内存可控。
  - 劣：多 GPU 调度需 v0.2+ 完善；CPU 多 worker 内存线性增长。

### ADR-008 输出目录原子切换（staging → rename）
- **Context**：保证运行中断或失败时旧结果可恢复。
- **Decision**：所有 `pick-face run` 默认 `--atomic`：在 `<out>/.staging-<run_id>/` 完整构造结果，成功后 `rename` 替换 `<out>`，旧目录改名 `<out>/.prev-<run_id>`。
- **Consequences**：
  - 优：失败可回滚；用户永远不会看到「半成品」结果。
  - 劣：磁盘占用翻倍（保留 `.prev-`）；大输出目录 rename 在 Windows 上较慢。

### ADR-009 元数据唯一权威 = SQLite；HNSW/JSON 都是缓存
- **Context**：崩溃恢复、跨机器迁移、版本升级的可靠性。
- **Decision**：
  - `index.sqlite` 是 source/face/cluster/link 的唯一权威。
  - HNSW 由 `pick-face index --rebuild-hnsw` 从 SQLite 重建。
  - `index.json` 仅用于调试/grep，不参与运行逻辑。
  - schema 升级走 `schema_migrations` 表 + 不可变 SQL 脚本。
- **Consequences**：
  - 优：崩溃可恢复；跨机器迁移可靠；可回放。
  - 劣：HNSW 偶尔需要 rebuild（开销大但 O(n) 可接受）。

### ADR-007 不内置任何遥测；诊断信息仅本地落盘
- **Context**：用户对本地工具的隐私预期；崩溃信息收集需明确边界。
- **Decision**：
  - 不引入任何 SDK / 统计 / 分析。
  - 默认运行不写任何超出 `<output>` 与 `<output>/.cache/` 的文件。
  - 仅当用户显式 `--diagnostics` 时，写入 `<output>/.cache/diagnostics-<ts>.zip`，内容包括：CLI 参数（去敏感）、`run` 表、`error_log`、模型版本；**不包含**原图、embedding、文件内容。
- **Consequences**：
  - 优：零隐私争议；行为可审计。
  - 劣：bug 反馈需用户主动附 diagnostics。
