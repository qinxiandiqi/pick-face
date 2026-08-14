# 05 数据与存储：pick-face v3 数据模型（v3.0）

> 文档版本：v3.0 · 2026-08-12
> 范围：Web 相册服务的 SQLite schema、文件布局、备份/恢复
> 关联：[01 PRD](01-product-requirement.md) · [03 §服务架构](03-architecture-design.md) · [04 §聚类流水线](04-algorithm-pipeline.md)

## 0. 设计原则

**pick-face 运行过程产生的所有持久化文件（配置、数据库、HNSW 索引、模型权重、缩略图、人脸 chip、任务状态、日志），全部归到一个独立的"应用专属根目录"下：**

```
~/.pick-face/                          # 应用根目录（pick-face 唯一命名空间）
```

> **路径解析优先级**（从高到低）：
> 1. 环境变量 `PICK_FACE_HOME`（Docker / 多实例 / 调试用）
> 2. 配置文件 `[server] data_dir`
> 3. 默认 `~/.pick-face/`（`Path.home() / ".pick-face"`）
>
> 所有派生路径（数据库、HNSW、缩略图、模型、缓存）**都在 `PICK_FACE_HOME` 之下**，不会跑到外面。

**为什么这样**：

- **一个目录管所有**——用户只要记住 `~/.pick-face/`，配置、数据、模型都在里面；不需要理解 XDG 三段式
- **统一命名空间 `pick-face`**——避免污染用户 home；卸载只需 `rm -rf ~/.pick-face`，不残留任何文件
- **Docker 友好**——挂 `-v ~/.pick-face:/data` 整个映射，容器内外路径一致；多实例用 `PICK_FACE_HOME=/srv/pick-face-2` 隔离
- **完全脱离扫描根**——用户在 `/mnt/photos` 加文件，pick-face **绝不**在 `/mnt/photos/.pick-face/` 写东西；扫描根里看不到任何痕迹

**扫描根目录里的原图（`/mnt/photos/...`）不在应用专属目录内**——原图是用户自己的数据，pick-face 只读不写。

### 0.1 三段语义（虽然路径不再用 XDG，但分类逻辑保留）

| 类别 | 在 `~/.pick-face/` 下 | 内容 | 备份策略 |
|---|---|---|---|
| 配置 | `~/.pick-face/config/` | `config.toml` | ✅ 必备份 |
| 数据 | `~/.pick-face/data/` | SQLite、HNSW、chips、thumbnails、covers、jobs、logs | ✅ 必备份（备份这一项 = 备份整个相册） |
| 缓存 | `~/.pick-face/cache/` | 模型权重、临时文件 | ❌ 可重下 / 重生成 |

## 1. 存储位置

```
~/.pick-face/                                    # 应用根目录（= PICK_FACE_HOME 的默认）
├── config/
│   └── config.toml                              # 白名单路径、模型 pack、阈值
├── data/                                        # 数据（备份这一项 = 备份整个相册）
│   ├── index.sqlite                             # 主数据库（见 §2 schema）
│   ├── index.sqlite-wal                         # WAL 日志
│   ├── index.hnsw                               # HNSW 持久化（hnswlib 格式）
│   ├── chips/                                   # 人脸 chip（112×112 对齐后）
│   │   └── ab/cd/<face_id>.jpg                  # 按 face_id 前 2 字符分桶
│   ├── thumbnails/                              # 原图缩略图（256×256 JPEG）
│   │   └── ab/cd/<xxh3>.jpg                     # 按 content_hash 前 4 字符分桶
│   ├── covers/                                  # 虚拟相册封面（chip 的硬链接 / 缓存）
│   │   └── person_<id>.jpg
│   ├── jobs/                                    # 扫描任务状态（崩溃恢复 / 审计）
│   │   └── scan-<uuid>.json
│   └── logs/
│       └── pick-face.log                        # 应用日志（rotated）
└── cache/                                       # 可丢弃的缓存
    ├── models/                                  # 模型权重（SHA256 已 pin，可重下）
    │   ├── yunet-sface/
    │   │   ├── face_detection_yunet_2023mar.onnx
    │   │   ├── face_recognition_sface_2021dec_int8.onnx
    │   │   └── .quant                           # 选定的量化档（fp32/int8）
    │   └── yunet-arcface/
    │       ├── face_detection_yunet_2023mar.onnx
    │       └── arcfaceresnet100-{fp32,int8}.onnx
    └── tmp/                                     # 解码 / 缩略图临时目录（可安全清空）
```

