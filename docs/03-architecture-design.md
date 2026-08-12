# 03 架构设计：pick-face Web 相册服务（v3.0）

> 文档版本：v3.0 · 2026-08-12
> 范围：服务模块划分、HTTP API 契约、worker 流水线、目录布局
> 关联：[01 PRD](01-product-requirement.md) · [02 栈选型](02-technical-pre-research.md) · [05 数据](05-data-and-storage.md)

## 0. 摘要

v3 在 v2.x 五域子包结构上加一层 **service domain**（`src/pick_face/service/`），不破坏现有 ingest/store/output 边界。

```
浏览器 SPA (React + Vite + TS + shadcn/ui + Tailwind)
   │
   │ HTTP (FastAPI) + SSE
   ▼
┌──────────────────────────────────────────────────────────┐
│              FastAPI app (uvicorn, port 8000)            │
│                                                          │
│   api/        api/             api/                      │
│   ├── persons ──┤              ├── config                │
│   ├── photos ───┤              ├── scan  ──── SSE        │
│   ├── viewer ───┤              ├── health                │
│                                  └────                    │
│                                                          │
│   service/  (新 domain)                                  │
│   ├── config_service   ← 路径白名单 / 配置 CRUD          │
│   ├── scan_service     ← 启动扫描 / 进度                  │
│   ├── person_service   ← 虚拟相册 CRUD + review         │
│   ├── photo_service    ← 缩略图 / 元数据 / 原图流       │
│   └── file_watcher     ← watchdog 适配层                │
│                                                          │
│   worker/  (后台异步任务)                                │
│   ├── scan_worker      ← 扫描 → 检测 → 嵌入             │
│   ├── index_worker     ← HNSW 增量                      │
│   └── cluster_worker   ← HDBSCAN 周期                   │
│                                                          │
│   ingest/  store/  output/  platform/   ← v2.x 算法内核  │
└──────────────────────────────────────────────────────────┘
```

## 1. 模块划分

### 1.1 新增 `service/` 子包

| 文件 | 职责 |
|---|---|
| `service/config_service.py` | 路径白名单校验 + 配置 CRUD（持久化到 `config.toml`） |
| `service/scan_service.py` | 启动扫描任务、进度 SSE、暂停/恢复 |
| `service/person_service.py` | 虚拟相册 list/rename/merge/delete（薄包装 `store/review.py`） |
| `service/photo_service.py` | 缩略图、原图流（Range）、元数据查询 |
| `service/file_watcher.py` | watchdog → asyncio.Queue 适配 |

### 1.2 新增 `api/` 子包

| 文件 | 路由前缀 | 职责 |
|---|---|---|
| `api/config.py` | `/api/config` | 路径 CRUD、健康检查 |
| `api/scan.py` | `/api/scan` | 启动扫描、查询状态、SSE 进度 |
| `api/persons.py` | `/api/persons` | 虚拟相册 list、详情 |
| `api/photos.py` | `/api/photos` | 缩略图、原图流、EXIF |
| `api/review.py` | `/api/review` | rename/merge/delete |
| `api/health.py` | `/api/health` | 服务健康 |

### 1.3 新增 `worker/` 子包

| 文件 | 职责 |
|---|---|
| `worker/scan_worker.py` | 队列消费者：调用 detector + embedder，写入 SQLite + HNSW |
| `worker/index_worker.py` | HNSW 增量添加 |
| `worker/cluster_worker.py` | 周期任务：新 embedding 累积到 N 张时触发 HDBSCAN |

### 1.4 复用 v2.x

| v2.x 模块 | v3 复用方式 |
|---|---|
| `ingest/scanner.py` | `scan_worker` 直接调用 |
| `ingest/detector.py` | 同上 |
| `ingest/embedder.py` | 同上 |
| `ingest/cluster.py` | `cluster_worker` 触发 |
| `ingest/align.py` | 直接调用 |
| `store/index.py` + `store/index_hnsw.py` | worker 增量写入 |
| `store/review.py` | `person_service` 调用 |
| `output/mirrors.py` | `photo_service` 用于原图路径映射 |
| `output/reporter.py` | 复用统计逻辑 |
| `platform/runtime.py` | `scan_worker` 启动 detector/embedder session |
| `platform/packs/*` | 完全不动 |

