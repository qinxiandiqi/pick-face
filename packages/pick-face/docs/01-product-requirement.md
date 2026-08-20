# 01 产品需求：pick-face Web 相册服务（v3.0）

> 文档版本：v3.0 · 2026-08-12 — 产品形态从 CLI 迁移到 **Web 服务**
> 范围：定义 pick-face v3 的用户故事、核心能力、非目标
> **本文是单一权威解读**。任何与本文件冲突的章节（README / 03 / 04 / 06 / 09 / 11），以本文件为准。
> 关联：[02 §栈选型](02-technical-pre-research.md) · [03 §服务架构](03-architecture-design.md) · [04 §聚类流水线](04-algorithm-pipeline.md) · [06 §M6+ 里程碑](06-engineering-plan.md)

## 0. 摘要（60 秒版）

pick-face v3 是一个**自托管**的人脸相册服务（Web 服务）：

- 用户在 Web UI 配置**一个或多个图片扫描根路径**（如 `/mnt/photos/2024/`、`/mnt/photos/2025/`）
- 服务在后台**遍历**这些路径下的所有图片，**检测人脸**，**按人聚类**
- 用户在浏览器打开 **`/persons`** 看到按人聚合的**虚拟相册**
- 点开一个人 → 进入瀑布流式图片查看器：上一张 / 下一张 / 缩放 / 手势 / 全屏 / 滑动切换
- 所有数据保存在本地文件系统，**离线**运行，**不联网**（模型权重首次启动下载一次）

```
┌─────────────┐       ┌────────────────────┐
│ 浏览器 SPA  │ HTTP  │  pick-face 服务    │
│ (React/Vite/TS + shadcn/ui) │ ◀──▶  │  FastAPI / 异步    │
└─────────────┘       │   ├─ scanner       │
                      │   ├─ detector      │
                      │   ├─ embedder      │
                      │   ├─ indexer       │
                      │   └─ clusterer     │
                      └────────┬───────────┘
                               │
                ┌──────────────┴──────────────┐
                ▼                             ▼
        /mnt/photos/2024/              ~/.pick-face/data/
        /mnt/photos/2025/              ├── index.sqlite
                                       ├── index.hnsw
                                       ├── chips/      # 人脸封面（112×112）
                                       ├── thumbnails/ # 原图缩略图
                                       └── covers/     # 虚拟相册封面
```

## 1. 用户故事

### 1.1 US-1 配置扫描路径（首要）
> 作为用户，我想让 pick-face **扫描我指定的照片目录**，自动找出有脸的图片。

**验收标准**：
- AC-1：Web UI 提供表单，让用户**添加 / 删除**扫描根路径
- AC-2：每个路径必须通过 `Path.resolve()` + 白名单校验，**禁止** `../../etc/passwd` 之类的穿越
- AC-3：路径必须存在、可读、含图片文件；不满足时给出明确错误
- AC-4：保存后立即触发一次扫描（或显式提供"立即扫描"按钮）

### 1.2 US-2 后台扫描与进度可见
> 作为用户，我想**看到扫描进度**（不是黑箱）。

**验收标准**：
- AC-1：扫描过程中 Web UI 显示进度条（已处理 / 总数）
- AC-2：失败文件（损坏 / 权限）单独计数，不中断整体
- AC-3：扫描可暂停、恢复、取消
- AC-4：扫描结束后给摘要（"新增 N 张、检测出 M 张脸、聚成 K 个虚拟相册"）

### 1.3 US-3 以人为单位的虚拟相册
> 作为用户，我想**看到所有"人"的列表**，每个人是一个虚拟相册。

**验收标准**：
- AC-1：`/persons` 列出所有聚类（按"代表性图片 + 该人照片数"排序）
- AC-2：可重命名 / 合并 / 删除虚拟相册（review 操作，与 CLI 时代共享 `output/review.py`）
- AC-3：每个虚拟相册点开后是瀑布流，展示该人所有出现过的原图
- AC-4：缩略图懒加载，原图按需请求
- AC-5：**每个虚拟相册必须有清晰的"封面脸"**——使用 `faces.chip_path`（112×112 对齐后人脸），不是原图缩略图；用户看到列表就能认出是谁

