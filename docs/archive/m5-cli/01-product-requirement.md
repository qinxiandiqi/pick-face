# 01 产品需求文档（PRD）

> 文档版本：v0.1（预研稿） · 2026-07-30 · 状态：**待评审**

## 1. 背景与目标

### 1.1 业务背景
家庭相册、手机备份盘、摄影作品库中长期沉淀了大量图片。当需要「按人查找」时，传统方式依赖手工打标签或文件名搜索，效率极低且覆盖率低。本工具通过**本地离线**的人脸识别，将多个目录中的图片按「人」自动归类，输出可被其它工具直接消费的有序结构。

### 1.2 产品目标
- **G1** 自动按人脸把多源目录图片整理为「一人一目录」结构。
- **G2** 全流程在本地完成，**默认不联网**，**默认不上传任何数据**。
- **G3** 增量友好：支持重复执行、避免重复计算，可恢复中断。
- **G4** 结果可验证：聚类结果可人工浏览、抽样校验、必要时合并/拆分。

### 1.3 非目标（v1 范围内不做）
- 人脸属性识别（年龄/表情/口罩）—— 不在主线。
- 跨设备同步 / 云端协作 —— 仅本地。
- 视频中的人脸识别 —— 仅静态图片。
- 自动删除源文件 —— 工具仅创建软链接，不修改源。

## 2. 用户与场景

### 2.1 主要用户
| 用户类型 | 核心诉求 | 关心点 |
|---------|---------|--------|
| 普通家庭用户 | 把多年散落照片快速按人分类 | 易用、稳定、隐私 |
| 摄影爱好者 | 跨多盘/多设备的素材归集 | 准确率、增量速度 |
| 小型工作室 | 给客户样片按模特归档 | 重复执行可控、链接稳定 |

### 2.2 关键场景
- **S1 首次整理**：选择 2–3 个照片目录 → 一键运行 → 输出目录得到「person-0001/…、person-0002/…」结构。
- **S2 增量更新**：过几天又导入新照片 → 再次运行 → 新照片被自动并入既有的人物目录，不会重算历史。
- **S3 校正聚类**：发现 person-0007 实际是两个人 → 在结果中把人脸拖到正确的人物下 → 后续运行沿用。
- **S4 全量重建**：换算法或调阈值 → 重建索引，输出目录被原子替换。

## 3. 功能需求

### 3.1 输入管理
- **F-IN-1** 支持配置**多个**扫描源目录（YAML/TOML/JSON 任一）。
- **F-IN-2** 默认**递归**扫描子目录，可按 glob 排除（`exclude`）。
- **F-IN-3** 支持配置允许的图片后缀集合，默认包含 jpg/jpeg/png/webp/heic/tiff/bmp/gif（首帧）。
- **F-IN-4** 输入目录权限不足 / 包含符号链接时给出明确提示而非崩溃。

### 3.2 识别与归集
- **F-ID-1** 检测每张图片中的所有人脸并生成嵌入向量。
- **F-ID-2** 使用无监督聚类在**未知人数**下将人脸分成不同人物。
- **F-ID-3** 在输出目录为每个人物创建子目录，将该人物对应源图的**软链接**放入其中。
- **F-ID-4** 重复源图（同名或内容相同）只产生一条结果，策略可配（哈希去重 vs 路径去重）。
- **F-ID-5** 同源图可关联到多个人物（多人合影）。

### 3.3 增量与一致性
- **F-INCR-1** 增量模式：仅处理新增/修改的源图，保留历史结果。
- **F-INCR-2** 源图被删除时，对应的输出链接被清理（仅清理本工具创建的链接，不动源图）。
- **F-INCR-3** 一次运行可被中断/恢复，不损坏已写出的链接。
- **F-INCR-4** 支持「dry-run」与「full-rebuild」两种模式。

### 3.4 输出与可观察性
- **F-OUT-1** 输出目录结构清晰稳定：`<output>/<person-id>/<source-relative-path>`，其中 `person-id` 形如 `person-0001`，对应一份 `meta.json` 描述该人物。
- **F-OUT-2** 顶层维护一份 `index.json` 或 `index.sqlite`，记录扫描快照、人物-人脸-源图映射、运行历史。
- **F-OUT-3** 提供命令行/JSON 两种进度输出。
- **F-OUT-4** 输出目录下生成 `report.html` 或 `report.md`：人物数、人脸数、置信度分布、异常清单。

### 3.5 校正与人工介入
- **F-OP-1** 合并/拆分人物：将人脸在不同人物之间移动；后续运行以人工标注为强约束。
- **F-OP-2** 标记噪声人脸：将其从聚类中排除。
- **F-OP-3** 命令行子命令：`scan / index / cluster / link / report / review / gc`。

### 3.6 跨平台
- **F-PLAT-1** Windows / macOS / Linux 三平台均能完成「软链接」目标；无权限时回退为**拷贝**并明确日志告警。

## 4. 非功能需求

| 维度 | 指标 |
|------|------|
| 准确性 | 在 LFW 公开子集上，聚类 pairwise precision ≥ 0.95（同一对被分到不同人为错误），pairwise recall ≥ 0.85。 |
| 性能 | 单核 CPU 推理 ≥ 2 张/秒（中等分辨率 1080×1500）；GPU 可用时 ≥ 30 张/秒。 |
| 稳定性 | 1 万张图片的扫描/聚类在单次进程内完成，无内存峰值 OOM；支持断点续跑。 |
| 可移植 | Python 3.10–3.12；包管理统一 `uv`（`uv venv` / `uv pip install`），提供 `pyproject.toml` + `requirements.lock`。 |
| 隐私 | 默认离线；显式 `--allow-network` 才允许下载模型。 |
| 许可证 | pick-face 本体 Apache-2.0；默认模型 `buffalo_l` **非商业研究用途**（详见 [11-commercial-compliance.md](11-commercial-compliance.md) 与 R-COM-1）。 |
| 可维护 | 模块化，关键算法可替换（接口稳定），测试覆盖率 ≥ 70%。 |

