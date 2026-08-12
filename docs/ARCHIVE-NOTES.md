# pick-face 文档归档说明

## 归档范围：`docs/archive/m5-cli/`

本目录保存的是 **M5 路线 B（CLI 工具）** 时代的全部设计文档，对应产品形态：
- **本地离线** 的人脸识别 CLI（`pick-face run`、`pick-face init`、`pick-face init-models`、`pick-face doctor`）
- 命令行输出 `by_face/person_XXXX/<src_rel_path>` 硬链接目录
- 单用户、本地文件系统

## 归档原因

2026-08-12 **产品需求重大调整** —— pick-face 从 CLI 工具转型为 **Web 相册服务**：

> "把这个项目改成一个 web 相册服务。服务中可以配置图片扫描路径，服务会在这些路径中遍历所有的图片进行人脸检测，然后根据人脸对图片进行分组聚合。服务还要提供在线相册查看的功能，以人为单位组件虚拟相册，可以打开相册可以查看这个人所有的图片。图片查看包括上一张下一张手势放大缩小等常见的相册操作。"

CLI 时代的需求假设与新需求之间存在根本差异：

| 维度 | M5 CLI 时代（已归档） | Web 相册服务（当前） |
|---|---|---|
| 用户界面 | CLI / 文件系统（`by_face/` 硬链接） | 浏览器（HTTP API + SPA） |
| 部署形态 | 单机、本地、批处理 | 长驻服务、多用户（可能）、跨平台 |
| 资源隔离 | 无（直接读 src 路径） | 需要路径白名单、读权限、路径遍历防护 |
| 输出 | 一次性目录链接 | 增量更新、进度可见 |
| 缩略图/原图 | 不需要（用户自己打开） | 必须（相册流式加载、图片查看器） |
| 模型后端 | CLI flag：`pick-face run --provider cpu` | Web 端无需选模型，但 GPU 仍要走 CUDA |

**复用部分**（保留作为基础）：
- 模型层：YuNet + SFace / ArcFace（仍然用）
- 算法层：检测 → 对齐 → 嵌入 → HNSW → HDBSCAN 聚类
- Model Pack 插件架构（v2.1.0 已稳定）

**需要重做部分**：
- 服务层：HTTP API + 前端 SPA
- 增量扫描、watcher、进度
- 缩略图、瀑布流、查看器
- 多用户 / 鉴权 / 路径权限

## 当前文档结构

```
docs/
├── AGENTS.md                     # 工作流 / 工具链（仍然有效）
├── index.md                      # 文档索引（会重写）
├── troubleshooting.md            # 故障排查（保留+扩展）
├── 01-product-requirement.md     # NEW：Web 相册服务 PRD
├── 02-technical-pre-research.md  # NEW：栈选型 / 库对比
├── 03-architecture-design.md     # NEW：服务架构
├── 04-algorithm-pipeline.md      # NEW：人脸聚类流水线（复用 CLI 时代的算法）
├── 05-data-and-storage.md        # NEW：相册数据模型
├── 06-engineering-plan.md        # NEW：M6+ 里程碑（Web 服务化）
├── 11-commercial-compliance.md   # 仍然有效（模型许可护栏）
├── 12-compatibility-promise.md   # 仍然有效（API 兼容策略）
└── archive/
    └── m5-cli/                   # 全部 CLI 时代设计文档（read-only 归档）
        ├── 01-product-requirement.md
        ├── ... (14 个文件)
        └── 14-model-pack-plugins.md
```

## 引用旧文档

如果遇到 CLI 时代假设与 Web 时代假设不一致的地方，以 **当前目录** 的新文档为准。
旧文档可作为**算法层**（检测 / 嵌入 / 聚类）的历史参考 —— 这部分技术细节与产品形态解耦，CLI 和 Web 服务共享同一套算法内核。