**路径可配置**：`config.toml` 的 `[server] data_dir` 改根目录（推荐生产 / NAS 场景）；细分子路径 `[index] db_path / hnsw_path / chips_dir / thumbnails_dir / covers_dir / models_dir` 也可单独覆盖。

**优先级**（见 §0）：
```
PICK_FACE_HOME 环境变量
       ↓ 覆盖
[server] data_dir 配置项
       ↓ 覆盖
默认值 ~/.pick-face/
```

**统一归属原则**：

| 文件类型 | 归属目录 | 是否备份 | 重建方式 |
|---|---|---|---|
| 配置文件 | `~/.pick-face/config/` | ✅ | 手写 |
| SQLite / HNSW | `~/.pick-face/data/` | ✅ 必须 | 不能重建（会丢失全部索引）|
| 人脸 chip | `~/.pick-face/data/chips/` | ✅ | 不能重建（会丢失代表脸）|
| 虚拟相册封面 | `~/.pick-face/data/covers/` | ✅ | 重生成 |
| 原图缩略图 | `~/.pick-face/data/thumbnails/` | ✅ | 不能重建（下次扫描重生成）|
| 任务状态 | `~/.pick-face/data/jobs/` | 可选 | 自动过期 |
| 模型权重 | `~/.pick-face/cache/models/` | ❌ 可不备份 | `init-models` 重新下载 |
| 日志 | `~/.pick-face/data/logs/` | ❌ | 自动 rotate |
| 临时文件 | `~/.pick-face/cache/tmp/` | ❌ | 自动清理 |

**扫描根目录**（用户原图，例如 `/mnt/photos/2024/`）**不在应用专属目录内**。原图是用户数据，pick-face 只读不写——`/mnt/photos/` 里**绝不会出现** `.pick-face/`。

**Windows 路径映射**：

| POSIX | Windows |
|---|---|
| `~/.pick-face/` | `%USERPROFILE%\.pick-face\` |
| `/mnt/photos/2024/` | `D:\photos\2024\` 或 `\\nas\photos\2024\` |

## 2. SQLite Schema

```sql
-- 扫描路径白名单（v3 新增）
CREATE TABLE scan_paths (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    path         TEXT NOT NULL UNIQUE,         -- 已 resolve 的绝对路径
    enabled      BOOLEAN NOT NULL DEFAULT 1,
    added_at     INTEGER NOT NULL,             -- unix timestamp
    last_scan_at INTEGER,                      -- 上次扫描时间
    notes        TEXT                          -- 用户标签
);
CREATE INDEX idx_scan_paths_enabled ON scan_paths(enabled);

-- 扫描任务状态（v3 新增）
CREATE TABLE scan_jobs (
    id           TEXT PRIMARY KEY,             -- uuid
    state        TEXT NOT NULL,                -- pending | running | paused | done | failed | cancelled
    kind         TEXT NOT NULL,                -- full | incremental | path_only
    path_id      INTEGER REFERENCES scan_paths(id),
    started_at   INTEGER,
    ended_at     INTEGER,
    processed    INTEGER NOT NULL DEFAULT 0,
    total        INTEGER NOT NULL DEFAULT 0,
    faces        INTEGER NOT NULL DEFAULT 0,
    errors       INTEGER NOT NULL DEFAULT 0,
    error_log    TEXT,                         -- JSON 数组
    progress_payload TEXT                      -- 序列化的中间状态（崩溃恢复）
);
CREATE INDEX idx_scan_jobs_state ON scan_jobs(state);

