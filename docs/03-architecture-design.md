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

| 文件 | 职责 | M6 状态 |
|---|---|---|
| `service/paths.py` | `AppLayout` + `~/.pick-face/` 解析 + 3-tier 目录树 | ✅ 已实现 |
| `service/config_service.py` | 路径白名单校验 + 配置 CRUD（持久化到 `config.toml`） | ✅ 已实现 |
| `service/scan_service.py` | JSON-backed scan-job 状态机（`QUEUED/RUNNING/DONE/FAILED/CANCELLED`） | ✅ 已实现 |
| `service/person_service.py` | 虚拟相册 list/count/detail/photos/cover | ✅ 已实现（薄包装 `store/index.py` 查询） |
| `service/photo_service.py` | 缩略图生成 + 原图 Range 流 + 元数据查询 + 白名单二次校验 | ✅ 已实现 |
| `service/file_watcher.py` | watchdog → asyncio.Queue 适配 | ⏳ M8（轮询占位） |

### 1.2 新增 `api/` 子包

| 文件 | 路由前缀 | 职责 | M6 状态 |
|---|---|---|---|
| `api/config.py` | `/api/config` | 路径 CRUD、健康检查 | ✅ 已实现 |
| `api/scan.py` | `/api/scan` | 启动扫描、查询状态、SSE 进度 | ✅ 已实现（最小集） |
| `api/persons.py` | `/api/persons` | 虚拟相册 list、详情 | ✅ 已实现（list / count / detail / photos / cover） |
| `api/photos.py` | `/api/photos` | 缩略图、原图流、metadata | ✅ 已实现（`/{id}` Range + `/{id}/thumb` + `/{id}/meta` M7.5 扩展为含 bbox + 人脸列表） |
| `api/review.py` | `/api/review` | rename/merge/delete | ⏳ M9 |
| `api/health.py` | `/api/health` + `/api/ready` | 服务健康 | ✅ 已实现 |

### 1.3 新增 `worker/` 子包

| 文件 | 职责 | M6 状态 |
|---|---|---|
| `worker/scan_worker.py` | 队列消费者：调用 detector + embedder，写入 SQLite + HNSW | ✅ 已实现（in-process via `run_scan()` coroutine） |
| `worker/index_worker.py` | HNSW 增量添加 | ⏳ M8（scan_worker 现写 HNSW 同步） |
| `worker/cluster_worker.py` | 周期任务：新 embedding 累积到 N 张时触发 HDBSCAN | ⏳ M8（扫描时同步聚类） |

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

> **M6 范围**：本节列出的 endpoint 是 **v3.0 完整契约**。M6 已实现的用 ✅
> 标注；标记 ⏳ 的属于后续里程碑（M7 SPA / M8 多进程 / M9 review）。
> 前端开发时按本节契约实现 UI，后端未实现的 endpoint 在 SPA 里用占位
> 组件（"feature coming in M9"）+ 503 graceful fallback。

### 2.1 配置 (`/api/config`)

```
GET  /api/config                  # 当前配置（白名单路径、模型 pack、merge_threshold）  ⏳ M7
POST /api/config/paths            # 添加扫描路径 { path: str }                       ✅ M6
                                 #   400 INVALID_PATH / NOT_A_DIRECTORY
                                 #   403 PATH_TRAVERSAL / NOT_READABLE / DUPLICATE
                                 #   404 NOT_FOUND
DELETE /api/config/paths/{id}     # 移除路径                                         ✅ M6
GET  /api/config/paths            # 列出已配置路径                                    ✅ M6
GET  /api/config/paths/enabled    # 仅返回 enabled=true 的 path（给 file watcher 用） ✅ M6
```

### 2.2 扫描 (`/api/scan`)

```
POST /api/scan/jobs               # 启动扫描 { kind: "incremental"|"full" }        ✅ M6
                                 #   202 ACCEPTED；扫描 id
GET  /api/scan/jobs               # 列出所有 job（最近 N 条）                        ✅ M6
GET  /api/scan/jobs/active        # 当前活动扫描                                      ✅ M6
GET  /api/scan/jobs/{id}          # 单个 job 的状态 + 进度                          ✅ M6
GET  /api/scan/jobs/{id}/events   # SSE: progress + state 事件                     ✅ M6
POST /api/scan/jobs/{id}/pause    #                                                          ⏳ M8
POST /api/scan/jobs/{id}/resume   #                                                          ⏳ M8
POST /api/scan/jobs/{id}/cancel   #                                                          ⏳ M8
```

