# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
— see [docs/12-compatibility-promise.md](docs/12-compatibility-promise.md) for
the full policy.

---

## [4.0.1] - 2026-08-20 — **SSE-driven scan state (polling removed)**

Replaced the 2-second polling of `/api/scan/jobs/active` with a push-based
Server-Sent Events stream. The ScanProgressBanner now updates only when
the active job actually changes — no more hammering the backend every
2 seconds while the user sits on the gallery page.

### Changed

- **New endpoint** `GET /api/scan/events` — global SSE stream of the
  active scan job. Emits `event: snapshot` on connect (current job or
  `null`), `event: job_update` whenever the active job's identity /
  state / progress changes, and `event: ping` every 15 s as a
  heartbeat. The per-job stream `GET /api/scan/jobs/{id}/events`
  (M8-T-8) is unchanged and still drives the fine-grained cluster
  events consumed by `usePersonsLiveInvalidator`.
- **New hook** `useActiveScanJobStream()` (replaces
  `useActiveScanJobQuery`) — opens an EventSource to the new endpoint
  and returns the same `{data: ScanJob | null}` shape. The browser's
  built-in auto-reconnect covers transient network drops.
- **`ScanState` zod enum** now uses lowercase values (`"running"`,
  `"done"`, …) to match the backend's `ScanState.value` wire format.
  Earlier versions silently dropped `state` on every payload (zod's
  default strip), so the banner never showed the spinner even when a
  scan was in flight. Now it does.
- **`ScanJobSchema`** now also accepts `eta_sec` (new on the backend)
  and `paths` (optional — older polling payloads may omit it).

### Removed

- `useActiveScanJobQuery` (polling hook) and `api.getActiveScanJob`
  (frontend wrapper for `/jobs/active`). The REST endpoint itself is
  still served by the backend and remains useful for `curl` / scripts.
- `useStartScanMutation`'s `onSuccess` cache invalidation — the global
  SSE pushes a fresh `job_update` automatically when the runner
  transitions the new job to `running`.

### Migration notes

- No data migration needed.
- All 443 backend tests + 74 frontend tests pass (1 skip: heic extra).
- 2 new backend tests (global SSE emits snapshot + on-change
  job_update; null snapshot when no active job) and 4 new frontend
  schema tests for the global-stream payload shape.

---

## [4.0.0] - 2026-08-20 — **Monorepo organization**

Restructured the project into a pnpm workspace without changing any
functionality, APIs, or commands.

### Changed

- **Monorepo layout**: project is now a pnpm workspace with two packages:
  - `packages/pick-face/` — Python wheel (`pick-face` + `pick-face-web`).
    `src/`, `tests/`, `pyproject.toml`, `uv.lock`, `scripts/`, `docs/`,
    `LICENSE`, `README.md`, `CHANGELOG.md`, `mkdocs.yml` all live here.
  - `packages/web-ui/` — React + Vite SPA (`@pick-face/web-ui`). Previously
    embedded at `src/pick_face/web/app/`; now an independent workspace member.
  - Root: `pnpm-workspace.yaml`, root `package.json`, root `pnpm-lock.yaml`
    (workspace lockfile), `.gitignore` updated to monorepo paths.
- **Vite build target**: `packages/web-ui/` builds to
  `packages/pick-face/src/pick_face/web/static/` so the wheel still ships
  the SPA bundle (`uv build` unchanged).
- **CI**: `working-directory` set to `packages/pick-face/` or
  `packages/web-ui/` per job; cache dependency path is the root
  `pnpm-lock.yaml`.

### Migration notes

- Existing `data/` directory (`pick-face.db` + `index.hnsw`) is unchanged.
- Existing `~/.pick-face/config.toml` is unchanged.
- Development commands now require `cd packages/pick-face` or
  `cd packages/web-ui` before `uv run …` / `pnpm …`.
- `pick-face` and `pick-face-web` console scripts work unchanged
  (wheel entry points preserved).
- All 433 backend tests + 70 frontend tests pass (1 skip: heic extra)
  with only path-depth adjustments in 7 test files.

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

