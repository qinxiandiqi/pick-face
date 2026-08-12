# 08 评审记录与可实施性差距清单

> 文档版本：v0.1（评审稿） · 2026-07-30 · 状态：**评审中**

本文件记录对 [docs/01-07](AGENTS.md) 进行的可实施性评审结论、问题分级与处置状态。每条问题有唯一编号（`ISSUE-###`）并指向处理它的文档与章节。

## 1. 评审结论摘要

- **总体**：方案选型合理（InsightFace + ONNX + HDBSCAN + SQLite + 软链接），覆盖了从需求到发布的关键路径。
- **主要差距**：缺少依赖锁定、schema 迁移策略、错误路径与可恢复模型、CI 矩阵细节、增量聚类实现细节、配置 schema 与示例、运行监控/日志/回滚、安全与合规。
- **次要差距**：部分数字指标未给出置信区间或测试方法；少数术语在文档间不一致（如 `_review/` vs `_unassigned/`）。
- **建议处置**：把 01–07 中相关章节就地修订；不可在预研稿中落地的细节显式列为「v0.1 待补」并指定负责人。

## 2. 问题清单（按优先级）

### 2.1 高优先级（阻碍实施）

| ID | 文档/位置 | 问题 | 处置 |
|----|----------|------|------|
| ISSUE-001 | 03 §7 进程模型 | `asyncio.Queue` 与 `ThreadPoolExecutor` 在 CPU 推理上 GIL 释放有限，**纯 Python 流水线吞吐受限**；且多 worker 多进程时 InsightFace session 不可共享，需写明每 worker 独立加载 + 内存倍增 | 在 03 §7 增加「CPU 推理多进程 / GPU 推理单进程」的明确分支与 `--workers` 行为表；加 ADR-008 |
| ISSUE-002 | 05 §2 SQLite | 缺 `PRAGMA`、WAL 模式、迁移机制、初始版本号；无法保证「多版本兼容 + 升级不破坏索引」 | 增补 PRAGMA 段、`schema_migrations` 表与 v0.1 升级路径示例 |
| ISSUE-003 | 05 §6 一致性 | 缺「原子切换输出目录」的具体实现；提到 atomic rename 但未写 staging dir、`.tmp` 切换与回滚 | 补「staging → atomic rename」伪代码与失败回滚路径 |
| ISSUE-004 | 06 §2 任务 | 缺 CI 矩阵、可复现环境（`uv` 锁定）、`requirements.lock`、`pyproject` extras 切分（`[heic]`/`[raw]`） | 06 §2 增加 T-007/T-008 子项；新增 06 §7 依赖与 CI 章节 |
| ISSUE-005 | 04 §2.4 聚类 | 「簇质心二次合并」没有写明何时触发（每次 run? 新人入簇后增量?），也没说合并后簇 ID 是否会变 | 增补「触发时机、ID 稳定性、合并后置信度重算」步骤 |
| ISSUE-006 | 03 §5 接口 | `FaceDetector`/`FaceEmbedder` Protocol 缺乏运行时选择、错误码、降级路径；批处理接口未定义 | 增补 `predict_batch`、错误语义、降级（ONNX 失败 → 退回 `buffalo_sc`） |
| ISSUE-007 | 01 §5 验收 | 缺「数据集/评测脚本/通过条件」的可执行定义；AC-1 的 200 张样本与 AC-6 的 demo 集未对齐 | 01 §5 增补「评测方法 + 复现命令」；指明 demo 数据集即 AC-1 用集 |
| ISSUE-008 | 02 §2.5 / 05 §4 | 软链接策略在 02 和 05 各写一份，略有差异（junction 优先级、硬链接判断）；同一行为出现两套实现 | 02 与 05 对齐；由 05 单一权威，02 引述 |

### 2.2 中优先级（影响交付质量）