SSE 流格式（`text/event-stream`，`scan.py` M6 实现）：

```
event: progress
data: {"processed": 4321, "total": 10000, "faces": 234, "errors": 3,
       "state": "RUNNING", "job_id": "abc"}

event: closed                    # 上游断开 / 客户端 cancel
data: {}

event: end                       # job 进入终态（DONE / FAILED / CANCELLED）后流终止
data: {}
```

> M6 的 SSE 只发 `progress` 事件。`stage`（detecting / embedding /
> clustering）是后续 M7 的客户端进度条细节，本节理想契约里写的
> `event: stage` / `event: done` 留给 M8 完整 worker pipeline 时再发。

### 2.3 虚拟相册 (`/api/persons`)

```
GET    /api/persons?limit=50                       # 列表（每项含 cover_url）     ✅ M6
GET    /api/persons/count                          # 总数                              ✅ M6
GET    /api/persons/{id}                           # 详情：name, photo_count, sources, cover_face_id  ✅ M6
GET    /api/persons/{id}/photos?limit=200          # waterfall                            ✅ M6
GET    /api/persons/{id}/cover                     # ⭐ 虚拟相册封面（112×112 人脸 chip） ✅ M6
PATCH  /api/persons/{id}                           # 重命名 { name: str }                    ⏳ M9
POST   /api/persons/merge                          # { source_ids: [id], target_id: id }       ⏳ M9
DELETE /api/persons/{id}                           # 软删除（mark deleted）                  ⏳ M9
```

**封面契约**（关键）：
- `/api/persons/{id}/cover` 返回的是 **人脸 chip（112×112 对齐后）**，不是原图缩略图
- 数据源：`persons.thumbnail_face_id` → `faces.chip_path`
- 选脸策略：HDBSCAN 输出 `cluster_confidence` 最高的；同分时挑 `det_score` 最高的；再同时挑 `bbox_w * bbox_h` 最大的（更清晰）
- 用户在 `/persons` 列表看到的"这是谁"，**就是这张脸的清晰正面照**
- 缓存：服务端可加 `ETag: "<face_id>-<mtime>"`（M7）

### 2.4 图片 (`/api/photos`)

```
GET  /api/photos/{id}                     # 流式原图（支持 HTTP Range，不复制）   ✅ M6
GET  /api/photos/{id}/thumb                # 缩略图（JPEG 256×256）                  ✅ M6
GET  /api/photos/{id}/meta                 # 路径 + mtime + size + 自然尺寸 + 人脸列表（bbox + cluster_id + det_score + quality）+ EXIF（make/model/taken_at/lens/exposure/f_number/iso/focal_length/gps）✅ M7.6
GET  /api/photos/{id}/thumbnail            # 同 /thumb（保留别名）                          ⏳ M7
GET  /api/photos/{id}/metadata            # EXIF + bbox + faces 完整列表                    ⏳ M7
GET  /api/photos/{id}/faces               # 该图所有人脸（bbox + 哪个 person）              ⏳ M7
```

> M7.5 起 `/api/photos/{id}/meta` 返回扩展集（路径 + mtime + size +
> 自然宽高 + `faces[]`），供 `<FaceOverlay>` 渲染 bbox 与 EXIF 抽屉展示
> 详细信息。纯 EXIF（相机 / GPS / 曝光）字段仍推迟到 M9。

**安全契约**：`/api/photos/{id}` 永远只返回**已记录到数据库**的图片。  
绝不能直接 `FileResponse(request.query_params["path"])` —— 那会让攻击者用 `?path=../../etc/passwd` 读到任何文件。  
实现见 `service/photo_service.py::lookup_photo`：先从 DB 拿 `source.path`，再用 `is_under_any_whitelisted()` 二次校验（深度防御）；非白名单返回 403 `NOT_WHITELISTED`。

### 2.5 Review (`/api/review`)

```
GET  /api/review/pending?limit=20        # 待人工 review（低置信聚类）       ⏳ M9
POST /api/review/{face_id}              # { action: "accept"|"reject"|"merge_with", target: id } ⏳ M9
```

### 2.6 健康 (`/api/health`)

