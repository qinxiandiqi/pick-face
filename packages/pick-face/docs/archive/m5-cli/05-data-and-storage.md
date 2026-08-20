# 05 数据与存储设计

> 文档版本：v0.1（预研稿） · 2026-07-30

## 1. 数据分层

```
热数据（运行时） ── SQLite (<output>/.cache/index.sqlite)
                ── HNSW 索引 (<output>/.cache/faces.hnsw)
冷数据（人脸样本缩略图）─<output>/.cache/thumbs/<face_id>.jpg
元数据（人类可读）── <output>/index.json (镜像 SQLite 关键关系)
报告产物 ── <output>/report.md / .html
最终产物 ── <output>/<person-id>/*.<ext> (软链接或回退拷贝)
```

## 2. SQLite Schema（v0.1）

### 2.1 启动 PRAGMA

每次打开连接时执行：

```sql
PRAGMA journal_mode = WAL;        -- 并发读 / 单写
PRAGMA synchronous  = NORMAL;     -- WAL 下可放宽
PRAGMA foreign_keys = ON;         -- 启用外键
PRAGMA temp_store    = MEMORY;
PRAGMA mmap_size     = 268435456; -- 256MB
```

### 2.2 schema_migrations

```sql
CREATE TABLE schema_migrations (
  version     INTEGER PRIMARY KEY,
  applied_at  REAL NOT NULL,
  description TEXT
);
```

启动时读 `MAX(version)`；若 `current < latest` 则顺序执行未应用的迁移（每条迁移一个不可变 SQL 脚本，命名 `migrations/0001_init.sql`、`0002_add_review_decision.sql` 等；**禁止修改已应用脚本**）。

### 2.3 主表

```sql
CREATE TABLE schema_version (version INTEGER PRIMARY KEY);

CREATE TABLE source (
  id          INTEGER PRIMARY KEY,
  path        TEXT NOT NULL UNIQUE,      -- 绝对路径
  rel_path    TEXT NOT NULL,             -- 相对第一个 src root 的路径
  size        INTEGER NOT NULL,
  mtime       REAL NOT NULL,
  hash_algo   TEXT NOT NULL DEFAULT 'xxh3_64',
  hash        TEXT NOT NULL,             -- hex, 16 chars (xxh3_64)
  status      TEXT NOT NULL,             -- active / missing
  first_seen  REAL NOT NULL,
  last_seen   REAL NOT NULL
);
CREATE INDEX idx_source_hash ON source(hash);
CREATE INDEX idx_source_status ON source(status);

CREATE TABLE face (
  id          INTEGER PRIMARY KEY,
  source_id   INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  bbox_x1     REAL, bbox_y1 REAL, bbox_x2 REAL, bbox_y2 REAL,
  det_score   REAL,
  lmk_x0 REAL, lmk_y0 REAL, lmk_x1 REAL, lmk_y1 REAL, lmk_x2 REAL,
  lmk_y2 REAL, lmk_x3 REAL, lmk_y3 REAL, lmk_x4 REAL, lmk_y4 REAL,
  quality     REAL,
  cluster_id  INTEGER,                   -- 当前聚类 ID（NULL = 未分配/噪声）
  cluster_prob REAL,
  low_quality INTEGER NOT NULL DEFAULT 0,
  review_state TEXT NOT NULL DEFAULT 'auto',  -- auto / confirmed / removed
  -- ====== 实施关键字段 (10 §5 升级策略 / 09 §6 / 05 §3 HNSW 重建) ======
  embedding   BLOB NOT NULL,             -- 512 维 float32 = 2048 bytes; 见 09 §6 / ADR-009
  model_version TEXT NOT NULL,           -- e.g. "buffalo_l@2023-11"; 升级触发整批重算 (10 §5)
  norm        REAL                       -- 可选: L2 范数 (MagFace 范数信号, 见 10 §2.3 留口子)
);
CREATE INDEX idx_face_source ON face(source_id);
CREATE INDEX idx_face_cluster ON face(cluster_id);
CREATE INDEX idx_face_model ON face(model_version);  -- 升级时按版本过滤

CREATE TABLE cluster (
  id          INTEGER PRIMARY KEY,        -- 1..N，与 person-XXXX 对应
  label       TEXT UNIQUE NOT NULL,       -- 'person-0001'
  size        INTEGER NOT NULL,
  mean_sim    REAL,                       -- 簇内平均相似度
  merged_into INTEGER REFERENCES cluster(id), -- 二级合并后留痕
  created_at  REAL NOT NULL,
  updated_at  REAL NOT NULL
);

CREATE TABLE review_decision (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL,              -- must_link / cannot_link / remove / rename
  face_a      INTEGER REFERENCES face(id) ON DELETE CASCADE,
  face_b      INTEGER REFERENCES face(id) ON DELETE CASCADE,  -- 仅 must_link/cannot_link
  cluster_id  INTEGER REFERENCES cluster(id) ON DELETE CASCADE, -- rename 用
  payload     TEXT,                       -- JSON 扩展
  created_at  REAL NOT NULL,
  applied_at  REAL                       -- 哪次 run 应用的
);
CREATE INDEX idx_review_kind ON review_decision(kind);

CREATE TABLE link (
  id          INTEGER PRIMARY KEY,
  face_id     INTEGER REFERENCES face(id) ON DELETE CASCADE,
  cluster_id  INTEGER REFERENCES cluster(id) ON DELETE CASCADE,
  link_path   TEXT NOT NULL,              -- 软链接相对输出目录的路径
  source_id   INTEGER REFERENCES source(id) ON DELETE CASCADE,
  link_kind   TEXT NOT NULL,              -- symlink / hardlink / junction / copy
  UNIQUE(cluster_id, source_id)
);
CREATE INDEX idx_link_cluster ON link(cluster_id);

CREATE TABLE run (
  id          INTEGER PRIMARY KEY,
  started_at  REAL NOT NULL,
  finished_at REAL,                       -- 留空 = 未完成（中断）
  mode        TEXT NOT NULL,              -- full / incremental / rebuild
  config_hash TEXT NOT NULL,
  stats_json  TEXT
);

CREATE TABLE error_log (
  id          INTEGER PRIMARY KEY,
  run_id      INTEGER REFERENCES run(id),
  path        TEXT,
  stage       TEXT,                       -- scan/decode/detect/embed/cluster/link
  message     TEXT,
  ts          REAL NOT NULL
);
```

