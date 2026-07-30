# pick-face

> **Local offline image face recognition & organization CLI.**
> Scan multiple directories → detect & embed faces → cluster by person →
> output `<output>/person-XXXX/<src_rel_path>` symlinks.

## ⚠ License notice (READ FIRST)

`pick-face` code is **Apache-2.0**, free for any use including commercial.

The **default model weights** (`InsightFace buffalo_l`) are **NOT** distributed
with this project and are licensed under
**[InsightFace's non-commercial-research terms](https://github.com/deepinsight/insightface/blob/master/LICENSE)**.

**If you use pick-face commercially** (company-internal tool, paid SaaS,
revenue-supporting product, etc.) you **must** self-train or license
another model. See **[docs/11-commercial-compliance.md](docs/11-commercial-compliance.md)**
for the three legal paths. The project authors make **no** representation
about your right to use the default model weights.

## 5-minute quickstart

```bash
# 1. Install (uses uv — see docs/AGENTS.md)
uv venv
uv pip install -e ".[dev,heic]"

# 2. Generate default config
pick-face init

# 3. Edit pick-face.toml — confirm model choice
#    (default: accept_noncommercial_model_license = false)
#    For personal/research use, set it to true.

# 4. Download model (requires --allow-network + I AGREE)
pick-face init-models --allow-network

# 5. Scan + index + cluster + link
pick-face run --src ~/Photos --out ~/Photos/by_face
```

## Documentation

- **[docs/AGENTS.md](docs/AGENTS.md)** — entry point, full doc index
- **[docs/11-commercial-compliance.md](docs/11-commercial-compliance.md)** —
  commercial deployment compliance (single source of truth)
- **[docs/03-architecture-design.md](docs/03-architecture-design.md)** —
  system architecture & module layout
- **[docs/05-data-and-storage.md](docs/05-data-and-storage.md)** — SQLite /
  HNSW / symlink strategy
- **[docs/09-face-recognition-pipeline.md](docs/09-face-recognition-pipeline.md)** —
  end-to-end face recognition walkthrough

## Development

```bash
uv pip install -e ".[dev]"
ruff check src tests
mypy src
pytest -q
```

See [docs/06-engineering-plan.md](docs/06-engineering-plan.md) for the
6-week milestone plan and task breakdown.
