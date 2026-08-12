# pick-face

> **Self-hosted, local-first face-photo gallery web app.**
> Point it at a directory of photos → it builds a face-clustered virtual
> album you can browse in your browser with a full-screen viewer
> (next/prev, pinch-zoom, swipe).

```
   ┌─────────────┐       ┌──────────────────┐
   │  Browser SPA │ HTTP  │  pick-face-web   │
   │  React+Vite  │ ◀──▶  │  FastAPI + worker │
   │  +shadcn/ui  │ SSE    └─────────┬────────┘
   │  +Tailwind   │                   │
                ┌──────────────────┴──────────────────┐
                ▼                                     ▼
        /mnt/photos/2024/                  ~/.pick-face/data/
        /mnt/photos/2025/                  ├── index.sqlite
                                           ├── index.hnsw
                                           ├── chips/        # face chips (album covers)
                                           ├── thumbnails/   # 256×256 photo thumbs
                                           └── covers/       # per-person cover files
```

**Highlights**
- **Local-first & offline** — once model weights are downloaded, no internet needed
- **Commercially friendly by default** — `yunet-sface` (MIT) ships in core; `yunet-arcface` (Apache-2.0) optional for x86 + GPU
- **Face-clustered virtual albums** — auto-groups every photo by person
- **Incremental** — `watchdog` watches your scan paths; new photos appear automatically
- **Multi-source aggregation** — multiple directories, one album
- **Originals stay where they are** — photos stream over HTTP Range; nothing copied to the data dir (except thumbnails + face chips + person covers)

---

## ⚠ License

The `pick-face` **code** is Apache-2.0.

**Default model pack `yunet-sface`** (OpenCV Zoo per-model MIT) and the
optional **`yunet-arcface`** high-precision tier (ONNX Model Zoo
Apache-2.0 + MIT detector) are both **commercial-friendly out of the box**
— no acknowledgment required.

Opt-in InsightFace packs (`buffalo_l` / `buffalo_sc` / `antelopev2`) via
`pip install pick-face-modelpack-insightface` are NC-research and require
explicit `accept_noncommercial_model_license = true` plus typing
"I AGREE". See [docs/11-commercial-compliance.md](docs/11-commercial-compliance.md).

| Asset | License | Commercial OK? |
|---|---|---|
| `pick-face` code & docs | Apache-2.0 | ✅ |
| **Default pack `yunet-sface`** (OpenCV Zoo) | **MIT** | **✅** |
| **High-precision tier `yunet-arcface`** (ONNX Model Zoo) | **Apache-2.0 + MIT** | **✅** |
| `onnxruntime`, `hnswlib`, `hdbscan`, FastAPI, watchdog | MIT / BSD | ✅ |
| `buffalo_*` weights (opt-in) | **InsightFace NC-research** | **❌** |

---

## 5-minute quickstart (Docker)

```bash
docker run -d \
  --name pick-face \
  -p 8000:8000 \
  -v /mnt/photos:/photos:ro \
  -v ~/.pick-face:/data \
  -e PICK_FACE_HOME=/data \
  pick-face/web:latest
```

Open `http://localhost:8000`, add `/photos` as a scan path, click
**Scan**. New photos added later are auto-detected.

## 5-minute quickstart (uv, bare metal)

```bash
# 1. Install
uv venv
uv pip install -e ".[web,heic]"

# 2. Initialize config (interactive)
pick-face-web init                          # creates ~/.pick-face/config/config.toml

# 3. Download default model weights (~10 MB, MIT)
pick-face-web init-models --allow-network   # lands in ~/.pick-face/cache/models/

# 4. Serve
pick-face-web serve --host 0.0.0.0 --port 8000
# Open http://localhost:8000
```

## Switch to high-precision tier

```bash
# Edit ~/.pick-face/config/config.toml
[runtime]
pack = "yunet-arcface"

[clustering]
merge_threshold = 0.55      # 512-D cosine hint

# Re-download weights
pick-face-web init-models --quant int8 --allow-network   # ~66 MB, ARM-friendly
# or
pick-face-web init-models --quant fp32 --allow-network   # ~261 MB, x86 + GPU
```

## CLI mode (v2.x compatible)

```bash
# pick-face CLI still works for one-shot scans
pick-face run --src /mnt/photos -o /tmp/by_face/
```

See [docs/12-compatibility-promise.md](docs/12-compatibility-promise.md) for
the full v2.x → v3.x compatibility contract: which commands still work,
which moved, and which were retired.

---

## What you get