幂等键由应用层组装 `(abs_path, size, mtime, hash)`；`UNIQUE(path)` 保证只存一条 `source`。

## 3. HNSW 索引

- 文件：`<output>/.cache/faces.hnsw`（hnswlib 持久化）。
- 维度：512；空间：cosine；`M=16`，`ef_construction=200`，`ef=50`。
- 内存：100k 512-D 约 ~200MB，常驻运行期；运行结束释放或持久化。
- **库选型**：hnswlib（`hnswlib>=0.7`，预编译 wheel 覆盖 Win/macOS/Linux x86_64 + arm64）。备选 Annoy（更慢但更易调试）。
- **同步策略**：`faces` 表写入新行 → `add_items` 追加到 HNSW；`face.review_state='removed'` → 从 HNSW 标 `deleted`（`mark_deleted`）而非物理移除；周期 `compact`（HNSW `add_items` 满 10% → rebuild）。
- **崩溃恢复**：HNSW 索引可由 SQLite 重建（`pick-face index --rebuild-hnsw`），即从 `face.embedding BLOB` 全量重建，保证「SQLite 永远权威、HNSW 永远是缓存」。

## 4. 软链接与回退（**单一权威**）

> 本节是软链接策略的权威描述；[02 §2.5](02-technical-pre-research.md) 引述本节。

| 平台 | 首选 | 回退顺序 |
|------|------|---------|
| Linux/macOS | `os.symlink(src, dst)` | 失败 → `shutil.copy2` |
| Windows 管理员/开发人员模式 | `os.symlink(src, dst, target_is_directory=isdir)` | 文件 → `os.link`（硬链接）；目录 → `mklink /J`（junction）；最后 → `shutil.copy2` |
| Windows 普通用户 | `shutil.copy2` | 显式 warning 写入 `report.md` 顶部 `Warnings` |

### 4.1 决策伪代码

```python
import os, subprocess, shutil, sys
from pathlib import Path

def link_or_copy(src: Path, dst: Path) -> str:
    src = src.resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        target_is_dir = src.is_dir() if sys.platform == "win32" else False
        os.symlink(str(src), str(dst), target_is_directory=target_is_dir)
        return "symlink"
    except OSError:
        if sys.platform == "win32" and src.is_dir():
            try:
                subprocess.check_call(["cmd", "/c", "mklink", "/J", str(dst), str(src)])
                return "junction"
            except subprocess.CalledProcessError:
                pass
    try:
        os.link(str(src), str(dst))
        return "hardlink"
    except OSError:
        shutil.copy2(str(src), str(dst))
        return "copy"
```

