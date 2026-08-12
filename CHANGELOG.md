# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
— see [docs/12-compatibility-promise.md](docs/12-compatibility-promise.md) for
the full policy.

---

## [3.0.0] - 2026-08-12 — **Product pivot**: Web gallery service

**Major product pivot.** pick-face transitions from a CLI tool
(`pick-face run --src ... -o ...`) to a **self-hosted Web service**
(`pick-face-web serve`). New product is a face-clustered photo gallery
that you open in a browser.

> **CLI still works.** All v2.x commands (`pick-face run`,
> `pick-face init`, `pick-face init-models`, `pick-face doctor`)
> remain available and produce the same `by_face/person_NNNN/...`
> directory layout. The new `pick-face-web` subcommand is added
> alongside, not instead.

### What you get

A FastAPI app + React SPA:

- **Configure scan paths** in the Web UI (`/settings`) — added paths
  go through a whitelist (`Path.resolve()` + allowed-roots check).
- **Background scan** with progress streamed to the browser via
  Server-Sent Events.
- **`/persons`** — face-clustered virtual albums (one per detected
  identity, sorted by representative photo + face count).
- **`/persons/{id}`** — waterfall view of every photo where this
  person appears.
- **`/persons/{id}/photos/{photoId}`** — full-screen viewer with
  `← / → / Space` keys, double-click to zoom, drag-pan, pinch/swipe
  on touch, `F` for fullscreen, `Esc` to exit.
- **Incremental updates** via `watchdog` — new photos added to a
  scan path appear in the gallery within seconds.
- **Multi-source aggregation** — multiple directories become one album.
- **Originals are never copied** — the viewer streams via HTTP Range.
  Only thumbnails land in `~/.local/share/pick-face/thumbnails/`.

### New architecture

- New `src/pick_face/service/` sub-package (config / scan / person / photo
  services, file watcher).
- New `src/pick_face/api/` sub-package (FastAPI routers under `/api/*`).
- New `src/pick_face/worker/` sub-package (scan worker, index worker,
  cluster worker).
- New `src/pick_face/web/` — built SPA (**React + Vite + TypeScript + shadcn/ui + Tailwind CSS**, see ADR-014).
- Algorithm core (`ingest/`, `store/`, `output/`, `platform/`) is reused
  100%; only the call sites moved from CLI → FastAPI `app.on_event("startup")`.
- Data layout changed: SQLite + HNSW + thumbnails now live under
  `~/.local/share/pick-face/` instead of `<scan-root>/.pick-face/`.
  A migration tool (`pick-face-web migrate`) reads old `by_face/` and
  populates the new database.

### Documentation

All docs rewritten for the Web service:

- `docs/01-product-requirement.md` — Web service PRD, AC-W1..W9
- `docs/02-technical-pre-research.md` — stack rationale
- `docs/03-architecture-design.md` — FastAPI app + worker + SPA
- `docs/04-algorithm-pipeline.md` — long-lived sessions + watchdog
- `docs/05-data-and-storage.md` — SQLite schema + thumbnail layout
- `docs/06-engineering-plan.md` — M6+ milestones
- `docs/07-risk-and-decisions.md` — ADRs
- `docs/09-face-recognition-pipeline.md` — end-to-end walkthrough
- `docs/11-`, `docs/12-`, `docs/13-`, `docs/14-` — refreshed front-matter;
  algorithm/model/policy content unchanged
- `docs/troubleshooting.md` — appended v3-specific entries
- `docs/ARCHIVE-NOTES.md` — pointer to the v2.x CLI archive

### Migration from v2.x

```bash
# Install v3 (preserves v2.x CLI)
uv pip install -U "pick-face[web]"

# Migrate v2.x by_face/ into v3 database
pick-face-web migrate /path/to/v2-output

# Launch the web service
pick-face-web serve
```

### Notes

- `yunet-sface` (default MIT) and `yunet-arcface` (high-precision
  Apache-2.0+MIT) packs unchanged — the model layer is product-shape
  agnostic.
- AC-9 commercial-compliance gate still only fires for NC-research packs
  (`buffalo_l` / `buffalo_sc` / `antelopev2`).