| ID | 文档/位置 | 问题 | 处置 |
|----|----------|------|------|
| ISSUE-101 | 01 §3.4 F-OUT-1 | `meta.json` schema 未给；后续 review 子命令将依赖 | 05 增加 `meta.json` schema |
| ISSUE-102 | 03 §8 错误处理 | 缺退出码契约、JSON 进度事件协议、临时文件清理 | 03 §8 增补 |
| ISSUE-103 | 06 §3 测试 | 缺 fixture（合成人脸图）、mock 推理后端、CI cache 策略 | 06 §3 增补 |
| ISSUE-104 | 07 ADR-007 | 「不内置任何遥测」与「崩溃诊断」边界不清；需明确 `--diagnostics` 输出范围 | ADR-007 改写 |
| ISSUE-105 | 02 §3 / 04 §2.5 | 阈值命名混乱：02 提「同人 0.5–0.6」「cos < 0.3 不同人」；04 提「cos 0.55 合并 / 0.6 强同人」；01 §3 没引用 | 在 04 §3 统一为一份表，02/01 引述 |
| ISSUE-106 | 03 §2 架构图 | 缺 review 通路与 re-cluster 触发 | 架构图加 review 节点 |
| ISSUE-107 | 05 §3 HNSW | 缺 hnswlib API 选型版本、API 在 Windows 预编译 wheel 状态、与 SQLite 同步策略 | 增补 |
| ISSUE-108 | 04 §5 评测 | LFW 5,749 人 13,233 张在 2026 已是入门级，需补充更现代的基准（IJB-C/CALFW/CPF） | 增补现代基准 |
| ISSUE-109 | 03 §4 数据流 | 「xxh3」hash 在 doc 提了但 `source` 表 05 写 `hash`；没明确 hash 算法与长度 | 05 §2 显式 `hash_algo='xxh3_64'`, `hash TEXT NOT NULL` |
| ISSUE-110 | 01 §3.3 F-INCR-2 | 没说「外部破坏的链接」如何处理 | 03 §8 增补 `gc` 行为 |

### 2.3 低优先级（可后续打磨）

| ID | 文档/位置 | 问题 | 处置 |
|----|----------|------|------|
| ISSUE-201 | README 术语 | 「人物 ID = 脸 ID」表述易混 | 修订为「人物 ID ≠ 脸 ID」 |
| ISSUE-202 | 01 §6 风险 | 缺对 `pick-face` 包自身的许可声明 | 补一条 |
| ISSUE-203 | 02 §2.4 图像解码 | `imagecodecs` 与 `pillow-heif` 关系没厘清 | 显式说明 |
| ISSUE-204 | 04 §1 ASCII 图 | 缺少 HNSW 加速反馈环 | 在图上补 |

## 3. 已就地修订摘要

| 修订 | 影响文档 | 关联 ISSUE |
|------|---------|-----------|
| 进程模型分支 + ADR-008 | 03 / 07 | 001 |
| SQLite PRAGMA + 迁移 | 05 | 002 |
| staging → atomic rename 流程 | 05 | 003 |
| 依赖与 CI 章节 + 任务增补 | 06 | 004 |
| 簇质心合并触发与 ID 稳定性 | 04 | 005 |
| 批量 / 错误码 / 降级 | 03 | 006 |
| 验收脚本与复现命令 | 01 | 007 |
| 软链接策略单一权威（05） + 02 引述 | 02 / 05 | 008 |
| `meta.json` schema | 05 | 101 |
| 退出码 / JSON 事件协议 / 临时文件 | 03 | 102 |
| 测试 fixture 与 mock 推理后端 | 06 | 103 |
| 遥测 / 诊断边界 | 07 | 104 |
| 阈值统一表 | 04 | 105 |
| 架构图加 review 节点 | 03 | 106 |
| HNSW 选型与同步 | 05 | 107 |
| 评测基准扩展 | 04 | 108 |
| hash 算法显式化 | 05 | 109 |
| `gc` 行为细化 | 03 | 110 |
| 术语与许可 | README / 01 | 201/202 |
| 工程结构树状图（仓库 + 运行期 + 依赖方向） | 03 §4 | — |
| 包管理设计（`uv` 主线 + extras 矩阵 + 模型分发 + 发布流水线） | 03 §11 | — |
| **包管理器统一为 `uv`**（清理 03/06/08/01 中 `pip-tools` / `pipx` / `twine` / `pypa/build` 表述，立为不可变约束） | 03 §11.7 + 06 §7 + 01 §4 | NEW |
| **人脸识别流程详解**（端到端 15 节 + 0 摘要 + 13 例子） | 09（全新增） | NEW |
| **模型栈选型解读**（ML 模型：SCRFD / ArcFace / buffalo_l/sc / ONNX Runtime + 算法：hnswlib / HDBSCAN / xxh3 / Laplacian；含选型理由、许可、体积、升级策略、备选拒绝） | 10（全新增） | NEW |
| **商业部署合规指南**（`buffalo_l` 非商用风险的完整闭环：三层许可证 / 用户义务 / 3 条合规路径 / toml 字段 `accept_noncommercial_model_license` / 启动强校验 / `init-models` License Notice / `report.md` 顶部 Model+License 字段 / CI 守卫 / 发布流水线 / 退出码扩展 / 决策表） | 11（全新增）+ README/01/10 收口 | NEW |
| **`.gitignore` + `.dockerignore` 落地**（模型权重 / 训练数据 / 虚拟环境 / 构建产物 / 运行时数据 / 凭据 / IDE / OS / uv 缓存全黑名单；15 节按 [11 §3.1 / §3.5](11-commercial-compliance.md) + AC-9 落地） | 仓根 `.gitignore` + `.dockerignore`（全新增） | NEW |
| **文档入口改名 `docs/README.md` → `docs/AGENTS.md`**（内容保留，顶部加改名留痕段；同步修 [03 §4.1](03-architecture-design.md) 仓布局注释 + [08 §5](08-review-notes.md) `docs/01-07` 引用；外链与仓根 README 不动） | docs/AGENTS.md + 03/08 两处内部引用 | NEW |
| **v0.1 终审跨文档一致性体检（4 阶段 18 子项）**：A 引用 2 严重（修）/B 关键事实 7 子项 2 漂移（修 03 demo 体量 + 03/08 漏 AC-9）/C 术语一致/D 可实施性 5 缺口（**修 5 处：05 schema 补 `embedding`/`model_version`/`norm` 3 列、06 T-002 14 子命令、T-003 license 字段、T-009 Model+License、T-012 gpu-cuda12/directml、T-302 AC-9 守卫、11 §3.5 删未用常量**） | 02/03/05/06/08/10/11 联动修订 | NEW |