-- 照片（v2.x 已存在，v3 扩展）
CREATE TABLE photos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT NOT NULL UNIQUE,           -- 扫描时 resolve 的绝对路径
    mtime       INTEGER NOT NULL,
    size        INTEGER NOT NULL,
    content_hash TEXT NOT NULL,                 -- xxh3_64（增量检测用）
    width       INTEGER,
    height      INTEGER,
    format      TEXT,                           -- JPEG / HEIC / RAW
    exif_json   TEXT,                          -- 序列化 EXIF
    deleted     BOOLEAN NOT NULL DEFAULT 0,     -- 软删除（v3 新增）
    added_at    INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);
CREATE INDEX idx_photos_hash ON photos(content_hash);
CREATE INDEX idx_photos_mtime ON photos(mtime DESC);
CREATE INDEX idx_photos_deleted ON photos(deleted);

-- 人脸（v2.x 已存在，v3 扩展）
CREATE TABLE faces (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id    INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    bbox_x      REAL NOT NULL,
    bbox_y      REAL NOT NULL,
    bbox_w      REAL NOT NULL,
    bbox_h      REAL NOT NULL,
    det_score   REAL NOT NULL,
    landmarks   TEXT NOT NULL,                  -- JSON array of 5 (x,y)
    chip_path   TEXT,                           -- data/chips/ab/cd/<face_id>.jpg（相对 data/）
    embedding   BLOB NOT NULL,                  -- float32 数组（128 或 512 维）
    dim         INTEGER NOT NULL,               -- 128 / 512
    person_id   INTEGER REFERENCES persons(id) ON DELETE SET NULL,
    cluster_confidence REAL,                    -- HDBSCAN 隶属度（v3 新增）
    quality     REAL,                           -- 模糊度（v2.x 已有）
    added_at    INTEGER NOT NULL
);
CREATE INDEX idx_faces_photo ON faces(photo_id);
CREATE INDEX idx_faces_person ON faces(person_id);

-- 虚拟相册 / 人（v2.x 已存在，v3 扩展）
CREATE TABLE persons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT NOT NULL,                  -- "person_NNNN" 或用户重命名
    display_name TEXT,                          -- 用户友好名（默认 NULL）
    thumbnail_face_id INTEGER REFERENCES faces(id), -- 虚拟相册封面（用 chip，不用原图缩略图）
    face_count  INTEGER NOT NULL DEFAULT 0,
    photo_count INTEGER NOT NULL DEFAULT 0,
    deleted     BOOLEAN NOT NULL DEFAULT 0,     -- 软删除
    merged_into INTEGER REFERENCES persons(id), -- 合并目标
    added_at    INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);
CREATE INDEX idx_persons_deleted ON persons(deleted);

-- Review（v2.x 已存在）
CREATE TABLE review (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    face_id      INTEGER NOT NULL REFERENCES faces(id) ON DELETE CASCADE,
    action       TEXT NOT NULL,                 -- rename | merge | accept | reject
    payload      TEXT NOT NULL,                 -- JSON
    applied_at   INTEGER NOT NULL
);

-- 一次扫描的多脸关联（v3 新增，用于跨目录聚合）
CREATE TABLE photo_persons (
    photo_id  INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    face_id   INTEGER NOT NULL REFERENCES faces(id) ON DELETE CASCADE,
    PRIMARY KEY (photo_id, person_id, face_id)
);
CREATE INDEX idx_pp_person ON photo_persons(person_id);
CREATE INDEX idx_pp_photo ON photo_persons(photo_id);
```

### 2.1 v2.x 兼容层 — `source` 与 `face` 表（M8 增补）

> **注意**：M6/M7/M8 复用 v2.x 的 `source` / `face` 表（详见
> `src/pick_face/store/index.py:44`），不是上面的 `photos` / `faces`
> 范式。迁移到范式化 `photos` 表是 v4 的工作。

```sql
-- v2.x 表（pick-face 实际使用）
CREATE TABLE source (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT NOT NULL UNIQUE,
    rel_path    TEXT,
    size        INTEGER NOT NULL,
    mtime       REAL NOT NULL,
    hash_algo   TEXT,
    hash        TEXT,
    status      TEXT NOT NULL,                  -- M8: 'active' | 'missing' | 'removed'
    first_seen  REAL NOT NULL,
    last_seen   REAL NOT NULL
);
CREATE INDEX idx_source_status ON source(status);
```

**M8 软删除语义** — `source.status` 枚举扩展：

| 值 | 含义 | 设置者 |
|---|---|---|
| `active` | 图存在且未被用户删除（默认） | `INSERT OR IGNORE`（扫描） |
| `missing` | 上次扫描后文件从磁盘消失 | `scan_worker.run_scan` DEL pass |
| `removed` | 用户通过 `DELETE /api/photos/{id}` 删除 | `PhotoService.soft_delete` |

`status` 列是 `TEXT NOT NULL`，**没有 CHECK 约束**。新增枚举值不需要 schema 迁移（v3 没有迁移框架）。`PersonService` 所有查询都加 `JOIN source s ON ... AND s.status='active'`，软删除的图片自动从 face_count / photo_count / cover / photos 列表中剔除。

`_VALID_SOURCE_STATUSES = frozenset({"active", "missing", "removed"})` 在 `src/pick_face/store/index.py` 中定义，写入点（`_mark_missing` / `_mark_removed` / scan worker DEL pass）需保证值在集合内。

## 3. HNSW 索引

```python
# 与 v2.x 完全兼容
import hnswlib