```
GET  /api/health            # liveness — 不查 DB       ✅ M6
→ {"status": "ok"}

GET  /api/ready             # readiness — 查 DB + AppLayout 摘要   ✅ M6
→ {"status": "ready", "data_dir": "~/.pick-face", "db": "...", "jobs": 0}
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

> **M7 状态**：✅ SPA 骨架 + 四个核心路由 + FaceViewer（键盘/滚轮/拖动/全屏/手势）+ SSE 进度条。
> **M7.5 状态**：✅ `<FaceOverlay>` bbox 渲染（按 cluster_id 高亮当前人）+ EXIF 侧抽屉（路径/尺寸/人脸列表；EXIF 字段待后端）。
> **M7.6 状态**：✅ 真实 EXIF — 服务层 `pick_face.service.photo_service.get_exif()` 用 PIL `Image.getexif()` 读 make/model/taken_at/lens/exposure/f_number/iso/focal_length/GPS；`/api/photos/{id}/meta` 响应多出 `exif` 块；`<PhotoMetaSheet>` 抽屉的 EXIF 段从占位切换到真实字段（相机 / 拍摄时间 / 曝光三段 / GPS DMS）。
> **M7.7 状态**：✅ `lib/toast.ts` sonner 门面 — 所有 toast 通过 `toast.fromError` / `success` / `warning` 触发；`ScanProgressBanner` 接入。
> **M7.8 状态**：✅ NC-research Badge — `/api/ready` 响应新增 `active_pack` 块（id / display_name / license_class / license_name / license_spdx / nc_research_acknowledged）；`<ModelPackCard>` 按 license_class 渲染 secondary / destructive / outline Badge，未确认 NC-research 时多挂一个红色 "AC-9 will block scans" Badge 并在 `<SettingsPage>` 挂载时触发一次性 `toast.warning`。
> **M7.9 状态**：✅ PWA — `vite-plugin-pwa@0.21.2` + `workbox-window@7.4.1`；`public/manifest.webmanifest` + 3 个 PNG icons（192/512/maskable 512，蓝色 `#2a6df4` 圆角 + 用户头像）；`VitePWA({ registerType: 'prompt', injectRegister: 'script', strategies: 'generateSW' })` 生成 `sw.js` + `registerSW.js` + `workbox-*.js`；缓存策略：应用壳（`navigateFallback: '/index.html'`）+ `/api/photos/{id}/thumb` CacheFirst 30d 256 entries + `/api/persons{,/{id}/photos}` SWR 1h 32 entries；`/api/photos/{id}` 原图走 Workbox 默认 `RangeRequestsPlugin`，`/api/scan/jobs/{id}/events` SSE 永不缓存（`navigateFallbackDenylist: [/^\/api\//]` + 不加 runtimeCaching）；`<SettingsPage>` 新增第 4 个 tab `App` → `<PwaSettingsCard>` 含手动 `<InstallAppButton>`（捕获 `beforeinstallprompt` + matchMedia standalone 检测，不主动弹）+ "Check for update" 按钮；`lib/pwa.ts` 是唯一注册入口，`registerSW({ onNeedRefresh → toast.info("New version available") + Reload action, onOfflineReady → toast.success })`；`import.meta.env.PROD` gating 保证 dev 不注册 SW；CI 守护 `index.html / manifest.webmanifest / sw.js / registerSW.js / icons/icon-{192,512,mask}.png` 全部入仓前不存在（产自 `pnpm build`）。全局 cmdk 搜索 / Playwright E2E 仍推迟到 M7.5 余下项。

```
src/pick_face/web/
├── __init__.py                  # 包标识；docstring 描述 app/static 关系
├── static/                      # Vite outDir（gitignore；CI 重建）
│   ├── index.html               # SPA 入口；FastAPI 在 / 挂载
│   └── assets/                  # hashed JS / CSS chunks
└── app/                         # Vite + React + TS + Tailwind + shadcn/ui 源码
    ├── package.json
    ├── pnpm-lock.yaml           # 入仓，CI 用作 pnpm 缓存键
    ├── vite.config.ts           # base=/, outDir=../static, proxy=/api
    ├── vitest.config.ts         # jsdom + globals
    ├── tailwind.config.ts / postcss.config.js
    ├── components.json          # shadcn/ui 配置
    ├── index.html               # vite HTML 模板（区别于 ../static/index.html）
    ├── tsconfig.json / tsconfig.node.json
    ├── public/favicon.svg
    ├── .env.example             # VITE_API_BASE=/api
    └── src/
        ├── main.tsx
        ├── App.tsx                          # createBrowserRouter + Providers
        ├── routeTree.ts
        ├── vite-env.d.ts                    # ImportMeta.env 类型
        ├── lib/
        │   ├── api/{client,schemas,hooks}.ts    # 14 端点手写 zod + TanStack Query
        │   ├── env.ts                            # import.meta.env 包装
        │   ├── cn.ts                             # clsx + tailwind-merge
        │   ├── sse.ts                            # 类型化 EventSource
        │   └── viewerStore.ts                    # zustand: FaceViewer 状态
        ├── components/
        │   ├── ui/                              # shadcn 复制源码（可改）
        │   ├── layout/{AppShell,ScanProgressBanner}.tsx
        │   ├── viewer/{FaceViewer,FaceOverlay,useViewerControls,ViewerToolbar}.tsx
        │   ├── persons/{PersonCard}.tsx
        │   └── settings/{PathList,PathAddDialog}.tsx
        └── pages/{HomeRedirect,PersonsPage,PersonDetailPage,SettingsPage,NotFoundPage}.tsx
```

