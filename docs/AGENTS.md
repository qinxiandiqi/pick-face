# pick-face 文档总览

> 本目录汇总「图片人脸整理工具」从需求到上线的全链路文档。当前阶段：**需求预研 & 技术方案研究 → 方案评审**。
>
> 当前日期：2026-07-30（用于校准版本与时效性）
>
> **文件说明**：本文件原名 `docs/README.md`，于 2026-07-30 改名为 `AGENTS.md`，作为**给 AI 代理（agent）/ 开发者**进入本项目时的**唯一入口**。所有内容（文档目录 / 阅读路径 / 术语 / 许可证速查）保持不变；其它文档中若仍引用 `docs/README.md`，请按本文件名 `docs/AGENTS.md` 解读。
> 关联：本次改名记录在 [08 §3 已就地修订摘要](08-review-notes.md)。

## 0. 许可证速查（⚠ 先读这一段）

`pick-face` 项目代码与文档采用 **Apache License 2.0**，可自由商用、再分发、修改。

**但是**：默认运行的 InsightFace `buffalo_l` 模型权重**不是** Apache-2.0 —— 它继承自 InsightFace 仓库的**「非商业研究用途」**条款。本项目**不**分发这些权重，**不**内置任何 ONNX，**不**在 CI / docker / wheel 里下载模型。

| 物 | 许可证 | 商业可用？ |
|---|---|---|
| pick-face 代码 / 文档 | Apache-2.0 | ✅ |
| insightface Python 包 | MIT | ✅ |
| onnxruntime | MIT | ✅ |
| hnswlib / hdbscan / Pillow / OpenCV / numpy | Apache-2.0 / BSD / HPND | ✅ |
| **buffalo_l 权重**（运行时下载） | **InsightFace 自定义（非商业研究）** | **❌** |

**商业部署怎么办**？详见 [docs/11-commercial-compliance.md](11-commercial-compliance.md)。一句话：**自训（MIT 训练脚本 + WebFace4M/Glint360K）→ 转 ONNX → 指向 `model_dir` → 改 `accept_noncommercial_model_license = false`**。

---

## 1. 文档目录

| # | 文档 | 面向对象 | 主要内容 |
|---|------|---------|----------|
| 1 | [01-product-requirement.md](01-product-requirement.md) | 产品 / 业务 / 验收 | 目标、用户故事、功能清单、非功能需求、验收标准 |
| 2 | [02-technical-pre-research.md](02-technical-pre-research.md) | 研发 / 评审 | 候选技术对比、关键风险、最小可行性建议 |
| 3 | [03-architecture-design.md](03-architecture-design.md) | 研发 / 架构 | 系统架构、模块划分、数据流、接口契约 |
| 4 | [04-algorithm-pipeline.md](04-algorithm-pipeline.md) | 算法 / 研发 | 检测-对齐-嵌入-聚类-后处理全流程与超参 |
| 5 | [05-data-and-storage.md](05-data-and-storage.md) | 研发 / 运维 | 缓存与数据库 schema、软链接策略、目录布局 |
| 6 | [06-engineering-plan.md](06-engineering-plan.md) | PM / 研发 / 测试 | 里程碑、任务分解、测试策略、发布策略 |
| 7 | [07-risk-and-decisions.md](07-risk-and-decisions.md) | 评审 / 决策 | 风险登记、技术决策记录（ADR） |
| 8 | [08-review-notes.md](08-review-notes.md) | 评审 | 可实施性评审记录、问题清单、处置状态 |
| 9 | [09-face-recognition-pipeline.md](09-face-recognition-pipeline.md) | 研发 / 新人 onboarding | 人脸识别流程端到端详解（每一步的 why & how） |
| 10 | [10-model-stack.md](10-model-stack.md) | 研发 / 选型评审 | 用到的 ML 模型 + 算法/数据结构 + 为什么这么选 + 许可与升级 |
| 11 | [11-commercial-compliance.md](11-commercial-compliance.md) | 商业用户 / 法务 | **商业部署合规指南**：默认模型非商用问题、用户义务、自训/换证路径、配置项语义 |

## 2. 阅读建议

- **5 分钟概览**：仅读 [01-product-requirement.md](01-product-requirement.md) 第 1–2 节与 [06-engineering-plan.md](06-engineering-plan.md) 里程碑表。
- **新人 onboarding**：[09-face-recognition-pipeline.md](09-face-recognition-pipeline.md) — 端到端读一遍，10 分钟理解全流程；再翻 [10-model-stack.md](10-model-stack.md) 看清每个模型是干嘛的、为什么不用别的。
- **技术评审**：[02-technical-pre-research.md](02-technical-pre-research.md) → [03-architecture-design.md](03-architecture-design.md) → [04-algorithm-pipeline.md](04-algorithm-pipeline.md) → [10-model-stack.md](10-model-stack.md) → [08-review-notes.md](08-review-notes.md)。
- **落地实施**：[03](03-architecture-design.md) + [04](04-algorithm-pipeline.md) + [05](05-data-and-storage.md) + [06](06-engineering-plan.md) + [07 ADR](07-risk-and-decisions.md)。
- **商业合规**：先读 [11-commercial-compliance.md](11-commercial-compliance.md) — 商业用户必读，避免触雷 buffalo_l 权重 license。

## 3. 术语

- **源图（source image）**：被扫描的输入目录中的原始图片。
- **脸（face）**：从源图中检测出的人脸实例，含检测框、关键点、嵌入向量、质量分；每个脸有唯一 `face.id`。
- **人物（person / cluster）**：聚类得到的「同一人」逻辑实体，对应输出目录中以 `person-XXXX` 命名的子目录；`person-id ≠ face.id`，人物 ID 由 `cluster.id` 决定，粘性保留。
- **输出链接（output link）**：输出目录中指向源图的软链接（或兼容性回退），由 `link` 表审计。
- **库（gallery）**：一次完整索引产生的所有数据，包含扫描快照、脸、人物、链接与运行日志。
- **staging 输出**：写入 `<out>/.staging-<run_id>/` 的「半成品」目录，原子切换前对外不可见。