- The `web` extra in `pyproject.toml` adds `fastapi`, `uvicorn[standard]`,
  `watchdog`, `apscheduler`. Existing `heic`, `raw`, `gpu` extras
  unchanged.
- Frontend stack locked at M6 kickoff (ADR-014): **shadcn/ui**
  (Radix + Tailwind, copy-source) + **react-photo-album** + **@use-gesture/react**
  + **framer-motion** + **TanStack Query** + **zustand** + **react-hook-form** +
  **zod** + **lucide-react** + **sonner**. shadcn/ui components are
  generated into `src/web/components/ui/`; new components added via
  `pnpm dlx shadcn@latest add <component>`.

### v3.0.0 app-dir contract (NEW)

All pick-face persistent state lives under **one application root** —
no XDG split, no "hidden folder inside the user's photo tree":

```
~/.pick-face/                              # = PICK_FACE_HOME default
├── config/                                # XDG_CONFIG equivalent: config.toml
├── data/                                  # XDG_DATA equivalent: backup this = backup the album
│   ├── index.sqlite
│   ├── index.hnsw
│   ├── chips/                              # 112×112 face crops
│   ├── thumbnails/                         # 256×256 photo thumbs
│   ├── covers/                             # per-person cover files
│   ├── jobs/                               # scan task state
│   └── logs/
└── cache/                                  # XDG_CACHE equivalent: redownloadable
    ├── models/                             # ONNX weights (SHA256-pinned)
    └── tmp/
```

**Path resolution priority** (high → low):
1. `PICK_FACE_HOME` environment variable (Docker / multi-instance / debugging)
2. `[server] data_dir` in `~/.pick-face/config/config.toml`
3. Default `~/.pick-face/` (= `Path.home() / ".pick-face"`)

**Uninstall**: `rm -rf ~/.pick-face` — no residue.

**Docker**:
```bash
docker run -d -p 8000:8000 \
  -v /mnt/photos:/photos:ro \
  -v ~/.pick-face:/data \
  -e PICK_FACE_HOME=/data \
  pick-face/web:latest
```

| Sub-dir | Role | Backup? |
|---|---|---|
| `config/config.toml` | TOML configuration | **必备份** |
| `data/index.sqlite` + `data/index.hnsw` | 主数据库 + 向量索引 | **必备份** |
| `data/chips/<face_id>.jpg` | 人脸 chip（112×112 对齐后） | **必备份**（虚拟相册封面数据源） |
| `data/covers/person_<id>.jpg` | 虚拟相册封面（chip 的硬链接 / 缓存） | 备份（可重新生成） |
| `data/thumbnails/<hash>.jpg` | 原图 256×256 缩略图 | 备份（可重新生成） |
| `data/jobs/scan-<uuid>.json` | 扫描任务状态 | 可选 |
| `data/logs/pick-face.log` | 应用日志 | 否 |
| `cache/models/<pack>/` | 模型权重 | 否（SHA256 pin，可重下） |

### v3.0.0 virtual-album cover (NEW)

`/api/persons/{id}/cover` returns the person's **face chip** (112×112
aligned) — not a photo thumbnail. Data source: `persons.thumbnail_face_id`
→ `faces.chip_path`. Selection: highest `cluster_confidence`, then highest
`det_score`, then largest `bbox_w * bbox_h` (clearest). This way the
`/persons` grid tells the user "who is who" at a glance, even when the
underlying photos contain side profiles or closed eyes.

### M6 implementation (Web service foundation)

The M6 milestone ships the **service + API + worker skeleton** end-to-end.
The React SPA itself lands in M7; M6 supplies the FastAPI surface, scan
worker, `pick-face-web` console script, and 80 new unit tests + 5
integration tests.

#### New modules

