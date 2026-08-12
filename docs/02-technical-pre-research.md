# 02 技术预研：栈选型与库对比（v3.0）

> 文档版本：v3.0 · 2026-08-12
> 范围：Web 相册服务的栈选型、对比矩阵、决策
> 关联：[01 PRD](01-product-requirement.md) · [03 架构](03-architecture-design.md)

## 0. 摘要

v3 在 v2.x 算法内核（已稳定）之上加一层 **Web 服务** + **SPA**。核心选型：

| 维度 | 选型 | 替代 | 决策依据 |
|---|---|---|---|
| **HTTP 框架** | FastAPI | Flask / Django / Starlette | 异步 / 自动 OpenAPI / Pydantic 类型 |
| **ASGI 服务器** | Uvicorn | Hypercorn | FastAPI 官方推荐 |
| **后台任务队列** | APScheduler + asyncio.Queue | Celery / RQ / Dramatiq | 单机部署无需 Redis；进程内即可 |
| **数据库** | SQLite (WAL 模式) | Postgres / DuckDB | 单用户自托管；WAL 足够 100k 张图 |
| **向量索引** | hnswlib | FAISS / Qdrant / Milvus | 已在 v2.x 用；持久化 + 增量添加 |
| **文件监听** | watchdog (跨平台) | inotify (Linux-only) / 周期轮询 | watchdog 封装 inotify/FSEvents/Windows |
| **缩略图** | Pillow + libvips (可选) | ImageMagick | Pillow 已依赖；libvips 仅在性能瓶颈时 |
| **原图流式返回** | FastAPI FileResponse + Range | 自实现 | Starlette 自带 Range 支持 |
| **前端框架** | React + Vite + TypeScript | Vue 3 / Svelte / Solid | 生态 / 查看器组件丰富 |
| **UI 组件库** | **shadcn/ui**（基于 Radix UI + Tailwind）| MUI / Chakra / Ant Design | 可复制可定制、零运行时、Radix 无障碍 |
| **样式系统** | Tailwind CSS v3 | MUI / Chakra | shadcn/ui 的依赖；utility-first 与查看器状态联动直接 |
| **图标** | lucide-react | heroicons / @radix-ui/react-icons | shadcn/ui 默认配套 |
| **表单** | react-hook-form + zod | Formik | 与 shadcn/ui 表单示例一致；zod 与 Pydantic 类型互译 |
| **查看器组件** | react-photo-album + 自研手势 | PhotoSwipe / react-image-lightbox | 灵活度；手势可控 |
| **状态管理** | TanStack Query + Zustand | Redux / Jotai | 服务端状态 + 少量本地状态 |
| **实时通信** | SSE (Server-Sent Events) | WebSocket / 轮询 | 扫描进度单向推送，SSE 最简 |
| **包管理器** | uv | pip-tools / poetry | 已确立（项目约束） |
| **Python 版本** | 3.10–3.12 | 3.13 | 与 v2.x 一致 |
| **打包** | Docker (multi-stage) + 裸机 | 仅 Docker | 两种部署都要 |

## 1. HTTP 框架对比

### 1.1 候选

| 框架 | 异步 | 类型提示 | OpenAPI 自动生成 | 生态 |
|---|---|---|---|---|
| **FastAPI** | ✅ | ✅ Pydantic | ✅ | 大；与 Starlette 100% 兼容 |
| Flask | ❌（默认同步） | 手动 | ❌（要 flask-smorest） | 最大 |
| Django | ❌（默认同步；ASGI 模式可用） | 手动 | ❌（drf-spectacular） | 最大；但重 |
| Starlette | ✅ | ✅ | ❌（要自己装 OpenAPI） | 中 |

### 1.2 决策：**FastAPI**

理由：
1. **异步优先** — `/api/scan/start` 是长任务，HTTP 异步让 worker 不阻塞主线程
2. **OpenAPI 自动** — 前端可以直接 `npm run gen-api` 从 OpenAPI 生成 TypeScript client
3. **Pydantic v2** — 数据校验 / 序列化已在 v2.x core 用过（`PickFaceConfig`），复用心智
4. **依赖注入** — `Depends(get_db)`、`Depends(get_runner)` 让测试友好

## 2. 数据库对比

### 1.1 候选

| 数据库 | 单机写 | 读并发 | 部署复杂度 | 适合规模 |
|---|---|---|---|---|
| **SQLite (WAL)** | ~100k/s | 高 | 零（一个文件） | 100k 张图内 |
| PostgreSQL | 高 | 极高 | 中（要起服务） | 100k+ |
| DuckDB | 极高（OLAP） | 高 | 零（嵌入式） | 1M+ 但写弱 |

### 2.2 决策：**SQLite（WAL 模式）**