### 1.5 模块依赖图

```
api/  ──▶  service/  ──▶  ingest/  ──▶  core/
              │            │
              │            ├─▶ store/
              │            │
              │            └─▶ platform/
              │
              └─▶ worker/  ──▶ ingest/ + store/ + platform/

output/    ← 所有 domain 可调用（路径映射、报表）
```

**DependencyRule 不变**：service 依赖 ingest/store/output/platform；worker 依赖 ingest/store/platform。service 和 worker 之间是事件驱动（asyncio.Queue），不直接 import。

## 2. HTTP API 契约（v3.0）

所有 endpoint 返回 JSON；FastAPI 自动 OpenAPI 文档位于 `/api/docs`。

### 2.1 配置 (`/api/config`)

```
GET  /api/config                  # 当前配置（白名单路径、模型 pack、merge_threshold）
POST /api/config/paths            # 添加扫描路径 { path: str }
                                 #   400 INVALID_PATH / NOT_WHITELISTED / NOT_FOUND
DELETE /api/config/paths/{id}     # 移除路径
GET  /api/config/paths            # 列出已配置路径
```

### 2.2 扫描 (`/api/scan`)

```
POST /api/scan/start              # 启动扫描 { paths?: [str], full?: bool }
                                 #   202 ACCEPTED；扫描 id
POST /api/scan/{id}/pause
POST /api/scan/{id}/resume
POST /api/scan/{id}/cancel
GET  /api/scan/active             # 当前活动扫描
GET  /api/scan/{id}               # 状态
GET  /api/scan/{id}/progress      # SSE: {processed, total, faces, errors, eta_sec}
```

SSE 流格式（`text/event-stream`）：

```
event: progress
data: {"processed": 4321, "total": 10000, "faces": 234, "errors": 3, "eta_sec": 180}

event: stage
data: {"stage": "detecting", "scan_id": "abc"}

event: done
data: {"scan_id": "abc", "result": "ok"}
```

### 2.3 虚拟相册 (`/api/persons`)

```
GET    /api/persons?cursor=&limit=50        # 列表（每项含 cover_url）
GET    /api/persons/{id}                    # 详情：name, photo_count, sources, cover_face_id
GET    /api/persons/{id}/cover              # ⭐ 虚拟相册封面（112×112 人脸 chip）
GET    /api/persons/{id}/photos?cursor=&limit=200&sort=mtime_desc
PATCH  /api/persons/{id}                    # 重命名 { name: str }
POST   /api/persons/merge                   # { source_ids: [id], target_id: id }
DELETE /api/persons/{id}                    # 软删除（mark deleted）
```

**封面契约**（关键）：
- `/api/persons/{id}/cover` 返回的是 **人脸 chip（112×112 对齐后）**，不是原图缩略图
- 数据源：`persons.thumbnail_face_id` → `faces.chip_path`
- 选脸策略：HDBSCAN 输出 `cluster_confidence` 最高的；同分时挑 `det_score` 最高的；再同时挑 `bbox_w * bbox_h` 最大的（更清晰）
- 用户在 `/persons` 列表看到的"这是谁"，**就是这张脸的清晰正面照**
- 缓存：服务端可加 `ETag: "<face_id>-<mtime>"`（M7）

### 2.4 图片 (`/api/photos`)

```
GET  /api/photos/{id}                     # 流式原图（支持 HTTP Range，不复制）
GET  /api/photos/{id}/thumbnail           # 缩略图（JPEG 256×256）
GET  /api/photos/{id}/metadata            # EXIF + 路径 + mtime + 该脸所在 person
GET  /api/photos/{id}/faces               # 该图所有人脸（bbox + 哪个 person）
```

