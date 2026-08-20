# pick-face 文档总览

> 本目录汇总「图片人脸整理工具」从需求到上线的全链路文档。当前阶段：**M4 1.0 已发布 → M5 路线 B 落地中**。
>
> 当前日期：2026-08-07（用于校准版本与时效性）
>
> **文件说明**：本文件原名 `docs/README.md`，于 2026-07-30 改名为 `AGENTS.md`，作为**给 AI 代理（agent）/ 开发者**进入本项目时的**唯一入口**。所有内容（文档目录 / 阅读路径 / 术语 / 许可证速查）保持不变；其它文档中若仍引用 `docs/README.md`，请按本文件名 `docs/AGENTS.md` 解读。
> 关联：本次改名记录在 [08 §3 已就地修订摘要](08-review-notes.md)。路线 B 改动在 [10 §0](10-model-stack.md) / [11 §0](11-commercial-compliance.md) / [13](13-raspberry-pi-support.md) / [14](14-model-pack-plugins.md)。

## 0. 许可证速查（⚠ 先读这一段）

`pick-face` 项目代码与文档采用 **Apache License 2.0**，可自由商用、再分发、修改。

**路线 B 后（v2.0+）**：默认 model pack `yunet-mfn`（OpenCV Zoo YuNet + MobileFaceNet INT8）是 **Apache-2.0**，**默认就商用合规**，无需任何 license ack。**InsightFace 仍可作为 opt-in 插件使用**（要 `pip install pick-face-modelpack-insightface`），其权重仍受 InsightFace 自定义「非商业研究」条款约束。

| 物 | 许可证 | 商业可用？ |
|---|---|---|
| pick-face 代码 / 文档 | Apache-2.0 | ✅ |
| `pick-face-modelpack-yunet`（默认 pack） | Apache-2.0 | ✅ |
| onnxruntime / hnswlib / hdbscan / Pillow / OpenCV / numpy | MIT / Apache-2.0 / BSD / HPND | ✅ |
| `insightface` Python 包（opt-in 插件代码）| MIT | ✅ |
| **`buffalo_l` / `buffalo_sc` / `antelopev2` 权重**（opt-in 插件运行时下载）| **InsightFace 自定义（非商业研究）**| **❌** |

**商业部署怎么办**？详见 [docs/11-commercial-compliance.md](11-commercial-compliance.md)。**路线 B 后**最简路径：直接用默认 `yunet-mfn`（Apache-2.0，零 license 摩擦）；想更高精度再走"自训"或"商业 SDK license"。

---

## 1. 文档目录

| # | 文档 | 面向对象 | 主要内容 |
|---|------|---------|----------|
| 1 | [01-product-requirement.md](01-product-requirement.md) | 产品 / 业务 / 验收 | 目标、用户故事、功能清单、非功能需求、验收标准 |
| 2 | [02-technical-pre-research.md](02-technical-pre-research.md) | 研发 / 评审 | 候选技术对比、关键风险、最小可行性建议 |
| 3 | [03-architecture-design.md](03-architecture-design.md) | 研发 / 架构 | 系统架构、模块划分、数据流、接口契约 |
| 4 | [04-algorithm-pipeline.md](04-algorithm-pipeline.md) | 算法 / 研发 | 检测-对齐-嵌入-聚类-后处理全流程与超参 |
| 5 | [05-data-and-storage.md](05-data-and-storage.md) | 研发 / 运维 | 缓存与数据库 schema、软链接策略、目录布局 |
| 6 | [06-engineering-plan.md](06-engineering-plan.md) | PM / 研发 / 测试 | 里程碑、任务分解、测试策略、发布策略（含 M5 路线 B）|
| 7 | [07-risk-and-decisions.md](07-risk-and-decisions.md) | 评审 / 决策 | 风险登记、技术决策记录（ADR） |
| 8 | [08-review-notes.md](08-review-notes.md) | 评审 | 可实施性评审记录、问题清单、处置状态 |
| 9 | [09-face-recognition-pipeline.md](09-face-recognition-pipeline.md) | 研发 / 新人 onboarding | 人脸识别流程端到端详解（每一步的 why & how） |
| 10 | [10-model-stack.md](10-model-stack.md) | 研发 / 选型评审 | **model pack 总览**（yunet-mfn 默认 / InsightFace opt-in）+ 选型理由 + 许可与升级 |
| 11 | [11-commercial-compliance.md](11-commercial-compliance.md) | 商业用户 / 法务 | **商业部署合规指南**：LicenseClass 驱动 AC-9、四条合法路径（含 yunet-mfn 选项 D）|
| 12 | [12-compatibility-promise.md](12-compatibility-promise.md) | 维护者 | 兼容性承诺、版本契约 |
| 13 | [13-raspberry-pi-support.md](13-raspberry-pi-support.md) | Pi / ARM 用户 / 研发 | 树莓派 3B/4/RK3588/Apple Silicon 支持矩阵 + 安装步骤 + 性能基线 |
| 14 | [14-model-pack-plugins.md](14-model-pack-plugins.md) | 插件作者 / 高级用户 | ModelPack Protocol 完整定义 + entry-points 规范 + 写自己 pack 的 50 行示例 |