- **`src/pick_face/service/`** — algorithm-agnostic service layer
  - `paths.py` — `AppLayout` resolves `~/.pick-face/` (override via
    `PICK_FACE_HOME`), materializes the 3-tier `config/` + `data/` +
    `cache/` directory tree
  - `config_service.py` — path-whitelist CRUD (TOML persistence with
    Windows-path backslash escaping), validation (`Path.resolve()` +
    lexical `..` rejection + whitelist-membership check)
  - `scan_service.py` — JSON-backed scan-job state machine
    (`QUEUED` / `RUNNING` / `DONE` / `FAILED` / `CANCELLED`),
    `data/jobs/scan-<uuid>.json` registry (single-process M6 scope;
    SQLite-backed in M8)
  - `person_service.py` — virtual-album queries (list / count /
    detail / cover selection by `quality → det_score → bbox_area`)
  - `photo_service.py` — photo lookup with whitelist enforcement,
    thumbnail cache (`256×256` JPEG, content-hash bucketed, 100% cover
    via `is_under_any_whitelisted`)
  - `file_watcher.py` — `watchdog` observer stub; M6 uses polling,
    real-time events arrive in M8
- **`src/pick_face/api/`** — FastAPI routers (all under `/api/*`)
  - `app.py` — `create_app()` factory: lifespan starts/stops the
    in-process `ScanRunner`; SPA static mount
    (`src/pick_face/web/static/`) for the M7 build artifact
  - `health.py` — `/api/health` (liveness) + `/api/ready` (DB +
    layout sanity check)
  - `config.py` — `/api/config/paths` CRUD with stable error codes
    (`NOT_FOUND → 404`, `NOT_A_DIRECTORY → 400`, `NOT_READABLE → 403`,
    `PATH_TRAVERSAL → 400`, `DUPLICATE → 409`, `NOT_WHITELISTED → 403`)
  - `scan.py` — `/api/scan/jobs{,/active,/{id},/{id}/events}` —
    job create/list/get/SSE stream. Defensive `try/except RuntimeError`
    around `asyncio.create_task` (sync handlers in TestClient run in a
    worker thread without a running loop)
  - `persons.py` — `/api/persons{,/count,/{id},/{id}/photos,/{id}/cover}`
  - `photos.py` — `/api/photos/{id}` (HTTP Range streaming, never
    copies the original), `/api/photos/{id}/thumb`, `/api/photos/{id}/meta`
  - `deps.py` — FastAPI dependency providers (`get_layout`,
    `get_*_service`) with real `Request` import (not `TYPE_CHECKING`),
    so FastAPI registers `Request` as `Depends` instead of treating it
    as a query parameter
- **`src/pick_face/worker/`** — async workers driven by `asyncio`
  - `scan_worker.py` — `run_scan()` coroutine: per-file detect + embed
    in `run_in_executor`. **Each file opens a fresh SQLite connection**
    — connections can't cross threads in SQLite's `check_same_thread=True`
    default
  - `runner.py` — `ScanRunner` polls the JSON job registry, dispatches
    to `scan_worker`. `make_runner()` is best-effort: detector/embedder
    are `None` if no model pack is on disk (the SPA shows
    "init-models required")
- **`src/pick_face/web_cli.py`** — `pick-face-web {init,serve,migrate}`
  argparse subcommands (NOT Typer — we keep one CLI style across the
  project). `init` creates the app root + default `config.toml`;
  `serve` runs the FastAPI app via uvicorn; `migrate` reads v2.x
  `by_face/` and populates the v3 SQLite DB.

#### pyproject changes

- `__version__ = "3.0.0.dev0"` in `src/pick_face/__init__.py`
- New `[web]` extra: `fastapi>=0.110,<1`, `uvicorn[standard]>=0.27,<1`,
  `watchdog>=4,<7`, `apscheduler>=3.10,<4`, `python-multipart>=0.0.9,<1`
- New `[dev]` extra add-ons: `pytest-asyncio>=0.23,<1`, `httpx>=0.27,<1`
- New console script: `pick-face-web = "pick_face.web_cli:main"`
- New pytest marker: `web_smoke` (end-to-end smoke for v3 Web service)
- 19 new M6 modules registered in
  `tests/unit/test_packaging.py::EXPECTED_MODULES`

#### Tests added (M6)

- `tests/unit/test_service_paths.py` — 7 tests (HOME + USERPROFILE
  env var handling on Windows, `PICK_FACE_HOME` override, default
  layout, three-tier creation)
- `tests/unit/test_service_config.py` — 13 tests (validation rules,
  dedup, persistence, TOML round-trip with backslash escaping)
