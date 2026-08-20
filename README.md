# pick-face monorepo

Local-first face-photo gallery. See [`packages/pick-face/`](packages/pick-face/) for
the Python service and [`packages/web-ui/`](packages/web-ui/) for the SPA.

## Quick start

```bash
# Python service + CLI (pick-face, pick-face-web)
cd packages/pick-face
uv sync
uv run pick-face-web serve --port 8000

# Frontend SPA (Vite dev server, optional — pick-face-web already serves the
# built bundle)
cd packages/web-ui
pnpm install
pnpm dev
```

## Repository layout

```
pick-face/
├── packages/
│   ├── pick-face/    # Python wheel (CLI + FastAPI service + Vite static host)
│   └── web-ui/       # React + Vite SPA
├── plugins/          # Third-party Python model-pack plugins
├── scripts/          # Repository-level maintenance scripts
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