**安全契约**：`/api/photos/{id}` 永远只返回**已记录到数据库**的图片。  
绝不能直接 `FileResponse(request.query_params["path"])` —— 那会让攻击者用 `?path=../../etc/passwd` 读到任何文件。

### 2.5 Review (`/api/review`)

```
GET  /api/review/pending?limit=20        # 待人工 review（低置信聚类）
POST /api/review/{face_id}              # { action: "accept" | "reject" | "merge_with", target?: id }
```

### 2.6 健康 (`/api/health`)

```
GET  /api/health
→ {"status": "ok", "packs": [...], "workers": {...}, "queue_depth": N}
```

## 3. 数据流（端到端）

### 3.1 启动时

```
1. uvicorn 启动 FastAPI app
2. app.on_event("startup")
   ├── 加载 .pick-face/config.toml（白名单路径）
   ├── 启动 N 个 scan_worker（asyncio task）
   ├── 启动 cluster_worker（APScheduler）
   ├── 启动 file_watcher（watchdog）
   └── 注册 SSE 广播
```

### 3.2 用户添加路径后

```
UI: POST /api/config/paths { path: "/mnt/photos/2024" }
   │
   ▼ service/config_service.add(path)
   │  ├─ Path.resolve() + 白名单校验
   │  ├─ os.access(path, R_OK) 检查
   │  └─ 持久化到 config.toml
   ▼ service/file_watcher.watch(path)
      └─ watchdog.Observer.schedule(handler, path)
   ▼ (可选) service/scan_service.start(path)
      └─ asyncio.Queue.put(scan_task)
            ▼ scan_worker
               ├─ ingest/scanner.iter(path)
               ├─ for each image: detector + embedder
               ├─ 写入 SQLite (face, embedding) + HNSW
               └─ SSE 广播 progress
```

### 3.3 浏览相册

```
UI: GET /api/persons
   ▼ service/person_service.list()
      └─ store/review.list_persons() (复用 v2.x)
   ← JSON: [{id, name, photo_count, thumbnail_url}]

UI: GET /api/persons/{id}/photos
   ▼ service/person_service.photos(id)
      └─ store/index.faces_by_person(id)
   ← JSON: [{photo_id, mtime, thumbnail_url, faces: [...]}]

UI: GET /api/photos/{id}
   ▼ service/photo_service.stream(id)
      ├─ store/index.photo_path(id) → /mnt/photos/.../IMG_001.jpg
      ├─ FastAPI FileResponse(path, headers={...})  # 不复制
      └─ Starlette Range middleware 自动处理 If-Range
```

## 4. 安全设计

### 4.1 路径白名单（US-1 AC-2）

```python
ALLOWED_ROOTS = [Path("/mnt/photos").resolve()]

def validate_scan_path(p: str) -> Path:
    resolved = Path(p).resolve()
    if not any(_is_subpath(resolved, r) for r in ALLOWED_ROOTS):
        raise InvalidPathError(f"{p} not under any allowed root")
    if not resolved.exists() or not resolved.is_dir():
        raise NotFoundError(f"{p} not a directory")
    return resolved

def _is_subpath(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False
```

**v3 仅支持运维员配置的根**（如 `/mnt/photos`）。不允许任意路径。

### 4.2 原图流（US-4 AC-7）

**绝不能**直接响应任意 path。响应流程：

```
photo_id → store.index.photo_path(photo_id) → 已校验的 Path → FileResponse
```

`photo_path` 返回的 Path 必须**只在扫描时入库** —— 攻击者无机会注入。

### 4.3 鉴权（v3 默认无；v4 才有）

- v3 默认**单用户自托管**：bind 到 `127.0.0.1` 或 LAN
- 反向代理（nginx / caddy）负责 HTTPS + Basic Auth / OIDC
- FastAPI 自身不实现用户体系

### 4.4 速率限制

- `/api/scan/start`：每小时 ≤ 10 次
- `/api/photos/{id}`：单 IP ≤ 100 req/s

## 5. 目录布局

**所有 pick-face 运行产生的文件全部归到一个独立的"应用根目录"下：**