**关键约定**：

- 所有按钮 / 弹窗 / 下拉 / Tab / Slider / Toast **必须用** shadcn/ui 的 `components/ui/*` —— 不允许临时 div + Tailwind 复刻（无障碍/键盘支持会丢）
- 新增 shadcn/ui 组件：手动把 shadcn 模板复制到 `src/pick_face/web/app/src/components/ui/`（**永不** `pnpm add shadcn`）
- 颜色 token（`--background` / `--foreground` / `--primary` / `--muted` ...）走 CSS 变量，**不**直接用 Tailwind class 硬编码 `bg-slate-900`
- 客户端 API 类型用 `zod` schema 手写镜像 Pydantic（`src/pick_face/web/app/src/lib/api/schemas.ts`）—— M9 端点数翻三倍时再评估是否切到 `openapi-typescript`
- 服务端状态用 TanStack Query；本地 UI 状态用 zustand；表单用 react-hook-form + zod

### 7.1 关键依赖

| 依赖 | 用途 |
|---|---|
| `react` / `react-dom` | UI 框架 |
| `react-router-dom` | 路由（`createBrowserRouter`，URL 即查看器状态） |
| `typescript` / `vite` | 类型 + 构建 |
| `tailwindcss` / `postcss` / `autoprefixer` | utility CSS |
| `class-variance-authority` / `clsx` / `tailwind-merge` | shadcn/ui 配套（`cn()`） |
| `@radix-ui/react-*` | shadcn/ui 行为原语 |
| `lucide-react` | 图标 |
| `react-hook-form` / `@hookform/resolvers` / `zod` | 表单 + 校验（与 Pydantic schema 互译） |
| `@tanstack/react-query` | 服务端状态缓存 + 失效 |
| `zustand` | 本地 UI 状态（查看器缩放 / 平移 / 全屏 / 当前 photoId） |
| `react-photo-album` | 瀑布流（`layout="rows"`） |
| `@use-gesture/react` | 拖动 + pinch + double-click |
| `framer-motion` | 查看器过渡 |
| `next-themes` | 主题（明 / 暗 / 跟随系统） |
| `sonner` | Toast（M7.7 接入：`lib/toast.ts` 门面收口所有调用方） |

构建产物：Vite 输出到 `src/pick_face/web/static/`，FastAPI 用 `StaticFiles` mount 到 `/`。
CI 工作流（`.github/workflows/ci.yml`）：`lint` → `frontend-build`（pnpm）→ `unit`（需要 web/static/ 存在）→ `frontend-test` → 三 OS smoke → bench → docs → AC-9。
sdist 排除 `web/app/**` 和 `web/static/**`（见 `pyproject.toml`），让 PyPI sdist 保持纯源码；wheel 自动携带 `web/static/`。

### 7.2 M7 已落地的 shadcn/ui 组件

| 组件 | 用在哪 |
|---|---|
| `Button` | 全局 |
| `Card` | PersonCard / PathList / Settings 卡 |
| `Dialog` | 添加扫描路径 / FaceViewer 宿主 |
| `Tabs` | `/settings`（Paths / Scan / Model） |
| `Switch` | 启用 / 禁用扫描路径 |
| `Progress` | 扫描进度条（SSE 推 percent） |
| `Skeleton` | 列表加载占位 |
| `Badge` | Model Tab（NC-research 警告 — M7.8） |
| `Label` / `Input` | 表单字段 |
| `Toaster` (sonner 门面) | M7.7 接入；`lib/toast.ts` 收口所有调用方 |

### 7.3 主题与暗色模式

`tailwind.config.ts` 配置 `darkMode: 'class'`。`<html>` 上的 `dark` class 由 `next-themes` 的 `ThemeProvider` 切换。CSS 变量定义在 `src/pick_face/web/app/src/styles/globals.css`。

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