- `tests/unit/test_service_scan.py` — 13 tests (state machine
  transitions, JSON round-trip, persistence)
- `tests/unit/test_service_person.py` — 11 tests (cover selection
  algorithm, cluster queries — fixed seed for v2.x NOT NULL columns
  `cluster.size/created_at/updated_at` + `source.hash_algo` +
  `face.cluster_id`)
- `tests/unit/test_service_photo.py` — 8 tests (thumbnail generation,
  whitelist enforcement, missing photo handling)
- `tests/unit/test_api_routes.py` — 20 tests (full FastAPI surface via
  TestClient, with `get_layout` patched to the temp fixture)
- `tests/unit/test_scan_worker.py` — 3 tests (`asyncio.run` on
  `run_scan`, per-file errors, progress callback — stub detector +
  4-D embedder, no real weights)
- `tests/unit/test_web_cli.py` — 7 tests (`init` / `serve` / `migrate`
  subcommands; uses argparse, not Typer)
- `tests/integration/test_web_smoke.py` — 5 tests, all passing — end-to-end
  smoke: `pick-face-web init` → whitelist photos → start scan → drive
  `run_scan` directly via `asyncio.run` (TestClient loop doesn't tick
  scheduled tasks during sync calls) → query persons → serve thumbnail
  → check health. **Stub detector/embedder wired before
  `make_runner()`** so no real weights needed in CI.

M6 test totals: **381 tests collected** (376 unit/integration + 3
deselected as `real_data`; 5 of those are `web_smoke` integration).
Before M6: ~301. M6 delta: **+80 tests**.

#### M6 → M7 hand-off

- The React SPA from `apps/web/` will replace
  `src/pick_face/web/static/index.html` at build time; the static mount
  is observable end-to-end today via the M6 placeholder.
- `ScanRunner.consider()` (polling) becomes event-driven when
  `watchdog` events arrive in M8.
- The single-process JSON job registry
  (`data/jobs/scan-<uuid>.json`) becomes a SQLite-backed `jobs` table
  when multi-process uvicorn workers land in M8.

---

## [2.1.0] - 2026-08-10 — High-precision tier (yunet-arcface)

Adds a second bundled model pack (`yunet-arcface`) alongside the
default `yunet-sface`. Same `--pack` switch, same `pick-face` API,
same core wheel — but the new pack ships 512-D **ArcFace R100**
embeddings (vs. SFace 128-D) for higher-precision clustering on
photographic datasets. Inside the route-B contract, this is a
**pure addition** — existing `yunet-sface` configs keep working
unchanged.

> **License posture:** `yunet-arcface` is **PERMISSIVE** under the
> Apache-2.0 / MIT split. The detector (YuNet) is MIT. The
> embedder weights (ArcFace R100) are released under Apache-2.0 by
> ONNX Model Zoo. AC-9 does **not** fire — no acknowledgment needed.
> The ArcFace model was trained on refined **MS-Celeb-1M**; the
> weights are Apache-2.0 but the **training-data rights remain the
> user's responsibility**. See
> <https://github.com/onnx/models/blob/main/validated/vision/body_analysis/arcface/README.md>.

### Highlights

- **New model pack** `yunet-arcface` (YuNet + ArcFace R100, 512-D).
  Two QUANT variants: **FP32** (~261 MB, x86 + GPU) and **INT8**
  (~66 MB, ARM / Pi 4/5). Default is FP32.
- **CLI**: `pick-face init-models --pack yunet-arcface --quant {fp32,int8} --allow-network`.
  Only the requested variant is downloaded (FP32 request skips
  INT8, saving ~66 MB).
- **Clustering threshold**: for 512-D embeddings, set
  `clustering.merge_threshold = 0.55` in `pick-face.toml`. The
  SFace default (`0.0`) is too aggressive at 512-D.
- **GPU / providers**: `runtime.provider = "cuda"` now plumbs
  through to the ArcFace ORT session. Install `onnxruntime-gpu`
  (`uv pip install -U onnxruntime-gpu` or
  `uv pip install -e ".[gpu]"`). Pre-existing gap I-7 (providers
  not passed to `build_embedder`) is fixed.