## 4. 待办（v0.1 仍要补）

- 真实 demo 数据集（去标识化、家庭相册样式）需在 v0.1 立项
- 报告 HTML 主题与暗色模式
- Web 预览（v0.2 路线）
- 多机协同（v0.4 路线）

## 5. 跨文档一致性体检与处置（v0.1 评审末轮）

> 评审末轮扫了 9 份文档，发现并就地修复的 5 处漂移：

| # | 漂移 | 处置 |
|---|------|------|
| C-1 | demo 数据集体量：01 写「50/2000」、04 写「50/875」、06 写「50/2000」与「200 张」 | 统一为 **50 人 / 约 1000 张**（每人 5–30 张随机），改 01/04/06 三处 |
| C-2 | `min_samples`：01 AC-1 锁定 2；02/04 写「1–2」 | 统一为 **2**（`01 AC-1` 权威），改 02/04 |
| C-3 | `low_confidence_faces.json` 阈值：04 §2.5 写「< 0.5」、04 §3 写「0.40」 | 统一为 **< 0.40**（与阈值表一致），改 04 §2.5 |
| C-4 | `pick-face init-models` 子命令：CLI 列表与 03 §11.5 / 02 §5 写法不一致 | CLI 列表新增 `init-models` / `prune` / `rollback` 三条 |
| C-5 | extras 切分：06 §7.2 缺 `[gpu-cuda12]` / `[gpu-directml]`；03 §3 模块表缺 `errors/progress/hashing/paths` | 06 §7.2 补齐；03 §3 模块表补齐，与 §4.1 仓库布局对齐 |

剩余可接受表述：
- 04 §1 ASCII 图把「SCRFD / RetinaFace」并列（同一检测器族）；保留。
- 多处「中端 x86」未给型号（i7-12700 是 04 §4 性能一处的具体锚点）；保留为软描述。
- 「ONNX Runtime EP 选型表」在 02 §2.5 与 05 §4.2 各出现一次，是有意重复（02 给结论，05 是单一权威）；保留。
- 03 §11.1 决策段落列出「`pip-tools / pipx / twine / pypa/build`」等替代项，是「我们不用谁」清单；保留。

## 6. 最终方案（单一权威解读）

> 评审末轮结论。**任何与本节冲突的章节，以本节为准**。

### 6.1 一句话定义

`pick-face` 是一个**本地离线**的 CLI 工具：递归扫描多个源目录的图片，使用 **InsightFace `buffalo_l`（ONNX Runtime）** 检测+生成 512-D L2 归一化嵌入，用 **HDBSCAN（cosine）+ 簇质心二次合并** 做无监督聚类，输出到目标目录的「**`person-XXXX/<src_rel_path>` 软链接**」结构。

### 6.2 关键选型（最终）