### 1.4 US-4 图片查看器（核心交互）
> 作为用户，我想**像普通相册 App 一样**浏览单张图片。

**验收标准**：
- AC-1：上一张 / 下一张（键盘 ←/→、点击、滑动）
- AC-2：双击 / 双指放大缩小，鼠标滚轮缩放
- AC-3：拖动图片查看细节（pan）
- AC-4：全屏切换（Esc 退出，←/→ 在全屏下仍然工作）
- AC-5：可看到 EXIF 日期、文件名、所在原图路径
- AC-6：手机端支持触摸手势（pinch、swipe、tap）
- AC-7：**绝不在前端保存原图到相册**——原图通过 HTTP Range 流式返回，不复制原图到 service 数据目录

### 1.5 US-5 增量更新
> 作为用户，新照片加进扫描路径后，**相册自动更新**，无需手动重扫。

**验收标准**：
- AC-1：服务**监听**扫描路径的目录变更（`inotify` / `watchdog` / 周期轮询 三选一）
- AC-2：新文件自动加入扫描队列
- AC-3：删除的文件**软删除**（不在数据库消失，留待人工 review）
- AC-4：增量扫描的资源使用（CPU/内存）有上限，不阻塞 HTTP 响应

### 1.6 US-6 多源聚合
> 作为用户，我想**多目录聚合**——例如 `/mnt/photos/2024/` 和 `/mnt/photos/2025/` 都扫描，跨目录同人仍然归到一个虚拟相册。

**验收标准**：
- AC-1：多个扫描路径共享同一套人脸索引（同一 cluster）
- AC-2：跨目录同人聚类精度 ≥ 单目录聚类（**F1 不下降**）
- AC-3：UI 上能看到"这个人来自 N 个目录"

## 2. 核心能力（必须）

| 能力 | 必须 | 说明 |
|---|---|---|
| 路径白名单 + 路径穿越防护 | ✅ | 安全底线 |
| 后台扫描（异步任务） | ✅ | 不可阻塞 HTTP |
| 人脸检测 + 嵌入 | ✅ | 复用 v2.x Model Pack 架构 |
| HNSW 索引 | ✅ | 复用 `store/index_hnsw.py` |
| HDBSCAN 聚类 | ✅ | 复用 `ingest/cluster.py` |
| Review（重命名 / 合并 / 删除） | ✅ | 复用 `store/review.py` |
| 缩略图生成 | ✅ | 新增；存 `~/.pick-face/data/thumbnails/<hash>.jpg` |
| 人脸 chip 生成 | ✅ | 新增；存 `~/.pick-face/data/chips/<face_id>.jpg`（虚拟相册封面） |
| 虚拟相册封面 | ✅ | 新增；用 chip，不用原图缩略图；存 `~/.pick-face/data/covers/person_<id>.jpg` |
| HTTP API | ✅ | FastAPI + OpenAPI 文档 |
| SPA 前端 | ✅ | React + Vite + TS + shadcn/ui + Tailwind 单页应用 |
| 流式原图（HTTP Range） | ✅ | 不复制原图到数据目录 |
| 增量扫描 | ✅ | inotify / 周期轮询 |
| 离线运行 | ✅ | 模型下载一次后无外网请求 |
| AC-9 模型许可护栏 | ✅ | 复用 v2.x 的 LicenseClass 体系 |

## 3. 非目标（v3 不做）

| 不做 | 原因 |
|---|---|
| **用户账号 / 多租户** | 单用户自托管优先；多用户留给 v4 |
| **照片编辑**（裁剪、滤镜） | 服务只聚类，不编辑 |
| **上传到云** | 离线 / 自托管是核心承诺 |
| **AI 自动打标签**（人物关系识别、场景识别） | v3 只做人脸聚类 |
| **手机 App** | v3 只做 Web；PWA 已能满足 90% 移动端 |
| **视频抽帧** | v3 只处理图片；视频留给 v3.1 |
| **HEIC / RAW 之外的格式强需求** | 复用 Pillow / pillow-heif / rawpy，已覆盖 |