```
~/.pick-face/                              # 应用根目录（= PICK_FACE_HOME 的默认）
├── config/
│   └── config.toml                        # 白名单路径、模型 pack、阈值
├── data/                                  # 数据（备份这一项 = 备份整个相册）
│   ├── index.sqlite                       # 主数据库
│   ├── index.sqlite-wal                   # WAL 日志
│   ├── index.hnsw                         # HNSW 持久化
│   ├── chips/                             # 人脸 chip（112×112 对齐后）—— 虚拟相册封面数据源
│   │   └── ab/cd/<face_id>.jpg
│   ├── thumbnails/                        # 原图缩略图（256×256 JPEG）—— 瀑布流显示
│   │   └── ab/cd/<xxh3>.jpg
│   ├── covers/                            # 虚拟相册封面（硬链接 / 缓存 chip）
│   │   └── person_<id>.jpg
│   ├── jobs/                              # 扫描任务状态（崩溃恢复 / 审计）
│   │   └── scan-<uuid>.json
│   └── logs/
│       └── pick-face.log
└── cache/                                 # 可丢弃的缓存
    ├── models/                            # 模型权重（SHA256 pin，可重下）
    │   ├── yunet-sface/
    │   └── yunet-arcface/
    └── tmp/                               # 解码 / 缩略图临时目录
```

**路径解析优先级**：
1. 环境变量 `PICK_FACE_HOME`（Docker / 多实例 / 调试用）
2. 配置文件 `[server] data_dir`
3. 默认 `~/.pick-face/`

**关键点**：

1. **数据目录与扫描根目录解耦**——用户在 `/mnt/photos` 加新文件，服务把索引写入 `~/.pick-face/data/`，原图**不被复制**
2. **单一命名空间 `~/.pick-face/`**——配置 / 数据 / 模型都在里面，卸载 `rm -rf ~/.pick-face` 即可清干净
3. **Docker / 裸机路径一致**——容器内整个 `/data` 卷就是宿主的 `~/.pick-face`；多实例用 `PICK_FACE_HOME=/srv/pick-face-2` 隔离

完整 schema 与备份策略见 [docs/05](05-data-and-storage.md)。

## 6. 启动 / 配置 / 工作流

### 6.1 CLI 入口（v3 新增）

```bash
pick-face-web init                          # 交互式初始化（生成 config.toml）
pick-face-web serve --host 0.0.0.0 --port 8000
pick-face-web scan --path /mnt/photos/2024  # CLI 模式扫描（与 v2.x 兼容）
pick-face-web doctor                        # 健康诊断（沿用 v2.x）
```

### 6.2 配置文件（`~/.config/pick-face/config.toml`）

```toml
[server]
host = "0.0.0.0"
port = 8000
workers = 2                                  # asyncio worker 数
data_dir = "~/.pick-face"                    # 应用根目录（默认；PICK_FACE_HOME 优先）

[scan]
allowed_roots = ["/mnt/photos", "/srv/photos"]
default_pack = "yunet-sface"                 # 或 "yunet-arcface"
incremental_interval_sec = 300               # watchdog 兜底轮询周期

[index]
db_path = "~/.pick-face/data/index.sqlite"
hnsw_path = "~/.pick-face/data/index.hnsw"
chips_dir = "~/.pick-face/data/chips"
thumbnails_dir = "~/.pick-face/data/thumbnails"
covers_dir = "~/.pick-face/data/covers"
models_dir = "~/.pick-face/cache/models"

[clustering]
merge_threshold = 0.0                        # SFace 128-D
                                          # 或 0.55（ArcFace 512-D）
auto_recluster_min_new = 500                 # 新增 N 张脸自动重聚类

[commercial]
accept_noncommercial_model_license = false    # AC-9 fail-safe
```

### 6.3 部署工作流