### 4.2 ONNX Runtime EP 选型

| 平台 | 推荐 EP | 备注 |
|------|--------|------|
| Windows 无 NVIDIA | CPU(MLAS) / DirectML | DirectML 走 DX12，任何现代 GPU 都跑 |
| Windows + NVIDIA | CUDA / TensorRT | `onnxruntime-gpu` 版本需严格匹配 CUDA/cuDNN |
| Linux + NVIDIA | CUDA / TensorRT | 同上 |
| macOS Apple Silicon | CPU（可尝试 CoreML） | MLX/CoreML 需自绑，非 InsightFace 默认 |
| Linux + AMD | ROCm / MIGraphX | 生态较新 |

`--provider auto` 时尝试顺序：`cuda` → `directml` → `cpu`；失败链路在 `report.md` 顶部 `Warnings` 列出。

### 4.3 链接命名与冲突

- 链接命名：`<src_rel_path>`，冲突时追加 `-<n>` 后缀。
- 跨设备源（不同卷）软链接失败时直接回退拷贝并告警。
- 跨平台源：Windows 上 junction 仅接受绝对路径；symlink 优先用相对路径（`os.path.relpath(src, dst.parent)`），但被复制/移动后行为不一致 —— 工具默认记录绝对路径以便审计。

## 5. 输出目录布局与 meta.json

```
output/
├── .cache/
│   ├── index.sqlite
│   ├── faces.hnsw
│   └── thumbs/
├── index.json
├── report.md
├── person-0001/
│   ├── meta.json
│   ├── 2023-05-trip/IMG_0001.jpg -> /Volumes/Photos/2023-05-trip/IMG_0001.jpg
│   └── 2023-08-party/IMG_0042.jpg -> /Volumes/Photos/2023-08-party/IMG_0042.jpg
├── person-0002/
│   └── ...
├── _review/                 # 宽松同人或低置信度（仅当 --emit-review 启用）
└── _archive/                # 被合并/废弃簇的旧链接（GC 由 pick-face prune 清理）
```

`meta.json` schema：

```json
{
  "schema_version": 1,
  "cluster_id": 1,
  "label": "person-0001",
  "size": 128,
  "mean_sim": 0.62,
  "created_at": 1722345678.0,
  "updated_at": 1722512000.0,
  "merged_into": null,
  "first_seen": "2023-05-12T08:30:00Z",
  "last_seen":  "2025-12-01T19:12:00Z",
  "review_state": "auto"
}
```

`index.json` 镜像 SQLite 中 `cluster` + `link` 关系（不含 embedding），便于 grep/调试。

## 6. 一致性约束与原子切换

- 每次 `run` 开始写 `run` 表，结束写 `finished_at`。
- 任意阶段异常，`run.finished_at` 留空；下次启动时 `gc` 子命令清理未提交的临时文件。
- 软链接的源路径写入 link 表以方便审计；运行时只信任 `source.path` + `link.link_path` 的组合。
- **输出目录原子切换（staging → rename）**：

  ```
  <out>/.staging-<run_id>/
      .cache/
      index.json
      report.md
      person-0001/...
      person-0002/...
  # 完成后：
  <out>/.prev-<run_id>   # 旧目录改名保留，便于回滚
  <out>/.staging-<run_id> -> <out>  # atomic rename
  # 失败时：删除 .staging-<run_id>，.prev-<run_id> 改名回 <out>
  ```

  `pick-face run --atomic` 默认开启；`--no-atomic` 仅在调试时使用。
- **回滚**：`pick-face rollback --to <run_id>` 将 `<out>` 替换为 `<out>/.prev-<run_id>`；保留最近 3 个 `.prev-`。
- **并发**：CLI 不支持多实例同时写同一 `<out>`；启动时获取 `<out>/.lock` 文件锁（`flock` 风格）。

## 7. 备份与迁移

- 用户拷走整个 `output/` 即可带走全部结果（包含索引）。
- 跨机器迁移：同算法版本可直接复用 `index.sqlite` + `faces.hnsw`；不同算法版本建议 `--rebuild`。
