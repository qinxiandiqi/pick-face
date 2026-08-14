# 06 工程计划：M6+ 里程碑（v3.0 Web 相册服务）

> 文档版本：v3.0 · 2026-08-12
> 范围：从 M5（CLI 落地）到 M6（Web 服务化）的里程碑拆解
> 关联：[01 PRD](01-product-requirement.md) · [03 §服务架构](03-architecture-design.md)

## 0. 摘要

v2.x（M0–M5）已经把"CLI 工具 + 算法内核 + Model Pack 架构"做完了。M6+ 把产品形态迁移到 Web 服务，复用 100% 算法内核。

| 里程碑 | 范围 | 周期（估）|
|---|---|---|
| **M6** | 服务骨架 + 路径配置 + 扫描 + 瀑布流（无手势） | 4 周 |
| **M7** | 图片查看器（手势、缩放、滑动）+ EXIF + 元数据 | 2 周 |
| **M8** | 增量扫描 + watchdog + 周期重聚类 | 2 周 |
| **M9** | 多目录聚合 + review UI + 合并/重命名 | 2 周 |
| **M10** | 打包 + Docker + 部署文档 + Beta 招募 | 2 周 |
| **M11** | v3.0 正式发布 | — |

总计 ~12 周。**前置**：M5（CLI + yunet-arcface）已发布 ✅。

## 1. M6 — 服务骨架 + 扫描 + 瀑布流

**目标**：能跑起来的最小 Web 服务，能看瀑布流。

### 1.1 子任务