```
Browser
  /              — overview, scan controls, recent activity
  /persons       — virtual-album list (sorted by representative photo + count)
  /persons/{id}  — single-person waterfall (all photos where this person appears)
  /persons/{id}/photos/{photoId}
                  — full-screen viewer (←/→/Space, double-click zoom, drag-pan,
                    pinch/swipe on touch, F for fullscreen, Esc to exit)
  /settings      — scan path whitelist, model pack, thresholds
```

Original photos are **never copied** to the data dir; the viewer streams
them via HTTP Range. Only `data/thumbnails/` (256×256) + `data/chips/`
(112×112 face crops, used as per-person covers) + `data/covers/`
(cached per-person cover files) land in `~/.pick-face/data/`.

## Where everything lives

All persistent state lives under one application root:

```
~/.pick-face/                              # = PICK_FACE_HOME default
├── config/config.toml                     # editable
├── data/                                  # backup this = backup the whole album
│   ├── index.sqlite
│   ├── index.hnsw
│   ├── chips/                             # 112×112 face crops → album covers
│   ├── thumbnails/                        # 256×256 photo thumbs
│   ├── covers/                            # cached per-person cover files
│   ├── jobs/                              # scan task state
│   └── logs/
└── cache/                                 # disposable, redownloadable
    ├── models/                            # ONNX weights (SHA256-pinned)
    └── tmp/
```

Override the root via `PICK_FACE_HOME` env var (Docker, multi-instance) or
`[server] data_dir` in config.toml. Uninstall = `rm -rf ~/.pick-face`,
no residue.

---

## Hardware

| Device | Default pack | High-precision |
|---|---|---|
| Raspberry Pi 4B 4-8 GB / Pi 5 | `yunet-sface` (MIT) | `yunet-arcface --quant int8` |
| RK3588 / Orange Pi 5 | `yunet-sface` (CPU) | `yunet-arcface --quant int8` |
| Apple Silicon (M1/M2/M3) | `yunet-sface` (CoreML EP) | `yunet-arcface --quant fp32` |
| x86-64 + NVIDIA | `yunet-sface` (default) | `yunet-arcface --quant fp32` (CUDA EP) |
| NAS (Synology / QNAP) | `yunet-sface` | not recommended |

See [docs/13-raspberry-pi-support.md](docs/13-raspberry-pi-support.md) for
the full matrix + Docker perf baselines.

---

## Documentation

| | |
|---|---|
| [docs/01-product-requirement.md](docs/01-product-requirement.md) | User stories, AC-W1..W9, out-of-scope |
| [docs/02-technical-pre-research.md](docs/02-technical-pre-research.md) | Stack choice rationale |
| [docs/03-architecture-design.md](docs/03-architecture-design.md) | FastAPI app + worker + SPA layout |
| [docs/04-algorithm-pipeline.md](docs/04-algorithm-pipeline.md) | detect → align → embed → cluster |
| [docs/05-data-and-storage.md](docs/05-data-and-storage.md) | SQLite schema, HNSW, thumbnails |
| [docs/06-engineering-plan.md](docs/06-engineering-plan.md) | M6+ milestones |
| [docs/09-face-recognition-pipeline.md](docs/09-face-recognition-pipeline.md) | End-to-end walkthrough |
| [docs/11-commercial-compliance.md](docs/11-commercial-compliance.md) | License / AC-9 |
| [docs/13-raspberry-pi-support.md](docs/13-raspberry-pi-support.md) | Pi / ARM matrix |
| [docs/14-model-pack-plugins.md](docs/14-model-pack-plugins.md) | ModelPack Protocol |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common errors + fixes |
| [docs/ARCHIVE-NOTES.md](docs/ARCHIVE-NOTES.md) | v2.x CLI design (archived) |

---

## Development

```bash
# Backend
uv pip install -e ".[dev,docs,web]"
ruff check src tests
pytest -q                                 # 288+ unit tests

# Frontend (SPA, React + Vite + TS + shadcn/ui)
cd src/web
pnpm install
pnpm run dev          # http://localhost:5173 (proxies API to 8000)
pnpm run gen-api      # OpenAPI → TypeScript client
pnpm dlx shadcn@latest add dialog  # 添加新的 shadcn/ui 组件

# Docs site
mkdocs serve         # http://localhost:8001
```

---

## License

- Code: Apache-2.0
- Default model pack `yunet-sface`: MIT (commercial-friendly)
- High-precision tier `yunet-arcface`: Apache-2.0 (commercial-friendly)
- Opt-in `buffalo_*`: InsightFace NC-research — see
  [docs/11-commercial-compliance.md](docs/11-commercial-compliance.md)