index = hnswlib.Index(space="cosine", dim=512)  # 或 128
index.load_index(str(hnsw_path), max_elements=...)
index.add_items(embeddings, ids=face_ids)
```

**v3 增强**：
- 启动时 SQLite 和 HNSW 的 `id_map` **必须一致**（自检）
- 增量添加：单条 `add_items(1)` 即可
- 周期性 rebuild：当 `len(index) > 200k` 且删除 > 20%，触发重建（HDBSCAN 也跟着重做）

## 4. 文件系统布局

### 4.1 人脸 chip（`chips/`）—— 虚拟相册封面的数据源

```
chips/
└── ab/
    └── cd/
        └── <face_id>.jpg       # 112×112 对齐后 JPEG（q=92，~5 KB）
```

**用途**：
- **虚拟相册封面**（`/api/persons/{id}/cover` 直接返这张图）
- **人脸 bbox 可视化**（查看器中叠加在原图上的小方块）
- **review UI**（让用户快速看到"这是哪张脸"）

**为什么用 chip 而不是原图缩略图作封面**：
- chip 是 **112×112 人脸区域对齐后**——眼睛鼻嘴位置统一，**直接告诉用户"这是谁"**
- 原图缩略图是 256×256 含背景——可能露出半张脸、闭眼、侧脸
- chip 极小（~5 KB），列表渲染 50 个 person 只需 250 KB

**命名规则**：`<face_id>.jpg`（face_id 是 `faces.id` 自增主键）。  
**分桶**：`chips/ab/cd/<face_id>.jpg`（face_id 模 256 拆两级），避免单目录文件爆炸。  
**不与 content_hash 关联**：同一张照片第二次扫描不会重复生成 chip（按 `photo_id` 跳过）。

### 4.2 原图缩略图（`thumbnails/`）

```
thumbnails/
└── ab/
    └── cd/
        └── abcd1234...xyz.jpg    # xxh3_64(content) 分桶存储（256×256 JPEG q=85）
```

**用途**：`/api/photos/{id}/thumbnail`，瀑布流网格显示。

**命名规则**：`xxh3_64(content_bytes)` → 16 进制前 4 字符作为前两级目录。  
**为什么按 hash 分桶**：天然去重；跨目录同名内容只存一份。

### 4.3 虚拟相册封面（`covers/`）

```
covers/
└── person_<id>.jpg              # 实际是 chips/<face_id>.jpg 的硬链接或拷贝
```

**生成时机**：`cluster_worker` 给 person 分配 `thumbnail_face_id` 时同步生成。  
**为什么不直接用 `faces.chip_path` 走 `/api/faces/{id}/chip`**：列表渲染 50 个 person 时，每个 person 都要先查 face 再查 chip 路径，多一次 JOIN；缓存 cover 文件可走 nginx 直送。

### 4.4 任务状态（`jobs/`）

```
jobs/
└── scan-<uuid>.json
```

每次扫描创建一个文件，包含进度 + 错误。失败/取消保留作为审计日志。

## 5. 关键不变量（CRUD 设计的不变量）

| 不变量 | 强制 |
|---|---|
| `photos.path` 必须存在且在 `scan_paths.path` 子树下 | ✅ 触发器 / 应用层校验 |
| `faces.person_id` 为 NULL 表示"未聚类" | ✅ HDBSCAN 跑完后填 |
| 同一 `photo_id` 不允许多条 `faces` 有相同 `bbox` 完全重叠 | ✅ 应用层去重（IoU > 0.9 视为同一脸）|
| 软删除的 `photos.deleted = 1` 永远不出现在瀑布流 | ✅ 查询层过滤 |
| `persons.merged_into IS NOT NULL` 的虚拟相册不出现在 `/api/persons` | ✅ 查询层过滤 |
| `thumbnail_face_id` 必须属于该 person | ✅ 触发器 |

## 6. 备份与恢复

```bash
# 全量备份（推荐）
# 备份 config/ + data/ 两项足以；cache/ 可重下
tar czf pick-face-$(date +%F).tar.gz \
  ~/.pick-face/config/ \
  ~/.pick-face/data/