理由：
1. 单用户自托管场景，**无并发写**
2. v2.x 已用 SQLite（`store/index.py`），零迁移成本
3. WAL 模式允许一边扫描一边 HTTP 查询不阻塞
4. 备份 = `cp .pick-face/index.sqlite` 即可

**多用户场景留给 v4**：v3 文档明确不做多租户；万一用户需要，**只换数据库驱动**，业务层不动（`store/*.py` 已经 Pydantic 化）。

## 3. 后台任务队列对比

### 3.1 候选

| 方案 | 需要外部依赖 | 适合规模 | 复杂度 |
|---|---|---|---|
| **asyncio.Queue + 后台 task** | 否 | 单进程 | 低 |
| APScheduler | 否 | 单进程定时任务 | 低 |
| Celery | Redis/RabbitMQ | 分布式 | 高 |
| RQ | Redis | 分布式 | 中 |
| Dramatiq | Redis/RabbitMQ | 分布式 | 中 |

### 3.2 决策：**asyncio.Queue + APScheduler**

理由：
1. 单机部署，**无需 Redis**
2. FastAPI 的 `@app.on_event("startup")` 起 N 个 worker，监听同一 asyncio.Queue
3. APScheduler 负责**周期任务**（每 5 分钟扫一次新文件）+ **延迟任务**（UI 点"立即扫描"）
4. 进度通过 **SSE**（`GET /api/scan/progress`）推给浏览器

## 4. 文件监听对比

### 4.1 候选

| 方案 | 平台 | 实时性 | 复杂度 |
|---|---|---|---|
| **watchdog** | 跨平台（inotify/FSEvents/Windows） | 实时 | 中 |
| 周期轮询（`os.scandir` 每 N 秒） | 跨平台 | N 秒延迟 | 低 |
| Linux inotify 直接调用 | Linux-only | 实时 | 中 |

### 4.2 决策：**watchdog + 周期轮询兜底**

理由：
1. watchdog 是事实标准，跨平台一致
2. 周期轮询作为**兜底**：watchdog 失败 / 文件系统不支持 inotify 时仍能跑
3. watchdog 事件进入 asyncio.Queue，worker 异步消费

## 5. 向量索引

### 5.1 决策：**复用 v2.x 的 hnswlib**

理由：
1. v2.x 已经验证 100k 张脸的性能（query < 5ms / p99）
2. 持久化文件 `index.bin` 直接复用
3. 不引入新依赖

**规模天花板**：hnswlib 单机能撑 ~10M 向量（@32-D），远超单用户场景。

## 6. 前端栈

### 6.1 React vs Vue vs Svelte

| 框架 | 体积 | 学习曲线 | 查看器组件 |
|---|---|---|---|
| **React** | 中 | 中 | 最多（react-photo-album、photoswipe-react 等） |
| Vue 3 | 小 | 平缓 | 中 |
| Svelte 5 | 最小 | 平缓 | 少 |

**决策：React + Vite + TypeScript + shadcn/ui + Tailwind CSS**
- React + Vite + TS：生态最广；OpenAPI → TypeScript 自动生成（`openapi-typescript`）
- **shadcn/ui**：Radix UI 提供无障碍 + 行为正确（Dialog / DropdownMenu / Toast / Tabs 都已做好 WAI-ARIA），Tailwind 提供可定制的 token 体系。**不是 npm 依赖**——`npx shadcn@latest add button` 把组件源代码复制进 `src/web/components/ui/`，可以随手改样式、改逻辑、改 props，不会被依赖锁死
- 查看器组件可自研手势层（pinch / swipe），复用 react-photo-album 的瀑布流

**为什么不用 MUI / Chakra**
- MUI：Material Design 强风格，与"自托管相册"调性不合；runtime CSS-in-JS 增加 bundle
- Chakra：API 好但组件体积大；自定义主题要走 token；不如 shadcn/ui 的"复制即拥有"
- Ant Design：偏后台管理风格，相册 UI 太重

**为什么不用纯 Radix 不带 shadcn/ui**
- Radix 本身只暴露无样式行为原语，每个组件都要从零写 Tailwind class；shadcn/ui 已经把这些写好的 class 模板随源码复制给你，省事但不失控制

### 6.1.5 主题与暗色模式

shadcn/ui + Tailwind 内建暗色模式支持，通过 `darkMode: 'class'` 切换。v3 默认跟随系统 `prefers-color-scheme`，UI 上提供手动切换（Radix DropdownMenu）。颜色 token 全部走 CSS 变量（`--background` / `--foreground` / `--primary` 等），方便后期白标/换肤。

### 6.2 查看器交互设计

参考 Apple Photos / Google Photos / Immich：