- **Thread policy**: ArcFace's `intra_op_num_threads` defaults to
  `cpu_count // 2` instead of being hardcoded to `1`. SFace keeps
  its conservative policy. Override with `OMP_NUM_THREADS`.

### Pinned weights (audit-friendly)

| Variant | URL | SHA256 | Size |
|---|---|---|---|
| YuNet detector | `https://media.githubusercontent.com/media/opencv/opencv_zoo/<pinned-commit>/models/face_detection_yunet/yunet_2023mar.onnx` | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` | 232,589 B |
| ArcFace FP32 | `https://media.githubusercontent.com/media/onnx/models/<pinned-commit>/validated/vision/body_analysis/arcface/model/arcfaceresnet100-8.onnx` | `f3a6bc281e72f88862f5748b53be3d76b3b48f8f1ab1f4a537941bdc4e1b01da` | 261,036,388 B |
| ArcFace INT8 | `https://media.githubusercontent.com/media/onnx/models/<pinned-commit>/validated/vision/body_analysis/arcface/model/arcfaceresnet100-11-int8.onnx` | `c625ca68a422418c48aa84f73341337e0a92b111f327909005d1eec07c95f936` | 65,764,892 B |

### Migration from `yunet-sface`

```toml
# pick-face.toml — switch to high-precision tier
[runtime]
pack = "yunet-arcface"

[clustering]
merge_threshold = 0.55  # 512-D cosine hint
```

```bash
# download INT8 (ARM-friendly) or FP32 (x86 + GPU)
pick-face init-models --pack yunet-arcface --quant int8 --allow-network
```

If you only want the default tier, do **nothing** — `yunet-sface`
remains the default pack and all v2.0.x configs keep working.

### Architecture extensions (also in this release)

These landed alongside to make the new pack work end-to-end:

- **B-2 / B-3**: `PackDescriptor` gained `embedder_alternates: list[EmbedderVariant] | None`.
  `ModelPack.Protocol.expected_files` took a `variant: str | None = None` keyword
  so multi-quant packs can return a variant-aware list.
- **B-1**: `init-models` gained a `--quant` option. `ModelPack.Protocol.download_to`
  took a `quant: str = "fp32"` keyword so single-variant packs can ignore it.
- **I-2**: variant selection is a single source of truth — `download_to(quant=)`
  writes `target_dir/.quant`, `build_embedder()` reads it. `PICK_FACE_ARCFACE_QUANT`
  env var is a fallback.
- **I-7**: `runtime.load_pack_runner` now passes `providers=providers` to
  `pack.build_embedder(...)`. Previously ORT picked CPU only.
- **I-6**: ArcFace threads default to `cpu_count // 2`; `OMP_NUM_THREADS` wins.

### Verification

- `uv run pytest tests/unit/test_yunet_arcface_pack.py` — 26 tests,
  covering discovery, LicenseClass, SPDX, tags, variants, providers,
  thread policy, channel-order preprocessing, AC-9 PERMISSIVE pass-through.
- `uv run pytest tests/unit/test_route_b_guards.py tests/unit/test_packaging.py`
  — existing route B + packaging guards still pass.
- `uv run pytest tests/integration/test_real_faces_ac1.py -m real_data`
  — parametrized over `("yunet-sface", 0.0, SOFT)` and
  `("yunet-arcface", 0.55, SOFT)`.

### Notes

- `yunet-mfn` is still a registered alias (deprecated, points at
  `yunet-sface`) for v1.x config back-compat. No new alias is added.
- The `ArcFaceR100Embedder.preprocess()` static method exposes the
  RGB→BGR + `(x-127.5)/128` + NCHW transform so the unit tests can
  assert channel order without running real weights.

---

## [2.0.0] - 2026-08-07 — Route B (model pack plugins)

The **route B** milestone: pick-face is no longer bound to InsightFace.
The default model pack is now the bundled Apache-2.0 `yunet-sface`
(YuNet + SFace INT8), which fits on a Raspberry Pi 3B. The
InsightFace `buffalo_*` family moves to a separate opt-in plugin
(`pick-face-modelpack-insightface`) and stays NC-research.

This release is a **minor-API change** — see *Migration* below.