### M7 — Web SPA + image viewer (M6 scaffold completion)

The M7 milestone ships the **complete M6 SPA scaffold + photo viewer**.
The backend was already service-ready in M6; M7 adds a real Vite + React
+ TypeScript SPA at `src/pick_face/web/app/`, a working `FaceViewer`
with keyboard / wheel / drag / fullscreen / touch gestures, SSE-driven
scan progress, and CI / release pipelines that build the SPA into the
wheel.

#### What's new

- **SPA scaffold** — Vite 5 + React 18.3 + TypeScript 5.6 + Tailwind v3
  + shadcn/ui (vendored primitives: Button, Card, Input, Dialog, Skeleton,
  Tabs, Switch, Progress, Label, Badge, Toaster). `pnpm-lock.yaml` is
  committed for reproducible CI installs.
- **Routing** — `createBrowserRouter` with four routes: `/` → `/persons`,
  `/persons` (waterfall grid), `/persons/:id` (per-person waterfall +
  FaceViewer via `?photo=X` deep link), `/settings` (Paths / Scan / Model
  tabs), plus a 404.
- **API client** — 14 endpoints hand-typed with `zod` schemas
  (`src/pick_face/web/app/src/lib/api/schemas.ts`) wrapped in TanStack
  Query hooks. Image bytes flow through the browser natively (Range
  requests handled by FastAPI's `StreamingResponse`).
- **`<FaceViewer>`** — keyboard (`←/→/Space/PageUp/PageDown/+/-/0/f/Esc`),
  mouse wheel zoom around the cursor, drag pan with edge clamping,
  double-click toggles fit ↔ 2×, fullscreen via the browser Fullscreen
  API, touch pinch / swipe / tap via `@use-gesture/react`. URL state:
  `/persons/:id?photo=N` opens the viewer at photo N — back button closes
  it without losing scroll position. Lazy-loaded so the gesture handler
  cost is only paid on the detail route.
- **`<FaceOverlay>`** — landed as a no-op SVG component (M7.5 fills
  bbox drawing once `/api/photos/{id}/metadata` exposes face rectangles).
- **SSE scan progress** — `<ScanProgressBanner>` polls the active scan
  job every 2 s and opens a typed EventSource (`lib/sse.ts`) when one is
  RUNNING. Renders shadcn `Progress` with `processed/total`. On
  terminal events, toasts (placeholder — M7.5 wires sonner).
- **CI** — new `frontend-build` job runs `pnpm install --frozen-lockfile`
  and `pnpm build` before `unit` and the smoke matrix. `frontend-test`
  job runs Vitest. `release.yml` runs `pnpm build` before `uv build` so
  the published wheel always ships the SPA bundle. `pyproject.toml`
  excludes `web/app/**` and `web/static/**` from sdist (sdist stays
  source-only; wheel automatically picks up `web/static/`).
- **Test coverage** — 19 Vitest cases (component + store + helpers) +
  3 pytest cases (`tests/unit/test_vite_build_artifacts.py`) guarding
  that `web/static/index.html` exists post-build and carries no `.onnx`.

#### Deferred to M7.5

- `<FaceOverlay>` bbox rendering (needs `/api/photos/{id}/metadata`).
- EXIF side-sheet on `/persons/:id`.
- PWA manifest + service worker.
- Playwright E2E.
- Sonner-based toast wrapper, `cmdk` global search, NC-research `Badge`
  on the Model tab.

#### Files touched

| Category | New | Modified |
|---|---|---|
| Source | `src/pick_face/web/app/**` (~40 files) | `src/pick_face/web/__init__.py` |
| Workflows | — | `.github/workflows/{ci,release}.yml` |
| Build | — | `pyproject.toml`, `.gitignore` |
| Tests | `tests/unit/test_vite_build_artifacts.py` | `tests/unit/test_vite_build_artifacts.py` |
| Docs | — | `README.md`, `docs/03-architecture-design.md`, `docs/06-engineering-plan.md`, `CHANGELOG.md` |

### M7.5 — FaceOverlay bbox rendering + EXIF side-sheet (M7 hand-off)

Fills the three M7.5 tasks that needed backend metadata extension. The
viewer now draws real face bboxes and the `/persons/:id` page exposes
extended photo metadata via a right-side drawer.

#### What's new

- **`/api/photos/{id}/meta` extended** — now returns
  `natural_width`, `natural_height`, and `faces[]` (each with `bbox`,
  `cluster_id`, `det_score`, `quality`). Service layer:
  `pick_face.service.photo_service.get_photo_metadata()` opens the
  image with PIL to read natural dimensions and joins the `face` table
  for detected faces.
- **`<FaceOverlay>` bbox rendering** — SVG overlay fed from the
  extended metadata. Stroke width scales with `min(naturalW, naturalH)`;
  matching `cluster_id` gets the primary stroke, non-matching gets a
  dimmed muted stroke. Unknown-cluster faces stay full opacity.
  Hooked into `FaceViewer` (M7-T-6) using server-reported natural
  dimensions (PIL fallback) and `<img>.naturalWidth` as a backstop.
- **EXIF side-sheet drawer** — `<PhotoMetaSheet>` on `/persons/:id`,
  opened via an "Info" button in the header. Renders Identity, Image,
  Faces (list with bbox + det_score + quality), and an EXIF
  placeholder (backend doesn't expose EXIF yet). Built on the shadcn
  `Sheet` primitive + Radix Dialog.
- **Typed client mirror** — `PhotoMetadataSchema` + `FaceInPhotoSchema`
  added to `src/pick_face/web/app/src/lib/api/schemas.ts`,
  `usePhotoMetadataQuery` hook + `api.getPhotoMetadata` client.

#### Deferred (still M7.5)

- PWA manifest + service worker (M7-T-9).
- Playwright E2E (M7-T-10).
- Sonner toast wrapper, `cmdk` global search, NC-research `Badge`
  (M7-T-11/12/13).
- Real EXIF fields (camera / GPS / exposure) in the side-sheet —
  needs a separate backend endpoint.

#### Tests added

- 2 pytest cases in `tests/unit/test_api_routes.py` for the extended
  `/meta` (with/without faces).
- 3 pytest cases in `tests/unit/test_service_photo.py` for
  `get_photo_metadata` (with/without faces, 404).
- 8 Vitest cases in `FaceOverlay.test.tsx` for bbox rendering + the
  `highlightClusterId` filter logic.
- 7 Vitest cases in `PhotoMetaSheet.test.tsx` for the drawer
  (loading / error / success / empty-faces / gating by `open`).

Regression: 388 pytest passing (+5), 34 Vitest passing (+15), `pnpm
build` clean (1757 modules, 499 KB JS / 22 KB CSS).

#### Files touched

| Category | New | Modified |
|---|---|---|
| Backend | — | `src/pick_face/service/photo_service.py`, `src/pick_face/api/photos.py` |
| Frontend | `src/pick_face/web/app/src/components/ui/sheet.tsx`, `src/pick_face/web/app/src/components/persons/PhotoMetaSheet.tsx`, `src/pick_face/web/app/src/components/viewer/FaceOverlay.tsx` (+8 tests), `src/pick_face/web/app/src/components/persons/PhotoMetaSheet.test.tsx` (+7 tests) | `src/pick_face/web/app/src/lib/api/{schemas,client,hooks}.ts`, `src/pick_face/web/app/src/components/viewer/FaceViewer.tsx`, `src/pick_face/web/app/src/pages/PersonDetailPage.tsx` |
| Tests | — | `tests/unit/test_api_routes.py`, `tests/unit/test_service_photo.py` |
| Docs | — | `CHANGELOG.md`, `docs/03-architecture-design.md`, `docs/06-engineering-plan.md` |

### M7.6 — Real EXIF in `/api/photos/{id}/meta` + side-sheet

Fills the EXIF placeholder in the `<PhotoMetaSheet>` drawer (M7-T-8).
Unblocks the future cmdk global search (M7-T-12) — EXIF fields will
join the search index.

#### What's new

- **`pick_face.service.photo_service.get_exif(photo_id) → ExifRecord`**
  — reads `Image.getexif()` via PIL, parses rationals (`ExposureTime`
  `(1,200)` → `0.005s`), DMS triples (`(37,30,0)` + `"N"` → `37.5`),
  and `DateTimeOriginal` `"YYYY:MM:DD HH:MM:SS"` → epoch seconds
  (UTC). Strips trailing NULs from `Make`/`Model`. Returns all-`None`
  for stripped JPEGs / PNGs / corrupt files / missing source.
- **`/api/photos/{id}/meta` extended** — adds an `exif` block
  alongside `faces`. Mirrored in zod `ExifSchema` /
  `PhotoMetadataSchema`.
- **`<PhotoMetaSheet>` EXIF section** — replaces the placeholder with
  real rows: Camera (make + model + lens), Taken (locale string),
  Exposure (`1/200s • f/2.8 • ISO 400 • 50mm`), GPS (DMS, signed
  hemisphere). Missing fields are silently dropped; a fully-empty
  EXIF block renders the "No EXIF tags on this photo" placeholder.

#### Tests added

- 6 pytest cases in `tests/unit/test_service_photo.py` for `get_exif`
  (full payload, no tags, partial tags, missing file, 404,
  trailing-NUL stripping).
- 2 pytest cases in `tests/unit/test_api_routes.py` for the new
  `exif` block in `/meta` (full payload + all-null fallback).
- 3 Vitest cases in `PhotoMetaSheet.test.tsx` (all-null placeholder,
  taken-only row, 1s+ exposure formatting). Existing success test
  extended to assert the camera / exposure / GPS rows.

Regression: 396 pytest passing (+8), 37 Vitest passing (+3), `pnpm
build` clean.

#### Files touched

| Category | Modified |
|---|---|
| Backend | `src/pick_face/service/photo_service.py`, `src/pick_face/api/photos.py` |
| Frontend | `src/pick_face/web/app/src/lib/api/schemas.ts`, `src/pick_face/web/app/src/components/persons/PhotoMetaSheet.tsx`, `src/pick_face/web/app/src/components/persons/PhotoMetaSheet.test.tsx` |
| Tests | `tests/unit/test_service_photo.py`, `tests/unit/test_api_routes.py` |
| Docs | `CHANGELOG.md`, `docs/03-architecture-design.md`, `docs/06-engineering-plan.md` |

### M7.7 — `lib/toast.ts` facade over sonner (M7-T-11)

One entry point for every user-facing toast in the SPA. Sonner is
now an implementation detail of `lib/toast.ts`; no component may
import from `"sonner"` directly.

#### What's new

- **`src/pick_face/web/app/src/lib/toast.ts`** — typed facade:
  - `success(msg, opts?)`, `error(msg, opts?)`, `info(...)`,
    `warning(...)` — direct passthroughs with sensible default
    durations (success 4s, error 6s).
  - `fromError(err, fallback?)` — accepts `unknown`, narrows:
    - `ApiError` → title = `body.message`, description = `code:
      <body.code>`, sticky on 5xx, dismissable on 4xx.
    - `Error` → title = `err.message`.
    - `unknown` → title = `fallback` (default `"Something went
      went wrong"`).
  - `toast` object form mirrors the sonner API for ergonomic swap-ins.
- **`<ScanProgressBanner>` migrated** — dropped direct `import
  { toast } from "sonner"`; uses `@/lib/toast` instead. The "New
  scan" button now reports `useStartScanMutation` failures via
  `toast.fromError(e, "Could not start scan")` (previously
  swallowed silently).

#### Tests added

- 8 Vitest cases in `src/lib/toast.test.ts` covering `fromError`
  narrowing for `ApiError` (4xx vs 5xx), `Error`, `string`, and
  `undefined`, plus the `success`/`error` direct helpers.

Regression: 396 pytest passing (unchanged), 45 Vitest passing (+8),
`pnpm build` clean.

#### Files touched

| Category | Modified |
|---|---|
| Frontend | `src/pick_face/web/app/src/lib/toast.ts` (new), `src/pick_face/web/app/src/lib/toast.test.ts` (new), `src/pick_face/web/app/src/components/layout/ScanProgressBanner.tsx` |
| Docs | `CHANGELOG.md`, `docs/03-architecture-design.md`, `docs/06-engineering-plan.md` |

### M7.8 — NC-research Badge on Settings → Model tab (M7-T-13)

The Model tab used to hardcode `<Badge>yunet-sface</Badge>`. It now
consumes the live `active_pack` block from `/api/ready` and renders
a license-class-driven Badge.

#### What's new

- **`/api/ready` extended** — response gains an `active_pack` block
  (`id`, `display_name`, `license_class`, `license_name`,
  `license_spdx`, `nc_research_acknowledged`). `null` when the
  configured pack id doesn't resolve to an installed plugin.
- **`pick_face.api.health._resolve_active_pack(layout)`** — loads
  config, calls `discover_packs()`, looks up `effective_pack_id()`,
  returns `None` on any miss. Honors
  `[runtime] accept_noncommercial_model_license` for the
  `nc_research_acknowledged` flag (the AC-9 gate).
- **`<ModelPackCard>`** — three Badge variants by `license_class`:
  - `permissive` → secondary, no warning.
  - `user-supplied` → outline, neutral.
  - `nc-research` → destructive red.
  Adds an extra destructive `"AC-9 will block scans"` Badge when
  `nc_research_acknowledged === false`. Falls back to a soft
  "No installed model pack detected" placeholder when `pack` is null.
- **`<SettingsPage>`** — wires the card to `useReadyQuery().active_pack`
  and fires a one-time `toast.warning(...)` on mount (guarded by a
  `useRef`) when the gate is unacknowledged, so AC-9 cannot be
  silently bypassed. Both scan buttons route mutation errors through
  `toast.fromError`.
- **zod mirror** — `LicenseClassSchema`, `ActivePackSchema`, and
  `ReadyResponseSchema.active_pack` added to `lib/api/schemas.ts`.

#### Tests added

- 3 pytest cases in `tests/unit/test_api_routes.py`:
  `test_ready_includes_active_pack_permissive`,
  `test_ready_active_pack_handles_unknown_id`,
  `test_ready_active_pack_nc_research_unacknowledged` (uses
  `monkeypatch.setattr("pick_face.platform.pack.discover_packs", ...)`
  to inject a fake NC-research `PackDescriptor` without registering
  a real plugin in the test env).
- 6 Vitest cases in
  `src/pick_face/web/app/src/components/settings/ModelPackCard.test.tsx`
  covering: loading skeleton, unknown-pack placeholder, permissive
  pack (secondary Badge), NC-research acked (destructive Badge, no
  AC-9 warning), NC-research unacked (destructive Badge **plus** AC-9
  warning Badge), user-supplied pack (outline Badge).

Regression: 399 pytest passing (+3), 51 Vitest passing (+6),
`pnpm build` clean.

#### Files touched

| Category | Modified |
|---|---|
| Backend | `src/pick_face/api/health.py` (`_resolve_active_pack` + `/ready` adds `active_pack`) |
| Frontend | `src/pick_face/web/app/src/lib/api/schemas.ts` (`LicenseClassSchema`, `ActivePackSchema`), `src/pick_face/web/app/src/components/settings/ModelPackCard.tsx` (new), `src/pick_face/web/app/src/components/settings/ModelPackCard.test.tsx` (new), `src/pick_face/web/app/src/pages/SettingsPage.tsx` (wires card + AC-9 toast) |
| Tests | `tests/unit/test_api_routes.py` (+3) |
| Docs | `CHANGELOG.md`, `docs/03-architecture-design.md` (§1.4 status, §7.2 table), `docs/06-engineering-plan.md` (§2.1 M7-T-13) |

### M7.9 — PWA manifest + service worker + offline app shell (M7-T-9)

Closes the PRD promise in `docs/01-product-requirement.md:126`
("手机 App: v3 只做 Web；PWA 已能满足 90% 移动端"). pick-face is now
installable, runs offline for the SPA shell + cached thumbnails, and
lets the user check for updates without an auto-reload surprise.

#### What's new

- **`vite-plugin-pwa@^0.21.2` + `workbox-window@^7.3.0`** added as
  devDependencies (no runtime cost — the wheel is unchanged).
- **`public/manifest.webmanifest`** — standalone, scope `/`, theme
  `#2a6df4`, 3 icons (192/512/maskable 512). Icons are pre-generated PNGs
  committed to the repo; a `scripts/build-icons.mjs` recipe (not in CI)
  documents how to rebuild them.
- **`vite.config.ts` — `VitePWA({ registerType: 'prompt',
  injectRegister: 'script', strategies: 'generateSW' })`** emits
  `sw.js` + `registerSW.js` + `workbox-*.js`. Caching:
  - App shell (`navigateFallback: '/index.html'`)
  - `/api/photos/{id}/thumb` → `CacheFirst`, 30 days, 256 entries
  - `/api/persons{,/{id}/photos}` → `StaleWhileRevalidate`, 1 h, 32 entries
  - `/api/photos/{id}` (original, Range) → Workbox's default
    `RangeRequestsPlugin` (no explicit `runtimeCaching` rule, so
    Range responses stream correctly)
  - `/api/scan/jobs/{id}/events` (SSE) → never cached (denied by both
    `navigateFallbackDenylist: [/^\/api\//]` and the absence of a rule)
- **`src/lib/pwa.ts`** — single side-effect entry point. Production-gated
  via `import.meta.env.PROD`. `onNeedRefresh` →
  `toast.info("New version available", { duration: 0, action: { label:
  "Reload", onClick: updateSW(true) } })`; `onOfflineReady` →
  `toast.success("Ready to work offline")`. `refreshPwa()` exposes a
  manual "check + apply, no reload" hook for the Settings button.
- **`<InstallAppButton>`** — captures `beforeinstallprompt`, only
  renders the button when the event fires and `matchMedia("(display-mode:
  standalone)")` is false. Click → `evt.prompt()` → toast with the
  user-choice outcome. No auto-prompt — install is user-initiated.
- **`<PwaSettingsCard>`** + **Settings → App tab** (4th tab) — wraps
  the install button and a "Check for update" button.
- **`toast.ts` ToastOptions** gained an optional `action: { label,
  onClick }` slot so the SW update prompt can render an inline button
  via sonner's native action API (no second toaster layer).

#### Tests added

- 6 Vitest cases in
  `src/components/settings/InstallAppButton.test.tsx`:
  hidden-before-event, hidden-when-standalone, renders-after-event,
  click-prompt-success, click-prompt-dismissed, appinstalled-hides.
- 2 Vitest cases in
  `src/components/settings/PwaSettingsCard.test.tsx`: renders the PWA
  badge + check-update button; click → `refreshPwa()`.
- 3 Vitest cases in `src/lib/pwa.test.ts`: `initPwa()` no-op in dev,
  idempotent across calls, `refreshPwa()` resolves undefined.
- `src/test-setup.ts` — stubs `navigator.serviceWorker` and adds
  `vi.restoreAllMocks()` in `afterEach` (jsdom doesn't ship service
  worker, the new tests need it).
- `vitest.config.ts` — aliases `virtual:pwa-register` to a tiny shim
  (`src/test-shims/pwa-register.ts`) since the VitePWA virtual module
  only resolves at build time, not under vitest.

Regression: 399 pytest passing (unchanged — no Python touched),
62 Vitest passing (+11), `pnpm build` emits
`sw.js` + `registerSW.js` + `workbox-*.js` + `manifest.webmanifest`
+ `icons/icon-{192,512,mask}.png` into `web/static/` (all 4 PNG/SW
paths verified gitignored via `git check-ignore -v`).

#### Files touched

| Category | Modified |
|---|---|
| Build | `src/pick_face/web/app/vite.config.ts` (VitePWA plugin), `src/pick_face/web/app/index.html` (`<link rel="manifest">` + `theme-color`), `src/pick_face/web/app/vitest.config.ts` (virtual:pwa-register shim) |
| Frontend | `src/pick_face/web/app/src/lib/pwa.ts` (new), `src/pick_face/web/app/src/lib/toast.ts` (`action` slot), `src/pick_face/web/app/src/main.tsx` (side-effect import), `src/pick_face/web/app/src/vite-env.d.ts` (triple-slash reference), `src/pick_face/web/app/src/pages/SettingsPage.tsx` (4th tab), `src/pick_face/web/app/src/components/settings/InstallAppButton.tsx` (new), `src/pick_face/web/app/src/components/settings/PwaSettingsCard.tsx` (new), `src/pick_face/web/app/src/test-setup.ts` (serviceWorker stub) |
| PWA assets | `src/pick_face/web/app/public/manifest.webmanifest` (new), `src/pick_face/web/app/public/icons/icon-{192,512,mask}.png` (new) |
| Tests | `src/pick_face/web/app/src/lib/pwa.test.ts` (new), `src/pick_face/web/app/src/components/settings/InstallAppButton.test.tsx` (new), `src/pick_face/web/app/src/components/settings/PwaSettingsCard.test.tsx` (new) |
| Repo | `.gitignore` (widened `web/static/` → directory form), `src/pick_face/web/app/package.json` (+ `vite-plugin-pwa`, `workbox-window`), `pnpm-lock.yaml` |
| CI | `.github/workflows/ci.yml` + `.github/workflows/release.yml` (4-file `test -f` guard for PWA artifacts) |
| Docs | `CHANGELOG.md`, `docs/03-architecture-design.md` (§7 status), `docs/06-engineering-plan.md` (§2.1 M7-T-9 row + §2.2 AC-W10) |

---

### M8 — Incremental scan + watchdog + periodic recluster + soft-delete + SSE events

#### What's new

- **Incremental ingestion, two paths to one consumer.** `service/file_watcher.py` (watchdog → `asyncio.Queue[Path]` → `ScanService.start(paths=[p], kind="path_only")`) covers local filesystems; `service/polling_scheduler.py` (APScheduler `IntervalTrigger(seconds=incremental_interval_sec)`) covers Docker bind mounts / NFS / FUSE where watchdog is unreliable. 5-second debounce collapses a 50-file burst into one job. Both paths reuse the existing `run_scan` worker (no new embedder pipeline, per the locked decision in `docs/06 §3.3`).
- **Cluster worker** (`worker/cluster_worker.py`) — two triggers: `recluster_interval_hours` for full HDBSCAN re-cluster, and a `recluster_threshold` (default 50) counter for incremental `incremental_assign` (the M2 helper that had never been wired). Registers on `ScanRunner._on_scan_complete` so every DONE scan feeds the unclustered counter.
- **HNSW persistence** (`HnswIndex.add_items + save` after every cluster run; `load()` on startup with `rebuild()` fallback on `ValueError`). Single-task ownership avoids hnswlib's thread-safety caveats.
- **Soft-delete without a schema migration.** `source.status` enum extended with `'removed'` (user-driven, via `DELETE /api/photos/{id}`) and the existing `'missing'` (filesystem-driven, via the new scan-worker DEL pass). No DB-level CHECK constraint; the constant `_VALID_SOURCE_STATUSES` lives in `store/index.py` and is asserted at write sites. `PersonService` joins `source s ON ... AND s.status='active'` on every face JOIN so the SPA waterfall never surfaces ghost thumbnails.
- **`/api/ready` extended** with `checks.queue_depth`, `checks.watcher_status`, `checks.polling_status`, `checks.cluster_worker_status`. Each defaults to `"disabled"` when the component is absent (test mode, pre-init).
- **SSE events piggyback on `/api/scan/jobs/{id}/events`** via a `scan-{id}.events.jsonl` sidecar. The runner appends `new_photo` after every face-bearing image; the cluster worker appends `new_person` / `merged`. The SSE generator tails the sidecar (0.5s poll, seek-forward so reconnect doesn't replay).
- **Frontend live updates** — `usePersonsLiveInvalidator(jobId)` subscribes to the SSE stream and invalidates the `persons` TanStack Query on `new_photo` / `new_person` / `merged`. `ScanProgressBanner` toasts `New photo indexed` (throttled to once per 1.5s) and `New person detected`. Zod schemas in `lib/api/schemas.ts` validate payloads.

#### Configuration changes

- **`[clustering] auto_recluster_min_new = 500`** → **`[clustering] recluster_threshold = 50`**. Aligns the TOML template with the Pydantic schema-of-record (`core/config.py:108 ClusteringConfig.recluster_threshold`). Existing TOMLs that still use the old key keep working — Pydantic's `extra='ignore'` silently drops it and the default (`50`) applies. Rename in your `config.toml` to force it into effect.

#### Acceptance criteria

- **AC-W8** — Drop a file in a whitelisted directory → it appears in `/api/persons` within 30s.
- **AC-W8-SSE** — Watchdog trigger emits at least one `event: new_photo` on `/api/scan/jobs/{id}/events`.
- **AC-W8-DELETE** — `DELETE /api/photos/{id}` returns 204; subsequent reads of `/api/persons` exclude the photo's faces from face_count / cover / photo list.

#### Deferred to M8.5 / M9

- Watchdog events on Linux CIFS shares (still unreliable; polling fallback applies).
- Cross-process ScanRunner (current design is in-process asyncio task).
- Hot-reload of `[scan] incremental_interval_sec` (read once at startup).

#### Files touched

| Module | Files |
|---|---|
| New services | `src/pick_face/service/file_watcher.py`, `src/pick_face/service/polling_scheduler.py` |
| New worker | `src/pick_face/worker/cluster_worker.py` |
| Modified worker | `src/pick_face/worker/scan_worker.py` (DEL pass + sidecar append), `src/pick_face/worker/runner.py` (`on_scan_complete` callback wire) |
| Modified API | `src/pick_face/api/app.py` (lifespan: 4-component wiring), `src/pick_face/api/health.py` (queue depth + worker status), `src/pick_face/api/photos.py` (DELETE route), `src/pick_face/api/scan.py` (SSE sidecar tail) |
| Modified services | `src/pick_face/service/scan_service.py` (`events_file()` accessor + sidecar lifecycle), `src/pick_face/service/photo_service.py` (`soft_delete` + `_mark_removed`), `src/pick_face/service/person_service.py` (active-source filter on every JOIN), `src/pick_face/service/config_service.py` (`recluster_threshold` template + `get_incremental_interval_sec` helper) |
| Modified store | `src/pick_face/store/index.py` (`_VALID_SOURCE_STATUSES` constant) |
| Frontend | `src/pick_face/web/app/src/lib/sse.ts` (typed `new_photo` / `new_person` / `merged` handlers), `src/pick_face/web/app/src/lib/api/schemas.ts` (event Zod schemas), `src/pick_face/web/app/src/lib/api/hooks.ts` (`usePersonsLiveInvalidator`), `src/pick_face/web/app/src/components/layout/ScanProgressBanner.tsx` (toast + invalidator wiring) |
| Tests | `tests/unit/test_file_watcher.py` (new, 5), `tests/unit/test_polling_scheduler.py` (new, 4), `tests/unit/test_cluster_worker.py` (new, 9), `tests/unit/test_soft_delete.py` (new, 5), `tests/unit/test_scan_sse.py` (new, 4); `tests/unit/test_api_routes.py` (+3), `tests/unit/test_index_hnsw.py` (+4), `tests/integration/test_web_smoke.py` (+3); frontend `src/pick_face/web/app/src/__tests__/sse.test.ts` (new, 3), `ScanProgressBanner.test.tsx` (+2) |
| Docs | `CHANGELOG.md`, `docs/05-data-and-storage.md` (§2.1 source.status extension), `docs/06-engineering-plan.md` (§3.1 status table + §3.3 implementation notes + §3.4 failure modes) |

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