- 桌面：← / → / Space、滚轮缩放、双击切换 100%↔适应屏幕
- 移动：tap 切 UI、单指 swipe 切图、双指 pinch 缩放、双击放大
- 全屏：F 键切换；Esc 退出
- 信息层：右下角抽屉显示 EXIF / 原图路径 / 该人所有位置

### 6.3 实现选择：**自研 React 查看器 + shadcn/ui 基础组件**

- `react-photo-album` 处理瀑布流布局（缩略图网格）
- 自研 `<FaceViewer>` 组件处理查看器
  - 用 `useGesture`（@use-gesture/react）处理手势
  - 用 `framer-motion` 做平滑过渡
- shadcn/ui 提供的 `<Button>` `<Dialog>` `<DropdownMenu>` `<Tabs>` `<Toast>` `<Slider>` 直接用于：路径配置弹窗、模型包切换菜单、扫描进度 Toast、缩放 Slider 等
- 复用 v2.x 的 `output/mirrors.py` 路径映射逻辑

## 7. 实时通信

### 7.1 SSE vs WebSocket vs Polling

| 方案 | 适合 | 复杂度 |
|---|---|---|
| **SSE** | 服务端单向推（扫描进度） | 低 |
| WebSocket | 双向 | 高 |
| 轮询 | 简单状态查询 | 中 |

**决策：SSE**
- 扫描进度是**单向推**（服务端 → 浏览器）
- SSE 用 `EventSource` API 浏览器原生支持
- FastAPI `StreamingResponse` 直接生成 SSE 流

## 8. 缩略图生成

### 8.1 候选

| 方案 | 速度 | 质量 | 依赖 |
|---|---|---|---|
| **Pillow** | 中 | 好 | 已依赖 |
| libvips (pyvips) | 快 5-10× | 极好 | 系统包；多阶段 Docker |
| ImageMagick | 中 | 好 | 系统包 |

### 8.2 决策：**Pillow 优先，libvips 可选**

理由：
1. v3 首版用 Pillow，零新依赖
2. 缩略图生成在 worker（异步），性能可接受
3. 如果用户报告"扫 1 万张要 10 分钟"，再加 libvips

## 9. 部署形态

### 9.1 Docker（推荐）

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y libgl1 libglib2.0-0
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src ./src
EXPOSE 8000
CMD ["uv", "run", "pick-face-web", "serve", "--host", "0.0.0.0", "--port", "8000"]
```

### 9.2 裸机

```bash
uv venv
uv pip install -e ".[web]"
pick-face-web serve --host 0.0.0.0 --port 8000
```

### 9.3 单进程 vs worker 进程

**v3 决策：单进程 + 异步任务**
- FastAPI 单进程内起 N 个 worker task（默认 N=2，可配）
- 扫描 / 索引 / 聚类 都在同一 asyncio 事件循环
- 监控：`/api/health` 返回 worker 状态

**v4 多机扩展**：如需分布式，把 asyncio.Queue 换成 Redis Stream，业务层不动。

## 10. 库版本约束（pyproject.toml 草案）

```toml
[project]
dependencies = [
    # ... v2.x 全部
    "fastapi>=0.110,<1",
    "uvicorn[standard]>=0.27,<1",
    "python-multipart>=0.0.9",     # file upload
    "watchdog>=4,<7",              # file system events
    "apscheduler>=3.10,<4",        # periodic scans
    "pyvips>=2.2,<3 ; sys_platform != 'win32'",  # optional fast thumbs
]
```

[project.optional-dependencies]
web = ["fastapi>=0.110", "uvicorn[standard]>=0.27", "watchdog>=4,<7", "apscheduler>=3.10,<4"]
web-frontend = ["pnpm>=8"]  # 仅开发者本地用
docker = ["gunicorn>=21"]  # 反向代理用

## 11. 决策汇总

| 决策 | 选型 | 推翻成本 |
|---|---|---|
| Web 框架 | FastAPI | 低（业务在 service 层） |
| DB | SQLite WAL | 低（业务在 store 层） |
| 后台任务 | asyncio.Queue + APScheduler | 低 |
| 文件监听 | watchdog | 低 |
| 前端 | React + Vite + TypeScript + shadcn/ui + Tailwind | 中（要重写组件） |
| 查看器 | 自研 React + @use-gesture + framer-motion | 中 |
| 实时通信 | SSE | 低 |
| 部署 | Docker + 裸机都支持 | 极低 |

## 12. 引用与延伸阅读

- [03 §服务架构](03-architecture-design.md)
- [04 §聚类流水线](04-algorithm-pipeline.md)
- [06 §M6+ 里程碑](06-engineering-plan.md)
- 归档：[M5 CLI §栈选型](archive/m5-cli/02-technical-pre-research.md)