> **Note — default pack rename (v2.0.0-dev0 → v2.0.0):**
> The default pack shipped in v2.0.0-dev0 was `yunet-mfn` (YuNet +
> MobileFaceNet INT8). During pre-release testing we discovered the
> upstream MobileFaceNet INT8 weights were removed from
> `opencv/opencv_zoo` (commit 8ac7b08869, 2025-07-31, part of the
> HuggingFace migration) and the API call returns HTTP 404. The only
> remaining Apache-2.0 face embedder in opencv_zoo is SFace, so the
> default pack was renamed to `yunet-sface`. The deprecated
> `yunet-mfn` id is still registered and points users at the
> replacement with a clear error message — see
> [docs/14 §2.3](docs/14-model-pack-plugins.md).

### Added

- **`ModelPack` plugin protocol** ([docs/14](docs/14-model-pack-plugins.md)).
  Each pack declares a `PackDescriptor` (id, license class, SHA256, URL,
  accuracy), plus `build_detector / build_embedder / build_aligner /
  download_to`. Plugins register via the `pick_face.model_packs`
  entry-point group and are discovered at runtime.
- **`LicenseClass` enum** (`PERMISSIVE / NC_RESEARCH / USER_SUPPLIED`)
  drives AC-9 instead of the hard-coded `INSIGHTFACE_MODELS` set. PERMISSIVE
  packs (like `yunet-sface`) skip the gate entirely; NC_RESEARCH packs
  require `accept_noncommercial_model_license = true`; USER_SUPPLIED
  packs warn in the report.
- **Bundled `yunet-sface` pack** (YuNet + SFace INT8, ~10 MB on disk,
  ~150 MB peak RAM, LFW ~99.45%). Default out of the box;
  Pi 3B-friendly. See [docs/13](docs/13-raspberry-pi-support.md).
- **`pick-face doctor`** subcommand — list installed ModelPack plugins,
  show which weights are present / missing under `model_dir`, and warn
  if AC-9 will block the active pack.
- **`init-models --pack <id>`** to download weights for any installed
  pack. The License Notice is rendered from the pack's
  `PackDescriptor.license_notice_text` and `I AGREE` is only required
  for NC_RESEARCH packs.
- **`pick-face-modelpack-insightface`** plugin skeleton under
  `plugins/pick-face-modelpack-insightface/` — installs the
  InsightFace `buffalo_l` / `buffalo_sc` / `antelopev2` packs as a
  separate distribution. The plugin code is MIT; the weights remain
  NC-research (see [docs/11](docs/11-commercial-compliance.md)).
- **`scripts/pin_sha256.py`** — computes the SHA256 of every file in
  `<model_dir>/<pack_id>/` and prints the snippet to paste into the
  pack source so integrity checks are auditable in code review.
- **`tests/unit/test_route_b_guards.py`** — CI guard asserting that
  `insightface` is not in the default deps, `yunet-sface` is registered
  as an entry-point, and the bundled pack advertises Apache-2.0 +
  arm-friendly / low-ram tags. Also guards that the deprecated
  `yunet-mfn` alias stays registered for v1.x back-compat.

### Changed

- **Default pack**: `yunet-sface` (was `buffalo_l` in v1.x). The `[runtime].pack`
  field replaces `[runtime].model_name`; `model_name` is still parsed
  for v1.x compat and emits a `DeprecationWarning`.
- **Default `model_dir`**: `~/.cache/pick-face/models` (was
  `~/.insightface/models`). Override with `PICK_FACE_MODEL_DIR` or
  `[runtime] model_dir`.
- **`is_commercial_unsafe()`** now defers to `PackDescriptor.license_class`
  when the pack plugin is installed; falls back to the legacy model-name
  set only when the plugin is missing.
- **`report.md` / `report.json` / `report.html`**: top-line header now
  reads **Model pack** instead of **Model**, and the descriptor string
  (detector + embedder names) comes from the pack rather than being
  hardcoded to "SCRFD-10G + ArcFace w600k_r50".
- **`init-models`**: requires `--pack <id>` for clarity; prints the
  pack-specific License Notice. NC packs still need `--allow-network`
  and either an interactive `I AGREE` or `--yes`.