## 2. 阅读建议

- **5 分钟概览**：仅读 [01-product-requirement.md](01-product-requirement.md) 第 1–2 节与 [06-engineering-plan.md](06-engineering-plan.md) 里程碑表。
- **新人 onboarding**：[09-face-recognition-pipeline.md](09-face-recognition-pipeline.md) — 端到端读一遍，10 分钟理解全流程；再翻 [10 §0/§2 model pack 总览](10-model-stack.md) 看默认 vs opt-in。
- **技术评审**：[02-technical-pre-research.md](02-technical-pre-research.md) → [03-architecture-design.md](03-architecture-design.md) → [04-algorithm-pipeline.md](04-algorithm-pipeline.md) → [10-model-stack.md](10-model-stack.md) → [14-model-pack-plugins.md](14-model-pack-plugins.md) → [08-review-notes.md](08-review-notes.md)。
- **落地实施**：[03](03-architecture-design.md) + [04](04-algorithm-pipeline.md) + [05](05-data-and-storage.md) + [06](06-engineering-plan.md) + [07 ADR](07-risk-and-decisions.md)。
- **商业合规**：先读 [11-commercial-compliance.md](11-commercial-compliance.md) — 商业用户必读，路线 B 后默认 `yunet-mfn` 已商用合规。
- **Pi / ARM / NAS 部署**：直接读 [13-raspberry-pi-support.md](13-raspberry-pi-support.md)。
- **写自己的 model pack**：读 [14-model-pack-plugins.md](14-model-pack-plugins.md) §3 的 50 行示例 + §9 检查清单。

## 3. 术语

- **源图（source image）**：被扫描的输入目录中的原始图片。
- **脸（face）**：从源图中检测出的人脸实例，含检测框、关键点、嵌入向量、质量分；每个脸有唯一 `face.id`。
- **人物（person / cluster）**：聚类得到的「同一人」逻辑实体，对应输出目录中以 `person-XXXX` 命名的子目录；`person-id ≠ face.id`，人物 ID 由 `cluster.id` 决定，粘性保留。
- **输出链接（output link）**：输出目录中指向源图的软链接（或兼容性回退），由 `link` 表审计。
- **库（gallery）**：一次完整索引产生的所有数据，包含扫描快照、脸、人物、链接与运行日志。
- **staging 输出**：写入 `<out>/.staging-<run_id>/` 的「半成品」目录，原子切换前对外不可见。

## 4. 代码 / 包布局

`src/pick_face/` 按 5 个领域拆成子包（v1.0 起稳定）：

| 子包 | 职责 |
|------|------|
| `pick_face.core`     | 底层：config / errors / hashing / images / paths；不依赖任何其他子包。 |
| `pick_face.ingest`   | 摄取流水线：scanner / detector / embedder / align / cluster。 |
| `pick_face.store`    | 持久化：index (SQLite) / index_hnsw / checkpoint / review。 |
| `pick_face.output`   | 输出层：linker / mirrors / reporter / parallel。 |
| `pick_face.platform` | 平台/运维：runtime (ONNX EP) / **pack** (ModelPack Protocol + entry-points loader) / **packs/** (内嵌 yunet-mfn 实现) / models (license ack) / bench。 |

新代码请直接 `from pick_face.<sub>.<module> import ...`。
每个子包都有自己的 `__init__.py`（声明 `__all__: list[str] = []`），
顶层 `pick_face/__init__.py` 把公共 API 重新导出。

详见 [03 §3 模块划分](03-architecture-design.md) 与 [03 §4.1 仓库布局](03-architecture-design.md)。
