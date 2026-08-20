# pick-face monorepo

Local-first face-photo gallery. See [`packages/pick-face/`](packages/pick-face/) for
the Python service and [`packages/web-ui/`](packages/web-ui/) for the SPA.

## Quick start

### One-shot dev server (recommended)

From the repo root, run `pnpm dev` — it boots the FastAPI service
(with `--reload`) and the Vite dev server (with HMR) in parallel,
prefixed with `web` / `api` log tags:

```bash
pnpm install                            # one-time: install concurrently + web-ui deps
pnpm dev                                # → http://localhost:5173 (Vite dev with proxy → :8000)
```

The Vite dev server proxies `/api/*` to `localhost:8000`, so the SPA
hot-reloads on source changes while the backend auto-reloads on Python
file changes. Press Ctrl-C once to stop both.

### Manual / split (only if `pnpm dev` is unavailable)

```bash
# Terminal A — backend
cd packages/pick-face
uv sync
uv run pick-face-web serve --port 8000

# Terminal B — frontend (Vite dev server, optional)
cd packages/web-ui
pnpm install
pnpm dev
```

## Repository layout

```
pick-face/
├── packages/
│   ├── pick-face/    # Python wheel (CLI + FastAPI service + Vite static host)
│   │   ├── scripts/  # Maintenance scripts (fetch_face_dataset.py, pin_sha256.py)
│   └── web-ui/       # React + Vite SPA
├── plugins/          # Third-party Python model-pack plugins
└── pick-face.toml    # Example user config (copy to ~/.pick-face/config.toml)
```

## Building a release wheel

The release wheel ships the built SPA under `web/static/`. CI runs the frontend
build first, then `uv build`:

```bash
cd packages/web-ui && pnpm install && pnpm build    # writes ../pick-face/src/pick_face/web/static/
cd ../pick-face && uv build                        # produces the wheel
```

See [`packages/pick-face/README.md`](packages/pick-face/README.md) for the
project's full description, features, and license.