| 任务 ID | 内容 | 依赖 |
|---|---|---|
| M6-T-1 | FastAPI app 骨架 + Uvicorn 启动 | — |
| M6-T-2 | `service/config_service.py` 路径白名单 | — |
| M6-T-3 | `api/config.py` CRUD + 表单 | M6-T-2 |
| M6-T-4 | `service/scan_service.py` 启动扫描 | M6-T-2 |
| M6-T-5 | `worker/scan_worker.py` 复用 v2.x ingest/* | M6-T-4 |
| M6-T-6 | `api/scan.py` 进度 SSE | M6-T-4 |
| M6-T-7 | `store/index.py` 增量扫描（基于 content_hash + mtime）| M6-T-5 |
| M6-T-8 | `service/photo_service.py` 缩略图生成 | M6-T-5 |
| M6-T-9 | `api/photos.py` 缩略图 + 原图流（HTTP Range） | M6-T-8 |
| M6-T-10 | `api/persons.py` 虚拟相册 list | M6-T-7 |
| M6-T-11 | SPA 骨架（Vite + React + TS + shadcn/ui + Tailwind 初始化） ✅ M7 | — |
| M6-T-11a | shadcn/ui 配置（`components.json`、`tailwind.config.ts`、CSS 变量、`<ThemeProvider>`） ✅ M7 | M6-T-11 |
| M6-T-11b | 引入基础 shadcn/ui 组件：`Button` `Card` `Input` `Dialog` `Toast` `Skeleton` `Tabs` `Switch` `Slider` `DropdownMenu` `Tooltip` `Badge` `Progress` `Sheet` `Command` ✅ M7 | M6-T-11a |
| M6-T-12 | SPA `/settings` 路径配置 UI（`Tabs` + `Dialog` + `Switch` + `react-hook-form` + `zod`） ✅ M7 | M6-T-3 |
| M6-T-13 | SPA `/persons` 瀑布流（react-photo-album + `Skeleton` 占位） ✅ M7 | M6-T-10 |
| M6-T-14 | SPA `/persons/:id` 单人瀑布流 + `Sheet` EXIF 抽屉 ⏸️ 部分（Sheet 推迟到 M7.5；详情页 + 查看器已交付） | M6-T-13 |
| M6-T-15 | 手写 TypeScript API 客户端（替代 OpenAPI 自动生成；14 个端点 + zod schemas） ✅ M7 | M6-T-1 |
| M6-T-16 | Docker 多阶段构建 | M6-T-1 |

### 1.2 验收

- AC-W1：路径白名单 ✅
- AC-W2：扫描 1000 张图，进度可见 ✅
- AC-W3：检测 + 嵌入 ✅
- AC-W5：`/persons` 列出 ≥ 10 个虚拟相册 ✅
- AC-W7：原图流式 ✅

## 2. M7 — 图片查看器

**目标**：完整的桌面 + 移动端相册体验。

### 2.1 子任务

| 任务 ID | 内容 | 依赖 |
|---|---|---|
| M7-T-1 | `<FaceViewer>` 组件：键盘 ←/→/Space ✅ M7 | M6-T-14 |
| M7-T-2 | `<FaceViewer>` 鼠标滚轮缩放 + 双击 100%↔fit ✅ M7 | M7-T-1 |
| M7-T-3 | `<FaceViewer>` 拖动 pan ✅ M7 | M7-T-2 |
| M7-T-4 | `<FaceViewer>` 全屏切换（F / Esc） ✅ M7 | M7-T-2 |
| M7-T-5 | `@use-gesture/react` 触摸手势（pinch、swipe、tap） ✅ M7 | M7-T-2 |
| M7-T-6 | `<FaceOverlay>` 在图上画 bbox ✅ M7.5（服务端 bbox + 客户端 SVG overlay + highlightClusterId 过滤） | M7-T-1 |
| M7-T-7 | `api/photos/{id}/metadata` bbox + faces + 自然尺寸 + EXIF ✅ M7.6 | — |
| M7-T-8 | 信息层抽屉（路径/尺寸/人脸/EXIF 占位） ✅ M7.5（EXIF 占位等后端） | M7-T-7 |
| M7-T-9 | PWA manifest + service worker ✅ M7.9（vite-plugin-pwa 0.21.2；workbox generateSW；app shell + `/api/photos/{id}/thumb` CacheFirst 30d + `/api/persons{,/{id}/photos}` SWR 1h；`RangeRequestsPlugin` 默认处理原图；`Settings → App` 手动 install 按钮 + 受控 update toast；`registerSW.js` + `sw.js` + `manifest.webmanifest` + 3 个 PNG icons；`AC-W10` ✅） | M7-T-1 |
| M7-T-10 | 浏览器 E2E 测试（Playwright）⏸️ M7.5 | M7-T-1 |
| M7-T-11 | `Toast` (sonner) 错误反馈统一封装 ✅ M7.7（`lib/toast.ts` 门面 + `toast.fromError` 收口） | M6-T-11b |
| M7-T-12 | ~~全局 `Command` (cmdk) 搜索~~ ❌ 已取消（2026-08-13：未发现足够有意义的目标列表；persons 数 ≤ 50 + 4 个 settings tab + 静态 actions，搜索的价值不抵 keybind 复杂度成本） | M6-T-11b |
| M7-T-13 | `Badge` 标注 NC-research 模型包警告 ✅ M7.8（`/api/ready.active_pack` + `<ModelPackCard>` 三态 Badge + 未确认警告 toast） | M6-T-11b |

### 2.2 验收

- AC-W6：上一张 / 下一张 / 缩放 / 拖动 ✅
- 移动端手势（pinch、swipe、tap）✅
- AC-W10：PWA 可安装（`Settings → App → Install app`）+ 离线壳加载（`navigator.onLine === false` 下 `/` 仍可渲染）+ 二次访问瀑布流缩略图命中 SW 缓存 ✅（M7.9）

## 3. M8 — 增量扫描 + watchdog + 周期重聚类

**目标**：新加图片自动出现在相册。

### 3.1 子任务

| 任务 ID | 内容 | 依赖 | 状态 |
|---|---|---|---|
| M8-T-1 | `service/file_watcher.py` watchdog → asyncio.Queue | M6-T-5 | ✅ |
| M8-T-2 | APScheduler 周期轮询兜底（每 5 分钟） | M8-T-1 | ✅ |
| M8-T-3 | `worker/cluster_worker.py` 周期重聚类 | M6-T-10 | ✅ |
| M8-T-4 | `worker/cluster_worker.py` 增量触发（≥ N 张脸） | M8-T-3 | ✅ |
| M8-T-5 | HNSW 增量添加 + 持久化频率 | M6-T-7 | ✅ |
| M8-T-6 | 软删除（`source.status='removed'/'missing'`）| M6-T-7 | ✅ |
| M8-T-7 | `api/ready` 队列深度 + worker 状态 | M6-T-1 | ✅ |
| M8-T-8 | SSE 增量事件（new_photo / new_person / merged） | M7-T-1 | ✅ |

### 3.2 验收

- AC-W8：新增一张图，30 秒内出现在聚类结果 ✅
- AC-W8-SSE：watchdog 触发后，`/api/scan/jobs/{id}/events` 流至少发出一个 `new_photo` 事件 ✅
- AC-W8-DELETE：`DELETE /api/photos/{id}` 返回 204；之后该图对应的脸从 `/api/persons` 中消失 ✅

### 3.3 实现要点

- 触发面（**用户锁定决策**）：复用 `ScanService.start(paths=[...], kind="path_only")`，**不**写新的 embedder pipeline。`run_scan` 通过 `(size, mtime)` diff 自然处理 ADD/MOD/UNCHANGED/DEL。
- 双源单汇：watchdog + APScheduler 周期轮询 → 单一消费者 → `ScanService.start`。5 秒 debounce 窗口将 50 个文件的 burst 合并为 1 个 job。
- HNSW 持久化：每次增量聚类后 `add_items + save`；启动时 `load()` → 失败时 `rebuild()`。HNSW 是单任务拥有（cluster worker），避免 hnswlib 的线程安全问题。
- 软删除：**没有 schema migration**。`source.status` 扩展枚举值 `'removed'`（用户驱动）+ 复用已有的 `'missing'`（filesystem 驱动）。`status TEXT NOT NULL` 无 CHECK 约束，所以新值自动生效。
- SSE 通道：复用 `/api/scan/jobs/{id}/events`，通过 `scan-{id}.events.jsonl` sidecar 转发 `new_photo` / `new_person` / `merged` 事件。SSE generator 0.5 秒 poll tail。SPA 的 `usePersonsLiveInvalidator` 在事件触发时 invalidate `persons` query。
- `recluster_threshold` 重命名：原 `auto_recluster_min_new` → `recluster_threshold`（对齐 `core/config.py ClusteringConfig` schema-of-record，默认值 50）。Pydantic `extra='ignore'` 保证旧 TOML 文件兼容（旧值被静默忽略，使用默认值）。

### 3.4 失败模式

| 失败 | 缓解 | 备注 |
|---|---|---|
| watchdog 在 Docker bind mount / NFS 上不触发 | M8-T-2 周期轮询兜底（每 5 分钟） | 单一 source-of-truth |
| APScheduler 与 watchdog 同时触发 | `run_scan` diff 幂等；最坏情况：一次冗余 DB read | 接受 |
| HNSW 写崩溃 | `save()` 是 write-then-rename 原子写；崩溃后 `load()` 仍可读到上次的好文件 | `index_hnsw.py:238` |
| 维度漂移（active pack 切换） | `load()` 抛 `ValueError` → `rebuild()` 从 SQLite 重建 | 慢但安全 |
| 旧 config.toml 仍用 `auto_recluster_min_new` | Pydantic `extra='ignore'` 静默忽略，使用默认值 50 | 文档提示用户改名 |
| `source.status='removed'` 写错值（无 DB CHECK） | `store/index.py _VALID_SOURCE_STATUSES` 常量 + 写点 assert | 类型层防御 |

## 4. M9 — 多目录聚合 + Review UI

**目标**：跨目录同人合并 + review UI。

### 4.1 子任务

| 任务 ID | 内容 | 依赖 |
|---|---|---|
| M9-T-1 | HDBSCAN 全局聚类（跨 scan_paths） | M8-T-3 |
| M9-T-2 | `api/persons/merge` 端点 | M6-T-10 |
| M9-T-3 | `api/persons/{id}` 重命名 | M6-T-10 |
| M9-T-4 | SPA `<ReviewPanel>` 合并 / 重命名 UI（`Dialog` + `DropdownMenu` + `Slider` 调阈值预览） | M9-T-2 |
| M9-T-5 | SPA `/review/pending` 待审聚类 | M9-T-1 |
| M9-T-6 | 跨目录 fixture（AT&T 拆 2 目录）| — |
| M9-T-7 | 跨目录聚类 F1 不降的回归测试 | M9-T-6 |

### 4.3 验收

- AC-W9：跨目录同人合并，B³ F1 不降 ✅

## 5. M10 — 打包 + Docker + 部署文档

**目标**：用户能 `docker run` 起来。

### 5.1 子任务

| 任务 ID | 内容 | 依赖 |
|---|---|---|
| M10-T-1 | Dockerfile 多阶段 | M6-T-16 |
| M10-T-2 | docker-compose.yml（含 volume mount） | M10-T-1 |
| M10-T-3 | 部署文档（`docs/deployment/`） | M10-T-2 |
| M10-T-4 | Caddy / nginx 反代配置示例 | M10-T-2 |
| M10-T-5 | system service 文件（Linux 裸机部署） | M6-T-1 |
| M10-T-6 | Windows 服务脚本 | M6-T-1 |
| M10-T-7 | 资源占用基线测试（CPU/RAM/磁盘） | M10-T-1 |
| M10-T-8 | 启动时间基线（首次 vs 增量） | M10-T-1 |
| M10-T-9 | Beta 用户招募（5–10 人） | — |

### 5.2 验收

- Docker 镜像 < 800 MB
- 启动时间（增量）< 3 秒
- 100k 张照片 CPU 扫描 < 75 分钟 / GPU < 12 分钟

## 6. M11 — v3.0 正式发布

### 6.1 子任务

| 任务 ID | 内容 | 依赖 |
|---|---|---|
| M11-T-1 | 全量回归测试（unit + integration） | M10-T-9 |
| M11-T-2 | 性能调优（如果 M10-T-7 不达标） | M11-T-1 |
| M11-T-3 | CHANGELOG [3.0.0] 段 | — |
| M11-T-4 | GitHub Release + 二进制包 | M11-T-3 |
| M11-T-5 | 文档站（mkdocs）发布 | M11-T-3 |

## 7. 跨里程碑风险

| 风险 | 触发 | 缓解 |
|---|---|---|
| watchdog 在某些文件系统（Docker bind mount）失效 | M8 | 周期轮询兜底 |
| FastAPI 单进程无法吃满 CPU | M6 | `workers` 配置；v4 用 gunicorn + uvicorn workers |
| 大目录（> 1M 张图）一次性扫描 OOM | M6 | 流式 + 批量提交 SQLite |
| HTTP Range 在 nginx 反代下丢失 | M10 | 文档示例 + 配置检查 |
| 前端包体积过大 | M7 | Vite tree-shaking + code-splitting |

## 8. v4+ 路线图（非 v3 范围）

| 主题 | 描述 |
|---|---|
| 多用户 / 多租户 | v3 schema 已预留 user_id 字段 |
| 视频抽帧 | ffmpeg + 关键帧检测 |
| 关系图谱 | 同一图多人 → "社交图" |
| 移动端原生 App | Capacitor / Tauri 包装 SPA |
| 智能标签 | 场景 / 物体识别 |
| 远程后端 | S3 / SMB 扫描源 |
| GPU 集群 | 多 worker 时跨机器 distribute |

## 9. 引用与延伸阅读

- [01 PRD](01-product-requirement.md)
- [02 §栈选型](02-technical-pre-research.md)
- [03 §服务架构](03-architecture-design.md)
- [04 §聚类流水线](04-algorithm-pipeline.md)
- [05 §数据与存储](05-data-and-storage.md)
- 归档：[M5 CLI §里程碑](archive/m5-cli/06-engineering-plan.md) — 历史