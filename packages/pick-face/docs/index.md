# pick-face

> **Local-first face-photo gallery, served as a self-hosted web app.**
> Point it at a directory of photos → it builds a face-clustered virtual
> album, browsable in your browser with full-screen viewer, gestures,
> and incremental updates.

---

## ⚠ License notice — read this first

The `pick-face` **code** is Apache-2.0; you may use it freely including
in commercial products.

The **default model pack** (`yunet-sface`, OpenCV Zoo YuNet + SFace INT8,
per-model MIT) and the **high-precision tier** (`yunet-arcface`, ONNX
Model Zoo ArcFace R100, Apache-2.0 + MIT detector) are both
**commercial-friendly** — no acknowledgment required. You can deploy
pick-face in commercial products out of the box with no extra license work.

If you opt into the **InsightFace** model pack (`buffalo_l` / `buffalo_sc` /
`antelopev2`) via `pip install pick-face-modelpack-insightface`, those
weights are under
**[InsightFace's non-commercial-research terms](https://github.com/deepinsight/insightface/blob/master/LICENSE)**
and require explicit `accept_noncommercial_model_license = true`.

See [Commercial compliance](11-commercial-compliance.md) for the four
legal paths to commercial deployment. pick-face refuses to download
NC-research weights unless you pass `--allow-network` and explicitly type
`I AGREE`.

| Asset | License | Commercial OK? |
|---|---|---|
| `pick-face` code & docs | Apache-2.0 | ✅ |
| **Default pack `yunet-sface`** (OpenCV Zoo) | **MIT** | **✅** |
| **High-precision tier `yunet-arcface`** (ONNX Model Zoo) | **Apache-2.0** | **✅** |
| `onnxruntime`, `hnswlib`, `hdbscan`, Pillow, OpenCV | MIT / Apache-2.0 / BSD | ✅ |
| `fastapi`, `uvicorn`, `watchdog` | MIT / BSD | ✅ |
| `insightface` Python package (opt-in plugin code) | MIT | ✅ |
| `buffalo_l` / `buffalo_sc` / `antelopev2` weights (opt-in) | **InsightFace non-commercial-research** | **❌** |

---

## 5-minute quickstart

### Docker (recommended)

```bash
docker run -d \
  --name pick-face \
  -p 8000:8000 \
  -v /mnt/photos:/photos:ro \
  -v ~/.pick-face:/data \
  -e PICK_FACE_HOME=/data \
  pick-face/web:latest

# Open http://localhost:8000 → configure /photos path → click "Scan"
```

### Bare metal (uv)

```bash
# 1. Install with uv
uv venv
uv pip install -e ".[web,heic]"

# 2. Initialize config (interactive; creates ~/.pick-face/config/config.toml)
pick-face-web init

# 3. Download default model weights (yunet-sface ~10 MB, MIT)
pick-face-web init-models --allow-network

# 4. Serve the web app (port 8000)
pick-face-web serve --host 0.0.0.0 --port 8000
# Open http://localhost:8000 → add /mnt/photos path → click "Scan"
```

### Switch to high-precision tier

```bash
# Edit ~/.pick-face/config/config.toml
[runtime]
pack = "yunet-arcface"

[clustering]
merge_threshold = 0.55      # 512-D cosine hint

# Re-download weights (~66 MB INT8 / ~261 MB FP32)
pick-face-web init-models --quant int8 --allow-network
```

### CLI mode (v2.x compatible)

```bash
# pick-face CLI still works for one-shot scans
pick-face run --src /mnt/photos -o /tmp/by_face/
```

---

## What you get

```
Browser → http://localhost:8000
   /persons              # 虚拟相册列表（按"代表性图片 + 该人照片数"排序）
   /persons/{id}         # 单人瀑布流
   /persons/{id}/photos  # 查看器（上一张/下一张/缩放/手势）
   /settings             # 路径白名单 / 模型包 / 阈值配置
```

---

## Documentation map

**Start here:**

- [Product requirement (PRD)](01-product-requirement.md) — what
  pick-face v3 does, user stories, acceptance criteria, out-of-scope.
- [Architecture design](03-architecture-design.md) — FastAPI app +
  worker + SPA module layout, HTTP API contract.
- [Commercial compliance](11-commercial-compliance.md) — read this
  **before** shipping anything for paid use.

**Engineering:**

- [Algorithm pipeline](04-algorithm-pipeline.md) — detect → align →
  embed → cluster → review. Web service timing notes (long-lived sessions,
  watchdog triggers).
- [Data & storage](05-data-and-storage.md) — SQLite schema, HNSW
  persistence, thumbnail layout, v2 → v3 migration.
- [Face recognition walkthrough](09-face-recognition-pipeline.md) —
  end-to-end read of every step (best onboarding doc).
- [Engineering plan](06-engineering-plan.md) — M6+ milestones (Web
  service build-out).
- [Risks & decisions (ADRs)](07-risk-and-decisions.md) — current
  decision log.

**Models & deployment:**

- [Technical pre-research](02-technical-pre-research.md) — stack
  choice rationale (FastAPI, SQLite, watchdog, etc.).
- [Model pack plugins](14-model-pack-plugins.md) — `ModelPack`
  Protocol, entry-points contract, multi-quant support.
- [Raspberry Pi / ARM support](13-raspberry-pi-support.md) — Pi 4B/5,
  RK3588, Apple Silicon compatibility matrix, Docker perf baselines.
- [Compatibility promise](12-compatibility-promise.md) — what stays
  stable across v2.x → v3.

**Operational:**

- [Troubleshooting](troubleshooting.md) — common errors with copy-paste
  fixes.
- [AGENTS index](AGENTS.md) — entry point for AI agents / contributors.
- [Archive: M5 CLI era](archive/m5-cli/) — historical CLI design docs.

---

## Development

```bash
uv pip install -e ".[dev,docs,web]"
ruff check src tests
ruff format --check src tests
pytest -q                              # 288+ unit tests
mkdocs serve                           # docs site at :8000
mkdocs build                           # static site under site/
```

Frontend (SPA: React + Vite + TS + shadcn/ui + Tailwind) — v4 monorepo,
lives at the repo root in `packages/web-ui/`:

```bash
cd packages/web-ui          # from the repo root
pnpm install
pnpm run dev          # http://localhost:5173 (proxies API to 8000)
pnpm run build        # → ../pick-face/src/pick_face/web/static/
pnpm run gen-api      # OpenAPI → TypeScript client
pnpm dlx shadcn@latest add dialog   # add new shadcn/ui component
```

---

## License

- Code: Apache-2.0
- Docs: Apache-2.0
- Default model pack `yunet-sface`: MIT (commercial-friendly)
- High-precision tier `yunet-arcface`: Apache-2.0 + MIT (commercial-friendly)
- Opt-in `buffalo_l` / `buffalo_sc` / `antelopev2`: NC-research — see
  [Commercial compliance](11-commercial-compliance.md)