## 5. 验收标准（v0.1 预研版）

通用前置：所有验收跑在 `bench/dataset_demo/` 提供的去标识化家庭相册 demo 上（**50 人 / 约 1000 张**——每人在 5–30 张之间随机，确保稀有人物也能被检测，详见 [06 §3 测试策略](06-engineering-plan.md#3-测试策略) 与 fixture `tests/fixtures/demo_dataset/`）。评测脚本：`tests/acceptance/run_eval.py`，输出 `eval_report.json` 含 pairwise precision/recall、B³ F1、误合并率、运行时间。

- [ ] **AC-1 聚类一致性**：在 demo 集上，聚类 pairwise precision ≥ 0.95，pairwise recall ≥ 0.85，B³ F1 ≥ 0.90（相对 `InsightFace buffalo_l + HDBSCAN(cosine, min_cluster_size=3, min_samples=2) + 簇质心合并阈值 0.55` 基线）。
- [ ] **AC-2 幂等**：对同一目录重复运行，第二次输出与第一次**逐字节一致**（基于 `(abs_path, size, mtime, sha1_8)` 幂等键），可用 `diff -r` 通过。
- [ ] **AC-3 增量**：在首次完成索引的状态下新增 50 张图，第二次运行检测+嵌入阶段总耗时 < 30 秒，且无重复写入历史 `face`。
- [ ] **AC-4 软链接回退**：
  - Linux/macOS：100% `os.symlink` 成功。
  - Windows 管理员/开发人员模式：≥ 95% symlink；其余自动回退 junction（目录）或 hardlink（文件）。
  - Windows 普通用户：自动回退 `copy2`，并在 `report.md` 顶部 `Warnings` 节列出。
- [ ] **AC-5 清理**：删除 5% 源图后再运行，对应输出链接被移除（`gc` 子命令复核），输出目录其它链接不受影响。
- [ ] **AC-6 复现**：README 给出 5 分钟 quickstart；`bench/dataset_demo/README.md` 注明数据来源、许可、再生成命令；`pytest -q` 全过、`tests/acceptance/run_eval.py` 产出 `eval_report.json`。
- [ ] **AC-7 跨平台 smoke**：ubuntu-latest / macos-latest / windows-latest CI 各跑通 `pick-face run --src bench/dataset_demo/src --out <tmp>` 一次。
- [ ] **AC-8 中断恢复**：`pick-face run` 在第 N 张图被 SIGTERM 中断后，重新运行同一命令能继续完成索引，不出现重复 face 或孤儿链接。
- [ ] **AC-9 商业合规护栏（合规底线，**任何情况下不得降低**）**：
  - pick-face **不**分发任何 `*.onnx` 模型权重进 git / wheel / sdist / docker / PyPI 镜像（CI 校验 `tests/acceptance/test_no_model_in_distribution.py`）。
  - 启动时若检测到当前模型为 `buffalo_*`，而 `pick-face.toml` 的 `accept_noncommercial_model_license = false` —— **拒启动**（退出码 2），错误信息明确指向 [11-commercial-compliance.md](11-commercial-compliance.md)。
  - `pick-face init-models` 首次下载前**强制交互式确认** InsightFace 权重 license 条款（详见 [11 §2.1](11-commercial-compliance.md)）。
  - `report.md` 顶部必须打印「Model: ... | License: ...」一行，便于审计。
  - 测试集中**禁止**提交任何 `*.onnx`（含 `tests/fixtures/`）。

## 6. 风险与依赖

- 聚类准确率受光照、年龄跨度、遮挡影响显著，需要保留人工校正入口。
- HEIC/RAW 解码依赖系统库；macOS 自带，Windows/Linux 需额外安装（extras：`pick-face[heic]`、`pick-face[raw]`）。
- Windows 创建符号链接需「开发人员模式」或管理员权限，需在文档中说明回退策略。
- 模型许可：默认使用 InsightFace `buffalo_l`，其代码 MIT、模型**非商业研究用途**；本工具的发行许可（建议 Apache-2.0）与模型许可解耦，README 顶部明记「默认不联网 + 模型来源 + 非商用提示」。**完整合规指南见 [11-commercial-compliance.md](11-commercial-compliance.md)。**
- 本工具不内置任何遥测；崩溃诊断信息仅在用户显式 `--diagnostics` 时写本地文件（见 [07-risk-and-decisions.md](07-risk-and-decisions.md) ADR-007）。

### 6.1 商业合规风险（必读）

| ID | 风险 | 缓解 | 责任 | 处置 |
|----|------|------|------|------|
| **R-COM-1** | 默认 `buffalo_l` 权重 license 禁止商业用途；用户**使用**即触发条款 | ①代码与权重**完全解耦**（不捆绑、不进仓、不进 wheel/docker/CI）；②`pick-face.toml` 加 `accept_noncommercial_model_license` 字段，默认 `false`；③`init-models` 强制交互确认；④启动时**强校验**，商用 `false` + buffalo_l → 拒启动；⑤README/LICENSE/docs/11 顶部明记"用户自负" | **商业用户**自负合规义务；项目方**不为第三方权重背书** | [11-commercial-compliance.md](11-commercial-compliance.md)（单一权威） |

## 7. 后续版本展望

- v0.2：交互式 Web 预览（仅本地）。
- v0.3：视频抽帧 + 时间轴。
- v0.4：多机协同（共享索引库）。