# 一键备份（如果 PICK_FACE_HOME 不是默认路径）
tar czf pick-face-$(date +%F).tar.gz "$PICK_FACE_HOME/config" "$PICK_FACE_HOME/data"

# 恢复
tar xzf pick-face-YYYY-MM-DD.tar.gz -C /

# SQLite 检查点（推荐备份前先跑）
sqlite3 ~/.pick-face/data/index.sqlite "PRAGMA wal_checkpoint(TRUNCATE);"
```

**HNSW 备份策略**：HNSW 是从 SQLite 重建的，每次 rebuild 写一次 `index.hnsw`。  
**崩溃恢复**：HNSW 比 SQLite 新 → 重建 HNSW；SQLite 比 HNSW 新 → 检查 SQLite，重建缺失。

## 7. 性能特征（100k 张照片）

| 表 | 行数 | 索引大小 | 顺序扫描 | 索引扫描 |
|---|---|---|---|---|
| photos | 100k | ~5 MB | 200 ms | 1 ms |
| faces | 800k (8 脸/图) | ~50 MB | 2 s | 5 ms |
| persons | 200 | < 1 MB | < 1 ms | < 1 ms |
| review | 10k | < 1 MB | < 10 ms | < 1 ms |
| **SQLite 总** | | **~80 MB** | | |
| HNSW (512-D) | 800k | ~200 MB | | KNN < 5 ms |

## 8. v2.x → v3 迁移

```
v2.x .pick-face/by_face/person_NNNN/<rel_path>   # 硬链接目录
                    ↓
v3 ~/.pick-face/data/index.sqlite                 # 数据库
  + photos 表
  + faces 表（person_id 引用）
```

**迁移工具**：`pick-face-web migrate /path/to/v2-output`  
- 默认从 `PICK_FACE_HOME`（即 `~/.pick-face/data/`）读 / 写
- 可用 `--data-dir <path>` 覆盖
- 扫描 `by_face/` 目录，反向解析每个硬链接的源文件路径
- 写 `photos` 和 `persons` 表（`person_id` 用文件夹名映射）
- `faces` 表里 `embedding = NULL`（v2.x 没存 embedding，要重做）

**保留期**：迁移完成后 v2.x 的 `by_face/` 目录保留 30 天，软链接标记"已迁移"，给用户手动验证。

## 9. 多用户 / 多租户（v4 预留）

v3 schema 不含 `user_id`。v4 引入时：

```sql
ALTER TABLE photos ADD COLUMN user_id INTEGER;
ALTER TABLE persons ADD COLUMN user_id INTEGER;
-- 路径白名单变成 "per-user" 而非 "global"
CREATE TABLE scan_paths (
    ...,
    user_id INTEGER NOT NULL REFERENCES users(id)  -- NEW
);
```

## 10. 引用与延伸阅读

- [01 PRD](01-product-requirement.md) — US-1/US-3/US-5
- [03 §服务架构](03-architecture-design.md) — 数据目录位置
- [04 §聚类流水线](04-algorithm-pipeline.md) — 何时写哪些表
- 归档：[M5 CLI §数据](archive/m5-cli/05-data-and-storage.md) — v2.x schema 历史