## 4. 验收里程碑（与 06 §里程碑 对齐）

| 验收编号 | 内容 | 通过条件 |
|---|---|---|
| AC-W1 | 路径白名单 + 配置页可用 | 提交 `../etc/passwd` 被拒；合法路径被接受 |
| AC-W2 | 扫描 1000 张图片，后台任务正常运行 | 进度可见；失败文件不中断；CPU 不爆 |
| AC-W3 | 人脸检测 + 嵌入完成，索引构建 | SQL 查到 ≥ 800 张脸的 embedding |
| AC-W4 | HDBSCAN 聚类，B³ F1 ≥ 0.85（AT&T 实测） | 见 04 §聚类验收 |
| AC-W5 | `/persons` 列出 ≥ 10 个虚拟相册 | UI 可见、可点开 |
| AC-W5b | 虚拟相册封面 = 112×112 人脸 chip | 用户一眼认出"这是谁" |
| AC-W6 | 图片查看器支持 上一张 / 下一张 / 缩放 / 拖动 | 浏览器端 E2E 测试通过 |
| AC-W7 | 流式原图（不复制到数据目录） | `du -sh ~/.pick-face/data/` 不增长（除了 chips / thumbnails / covers） |
| AC-W8 | 增量：新加一张图，30 秒内出现在聚类结果 | Webhook 或轮询 |
| AC-W9 | 多目录聚合：跨目录同人合并 | 手动建 fixture，验证 B³ F1 不降 |

## 5. 部署形态

```
单容器部署（推荐）：
  Docker 镜像
  ├─ FastAPI (uvicorn, port 8000)
  ├─ worker (后台扫描 + 索引)
  └─ SQLite / 共享 volume

裸机部署：
  uv venv
  uv pip install -e ".[web]"
  pick-face-web serve --config /etc/pick-face/config.toml
```

**资源占用基线**（100k 张照片）：
- 内存：~1.5 GB（detector session + HNSW + HDBSCAN）
- 磁盘：原图 + thumbnails（~5 GB）+ SQLite（~500 MB）+ HNSW（~200 MB）+ chips（~5 GB / 800k 张脸）
- CPU：x86 4 核 + GPU 可用时首扫 ~30 分钟

**应用根目录**（所有 pick-face 持久化文件归这一个目录，原图不在内）：

```
~/.pick-face/                             # 应用根目录（= PICK_FACE_HOME 默认值）
├── config/                               # 配置（用户可编辑）
├── data/                                 # 数据（备份这一项 = 备份整个相册）
└── cache/                                # 缓存（模型权重可重下）
```

> 可通过环境变量 `PICK_FACE_HOME` 或配置 `[server] data_dir` 覆盖根目录（Docker / 多实例）。

## 6. 与 v2.x（CLI 时代）的兼容

- **算法内核 100% 复用**：detector / embedder / indexer / clusterer / review
- **Model Pack 架构 100% 复用**：`yunet-sface`（默认 MIT）/ `yunet-arcface`（高精度 Apache-2.0）
- **CLI 子命令保留为可选**：`pick-face-web run --src ...` 仍能用单次 CLI 模式（无 Web UI）
- **配置文件路径**：`~/.config/pick-face/config.toml`（与 v2.x 兼容）

## 7. 引用与延伸阅读

- [02 §栈选型](02-technical-pre-research.md) — 为什么选 FastAPI / SQLite / React + shadcn/ui
- [03 §服务架构](03-architecture-design.md) — 服务模块、worker、HTTP API
- [04 §聚类流水线](04-algorithm-pipeline.md) — 检测 → 嵌入 → 聚类算法细节
- [05 §数据与存储](05-data-and-storage.md) — SQLite schema / 文件布局
- [06 §M6+ 里程碑](06-engineering-plan.md) — 何时能上线
- [11 §商业合规](11-commercial-compliance.md) — NC-research 模型护栏
- 归档：[M5 CLI 时代 PRD](archive/m5-cli/01-product-requirement.md) — 历史参考