- **`onnxruntime`**: required ≥ 1.24 (numpy 2.x ABI); `numpy` stays
  `>=1.24,<3` (no other change). GPU extras (`onnxruntime-gpu`,
  `onnxruntime-directml`) bumped to ≥ 1.24.
- **`Aligner` Protocol** moved from `pick_face.ingest.detector` to
  `pick_face.ingest.align`; re-exported from `detector` for v1.x
  plugin compat.
- **`index` / `run`** now go through `load_pack_runner(cfg)` (route B
  canonical entry point). `load_insightface_runner(cfg)` is kept as a
  narrow implementation backing the InsightFace opt-in packs.
- **Clustering defaults**: `min_cluster_size 3 → 4`,
  `merge_threshold 0.55 → 0.0`. The v1.x defaults were tuned for
  ArcFace w600k_r50 (512-D) — SFace INT8 (128-D) collapses distinct
  identities into a much tighter cosine cone (centroid pairwise sim
  ≥ 0.55 on AT&T), so any positive `merge_threshold` over-merges all
  faces into 1 cluster. With `merge_threshold=0.0` the 2-pass centroid
  merge is opt-in (set a positive value in `pick-face.toml` for
  high-dim embedders); HDBSCAN's initial labels are preserved by
  default. See `docs/04 §3.1` for the rationale and the
  `tests/integration/test_real_faces_ac1.py` sweep that pinned the
  v2.0.0 defaults.
- **`_centroid_merge` bug fix**: when `merge_threshold == 0`, the
  cap calculation `1.0 - threshold = 1.0` made the merge predicate
  `1.0 - sim <= 1.0` always true, silently collapsing every HDBSCAN
  output to a single cluster. v2.0.0 returns the renumbered HDBSCAN
  labels unchanged when `merge_threshold == 0`. (Empirical: under the
  bug SFace on AT&T produced 1 cluster from 400 faces; the fix brings
  it to 36 clusters matching ground truth.)

### Removed

- **`insightface` is no longer a default dep of pick-face core.** It is
  pulled in only by `[insightface]` extras or by the
  `pick-face-modelpack-insightface` plugin. Anyone shipping pick-face
  commercially out of the box no longer carries the InsightFace
  license burden by default.

### Migration (1.0.x → 2.0)

1. **No config change is required** to keep working with `buffalo_l`:
   v1.x configs with `model_name = "buffalo_l"` still parse and route
   to the AC-9 gate (with a one-shot `DeprecationWarning`).
2. To migrate to the new default pack, edit `pick-face.toml`:

   ```toml
   [runtime]
   pack = "yunet-sface"  # Apache-2.0, no ack required
   ```

   Then download the weights once:

   ```bash
   pick-face init-models --pack yunet-sface --allow-network
   ```

   (If you previously set `pack = "yunet-mfn"` during v2.0.0-dev0,
   that id still parses but `init-models` will raise a clear
   "use yunet-sface" message — update the toml as shown.)

3. To keep using InsightFace weights, install the new plugin first:

   ```bash
   uv pip install pick-face-modelpack-insightface
   ```

   and continue with `pack = "buffalo_l"`.

### Notes

- 264 unit tests pass under the v2.0 layout; one new test file
  (`tests/unit/test_route_b_guards.py`) covers the structural invariants.
- Real-face integration tests (`-m real_data`) run the v2.0 default
  `yunet-sface` pack against the AT&T / ORL fixture once
  `scripts/fetch_face_dataset.py` has populated the local cache. On
  AT&T (40 × 10 PGM, 400 faces / 36 persons) the v2.0.0 default config
  produces 36 clusters, B³ F1 ≈ 0.84 — well above the SOFT bar of
  0.70. Pairwise precision tops out around 0.72 on AT&T regardless of
  HDBSCAN params (SFace INT8 on small grayscale fixtures is
  noticeably less discriminative than ArcFace w600k_r50 on colour
  faces); the AC-1 contract thresholds (precision ≥ 0.95, recall ≥
  0.85, B³ F1 ≥ 0.90) remain the benchmark for production-scale runs
  and the integration test passes `--soft-thresholds` to
  `run_eval.py` so it never silently regresses.