| 维度 | 最终选择 | 单一权威章节 |
|------|----------|--------------|
| 识别模型 | InsightFace `buffalo_l`（默认）/ `buffalo_sc`（`--fast`） | [02 §2.1](02-technical-pre-research.md) + [10 §2.1/2.2/2.3](10-model-stack.md) |
| 推理后端 | ONNX Runtime EP：`cpu` / `cuda` / `directml` | [05 §4.2](05-data-and-storage.md) |
| 聚类 | HDBSCAN，`metric='cosine'`，`min_cluster_size=3`，`min_samples=2`，`cluster_selection_method='leaf'` | [04 §2.4](04-algorithm-pipeline.md) |
| 二次合并 | 簇质心 cos ≥ **0.55** 强制合并 | [04 §2.4](04-algorithm-pipeline.md) |
| 同人阈值 | 强 ≥ 0.60 / 宽松 0.45–0.60 / 不同 < 0.30 / 低置信度 < 0.40 | [04 §3](04-algorithm-pipeline.md) |
| 索引 | SQLite（WAL）唯一权威；HNSW（hnswlib）缓存 | [05 §2–3](05-data-and-storage.md) + ADR-009 |
| 链接 | symlink → hardlink → copy，Windows 管理员权限失败时加 junction | [05 §4](05-data-and-storage.md) |
| 输出切换 | `staging-<run_id>` → atomic rename；旧版本保留 `.prev-<run_id>` | [05 §6](05-data-and-storage.md) + ADR-008 |
| 进程模型 | CPU 推理多进程 / GPU 推理单进程 + prefetch | [03 §8](03-architecture-design.md) + ADR-006 |
| 包管理 | **`uv` 唯一主线** | [03 §11](03-architecture-design.md) + ADR-007 不变量 |
| 隐私 | 默认离线；`--allow-network` 才允许 IO；`--diagnostics` 才落诊断 | [07 ADR-005/007](07-risk-and-decisions.md) |
| **商业合规** | `accept_noncommercial_model_license` 字段强校验；`buffalo_*` 需明示同意；商业用户走自训/换证/换模型族 | [11-commercial-compliance.md](11-commercial-compliance.md) 单一权威 |

### 6.3 验收基线（最终）

- **AC-1 聚类**：pairwise precision ≥ 0.95，pairwise recall ≥ 0.85，B³ F1 ≥ 0.90。
- **AC-2 幂等**：重复运行结果 `diff -r` 通过。
- **AC-3 增量**：新增 50 张后再次 run，检测+嵌入 < 30 秒。
- **AC-4 链接**：Linux/macOS 100% symlink；Windows 管理员 ≥ 95% symlink。
- **AC-5 清理**：删除 5% 源图后，对应输出链接被移除。
- **AC-6 复现**：demo = 50 人 / 约 1000 张（每人 5–30 张随机），`bench/dataset_demo/`。
- **AC-7 跨平台 smoke**：ubuntu / macOS / windows-latest CI。
- **AC-8 中断恢复**：SIGTERM 后重跑可继续，无重复 face / 孤儿链接。
- **AC-9 商业合规护栏**（合规底线，任何情况下不得降低）：`tests/acceptance/test_no_model_in_distribution.py` 全过；`accept_noncommercial_model_license` 字段强校验；`init-models` License Notice 不可关闭。详见 [11-commercial-compliance.md](11-commercial-compliance.md)。

### 6.4 路径与文件（最终）

```
<output>/
├── .cache/             # 索引权威 + 缓存
├── .staging-<run_id>/  # 半成品（不可见）
├── .prev-<run_id>/     # 上一版输出（最多 3 个，供 rollback）
├── .lock               # flock 互斥
├── index.json          # SQLite 镜像（调试）
├── report.md / .html
├── person-XXXX/
│   ├── meta.json
│   └── <src_rel_path> -> <abs_src>
├── _review/            # 宽松同人或低置信度（--emit-review 启用）
└── _archive/           # 被合并/废弃簇的旧链接（prune 清理）
```

### 6.5 子命令（最终）

`init / init-models / scan / index / cluster / link / run / report / review / review apply / gc / prune / rollback / rebuild`，详见 [03 §7](03-architecture-design.md)。

### 6.6 6 周里程碑（最终）

M1 原型 v0.1（2 周）→ M2 增量+校正（1.5 周）→ M3 GPU+性能（1.5 周）→ M4 1.0（1 周），详见 [06 §1](06-engineering-plan.md)。

### 6.7 仍开放的 v0.1 缺口

- 真实 demo 数据集（去标识化、家庭相册样式）需在 M1 立项。
- 报告 HTML 主题与暗色模式（M4）。
- Web 预览 / 多机协同延后到 v0.2 / v0.4。
- **商业用户自训脚本的封装**：[11 §4.1](11-commercial-compliance.md) 给了端到端流程，M1 需要把它做成 `scripts/train_commercial_model.sh` 一键脚本。