```bash
# Docker（推荐）
docker run -d \
  -p 8000:8000 \
  -v /mnt/photos:/mnt/photos:ro \
  -v ~/.pick-face:/data \
  -e PICK_FACE_HOME=/data \
  pick-face/web:latest

# 多实例（同一台机器跑两份）
docker run -d -p 8000:8000 \
  -v ~/.pick-face:/data \
  -e PICK_FACE_HOME=/data \
  pick-face/web:latest               # 实例 1

docker run -d -p 8001:8000 \
  -v ~/.pick-face-2:/data \
  -e PICK_FACE_HOME=/data \
  pick-face/web:latest               # 实例 2（独立 ~/.pick-face-2）

# 裸机
export PICK_FACE_HOME=~/.pick-face      # 可选；不设也走默认
uv venv && uv pip install -e ".[web]"
pick-face-web init                          # 交互式
pick-face-web serve --host 0.0.0.0 --port 8000
```

## 7. 前端架构（SPA）

```
src/web/                                # Vite + React + TS + shadcn/ui
├── main.tsx                            # React 入口，挂载 <App/>
├── App.tsx                             # 路由 + QueryClientProvider + ThemeProvider
├── routes/
│   ├── Home.tsx                        # / 入口
│   ├── Persons.tsx                     # /persons 虚拟相册列表
│   ├── PersonDetail.tsx                # /persons/:id 瀑布流
│   ├── PhotoViewer.tsx                 # /persons/:id/photos/:photoId 查看器
│   └── Settings.tsx                    # /settings 路径配置
├── components/
│   ├── ui/                             # shadcn/ui 生成（复制源码，可改）
│   │   ├── button.tsx
│   │   ├── dialog.tsx                  # Radix Dialog
│   │   ├── dropdown-menu.tsx           # Radix DropdownMenu
│   │   ├── tabs.tsx                    # Radix Tabs
│   │   ├── toast.tsx                   # Radix Toast + sonner
│   │   ├── slider.tsx                  # Radix Slider
│   │   └── ...                         # 见 §7.2
│   ├── PhotoGrid.tsx                   # 瀑布流（react-photo-album）
│   ├── FaceViewer.tsx                  # 自研查看器（@use-gesture + framer-motion）
│   ├── FaceOverlay.tsx                 # 在图上画 bbox
│   ├── ScanProgressToast.tsx           # SSE 订阅（Radix Toast）
│   ├── PathManagerDialog.tsx           # 添加/删除扫描路径（Radix Dialog）
│   ├── ModelPackSelector.tsx           # 模型包切换（Radix DropdownMenu）
│   └── ThemeToggle.tsx                 # 明暗主题切换
├── api/
│   ├── schema.ts                       # openapi-typescript 生成（不要手改）
│   ├── client.ts                       # 基于 schema.ts 的 fetch 封装
│   └── hooks.ts                        # TanStack Query 包装（usePersons/usePhotos/...）
├── lib/
│   ├── gesture.ts                      # @use-gesture 封装
│   ├── sse.ts                          # EventSource hook
│   ├── utils.ts                        # cn() 等 shadcn/ui 公用工具
│   └── theme.tsx                       # ThemeProvider（class=dark 切换）
└── styles/
    └── globals.css                     # Tailwind directives + CSS 变量（HSL token）
```

**核心约定**：
- 所有按钮 / 弹窗 / 下拉 / Tab / Slider / Toast **必须用** shadcn/ui 的 `components/ui/*` —— 不允许临时 div + Tailwind 复刻（无障碍/键盘支持会丢）
- 新增 shadcn/ui 组件：`pnpm dlx shadcn@latest add <component>`（写入 `src/web/components/ui/`）
- 颜色 token（`--background` / `--foreground` / `--primary` / `--muted` ...）走 CSS 变量，**不**直接用 Tailwind class 硬编码 `bg-slate-900`

### 7.1 关键依赖