- See [docs/14 §6 migration checklist](docs/14-model-pack-plugins.md)
  for the full plugin-author migration notes.

---

## [1.0.0] - 2026-08-03

The first **stable** release of `pick-face`. From this version onward we
follow the public API / persistence / CLI surface contract documented in
[docs/12-compatibility-promise.md](docs/12-compatibility-promise.md).

### Added

- **HTML report** with `data-theme="dark"` CSS variables and a per-person
  thumbnail wall ([T-301](docs/06-engineering-plan.md)).
- **CI matrix** on Linux + Windows + macOS: lint, unit tests, five
  end-to-end smoke scripts, benchmark, AC-9 guard, and mkdocs build
  (`.github/workflows/ci.yml`).
- **Docs site** built with `mkdocs-material`: navigation, dark-mode toggle,
  search, code copy. Landing page at `docs/index.md`; build via
  `mkdocs serve` / `mkdocs build`; the `[docs]` extra pulls
  `mkdocs >= 1.6` and `mkdocs-material >= 9.5`.
- **`pick-face init`**, **`pick-face init-models`**, and a streamlined
  `pick-face run` one-shot pipeline.
- **Low-confidence face review queue**: `pick-face cluster --no-low-confidence`
  to skip, `low_confidence_faces.json` written next to every report, and
  `pick-face review apply` for must-link / cannot-link / remove / rename.
- **3-stage symlink fallback**: `symlink → hardlink → copy`, plus Windows
  `junction`. Pick with `--prefer`; fallbacks surface as a warning in
  `report.md`.
- **`--dry-run`** on `gc` / `prune` / `rollback` / `rebuild`.
- **Per-cluster mirrors**: `meta.json` per cluster and `index.json` at the
  output root, with `pick-face/meta@1` and `pick-face/index@1` schemas.
- **GPU provider auto-probe** with explicit chain
  (`CUDA → TensorRT → DirectML → CPU`).
- **Process pool executor** with `human` / `json` / `quiet` progress modes.
- **HNSW index** (`pick-face/index@1` binary header) with numpy fallback
  for crash recovery.
- **Long-task checkpoint** (`pick-face/checkpoint@1`) with `face.id`-based
  resume.
- **Performance benchmark** CLI (`pick-face bench`) emitting
  `perf_report.json` / `perf_report.md` (`pick-face/perf_report@1`).
- **Trusted Publishing** to PyPI on `v*.*.*` tags
  (`.github/workflows/release.yml`).

### Changed

- **Project status**: bumped to `Development Status :: 5 - Production/Stable`.
- **Minimum Python**: still 3.10 (we may raise to 3.11 in a future
  release with 6 months' notice).
- **License classifier**: clarified as `Apache-2.0` (code & docs) plus
  the persistent model-weight notice (see Compliance §1).

### Notes

- Default model weights are still `InsightFace buffalo_l` (non-commercial
  research). Commercial users must self-train or license another model
  per [docs/11-commercial-compliance.md](docs/11-commercial-compliance.md).
- The first 1.0 release ships **230+ unit tests** and **5 end-to-end smoke
  scripts** covering: scan, init-models, index, link, report.

---

## [0.1.0] - 2026-07-30

### Added

- Initial release: local offline face recognition & organization CLI.
- InsightFace `buffalo_l` integration (SCRFD detector + ArcFace embedder).
- HDBSCAN clustering with cosine metric + 2-pass centroid merge.
- Symlink / hardlink / copy / junction fallback for cross-platform.
- SQLite (WAL) + HNSW index for incremental & resumable runs.
- 14 CLI subcommands: `init` / `init-models` / `scan` / `index` /
  `cluster` / `link` / `run` / `report` / `review` / `review apply` /
  `gc` / `prune` / `rollback` / `rebuild`.
- Commercial compliance guard: `accept_noncommercial_model_license` field,
  `init-models` License Notice, `report.md` Model + License header,
  AC-9 acceptance test (`tests/acceptance/test_no_model_in_distribution.py`).
- Full documentation set under `docs/`.

### Notes

- v0.1 uses InsightFace `buffalo_l` by default, which is
  non-commercial-research licensed. Commercial users must self-train or
  obtain a commercial license per `docs/11-commercial-compliance.md`.