| 依赖 | 用途 |
|---|---|
| `react` / `react-dom` | UI 框架 |
| `typescript` / `vite` | 类型 + 构建 |
| `tailwindcss` / `postcss` / `autoprefixer` | utility CSS |
| `class-variance-authority` / `clsx` / `tailwind-merge` | shadcn/ui 配套（`cn()`） |
| `@radix-ui/react-*` | shadcn/ui 行为原语 |
| `lucide-react` | 图标 |
| `react-hook-form` / `@hookform/resolvers` / `zod` | 表单 + 校验（与 Pydantic schema 互译） |
| `@tanstack/react-query` | 服务端状态缓存 |
| `zustand` | 本地 UI 状态（查看器缩放级别 / 全屏 / 当前 photoId） |
| `react-photo-album` | 瀑布流 |
| `@use-gesture/react` | 手势 |
| `framer-motion` | 查看器过渡 |
| `sonner` | Toast（shadcn/ui 推荐） |
| `openapi-typescript` | 从 FastAPI OpenAPI 生成 TS 类型 |

构建产物：Vite 输出到 `src/pick_face/web/static/`，FastAPI 用 `StaticFiles` mount 到 `/`。

### 7.2 计划引入的 shadcn/ui 组件清单（M6-M9 范围）

| 组件 | 用在哪 |
|---|---|
| `Button` | 全局 |
| `Dialog` | 添加扫描路径 / 模型包详情 / EXIF 详情 |
| `DropdownMenu` | 模型包切换 / 主题切换 / 单张照片"打开人/原图/导出"菜单 |
| `Tabs` | `/settings` 分页（路径 / 模型 / 阈值） |
| `Toast` (sonner) | 扫描进度 / 保存成功 / 错误 |
| `Slider` | 查看器缩放、merge_threshold 调节 |
| `Switch` | 启用/禁用扫描路径 |
| `Tooltip` | 人脸 bbox 悬停 |
| `Sheet` | 查看器右侧 EXIF 抽屉 |
| `Command` (cmdk) | 全局搜索（按人名 / 路径） |
| `Skeleton` | 列表加载占位 |
| `Badge` | 标签（NC-research 警告 / 缩略图分辨率） |
| `Progress` | 扫描进度条（SSE 推 percent） |

### 7.3 主题与暗色模式

`tailwind.config.ts` 配置 `darkMode: 'class'`。`<html>` 上的 `dark` class 由 `ThemeToggle` 切换。CSS 变量定义在 `src/web/styles/globals.css`：

```css
:root {
  --background: 0 0% 100%;
  --foreground: 240 10% 4%;
  --primary: 240 6% 10%;
  ...
}
.dark {
  --background: 240 10% 4%;
  --foreground: 0 0% 98%;
  ...
}
```

shadcn/ui 组件**全部**用 `bg-background text-foreground` 这类 token class，不写死颜色——换肤/白标靠改 CSS 变量即可。

## 8. 关键架构决策记录

| ADR | 决策 | 替代 |
|---|---|---|
| ADR-1 | FastAPI 单进程 + 异步 task | 多 worker (gunicorn) |
| ADR-2 | SQLite WAL | Postgres |
| ADR-3 | asyncio.Queue | Redis Stream |
| ADR-4 | watchdog + 周期兜底 | 仅 watchdog / 仅轮询 |
| ADR-5 | 自研 React 查看器 + shadcn/ui 基础组件 | PhotoSwipe / Lightbox / MUI |
| ADR-6 | 数据目录 vs 扫描根目录解耦 | 数据目录与扫描根目录合并 |
| ADR-7 | v3 无用户体系（仅运维配置） | 内置 Auth |
| ADR-8 | 缩略图持久化到 `.pick-face/thumbnails/` | 数据库存二进制 |
| ADR-9 | shadcn/ui（复制源码）+ Tailwind + Radix | MUI / Chakra / Ant Design |

## 9. 引用与延伸阅读

- [01 PRD](01-product-requirement.md)
- [02 §栈选型](02-technical-pre-research.md)
- [04 §聚类流水线](04-algorithm-pipeline.md)
- [05 §数据与存储](05-data-and-storage.md)
- [06 §M6+ 里程碑](06-engineering-plan.md)
- 归档：[M5 CLI §架构](archive/m5-cli/03-architecture-design.md)