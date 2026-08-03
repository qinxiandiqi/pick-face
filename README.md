# pick-face

> Local offline image face recognition & organization CLI.
> Scan → detect & embed faces → cluster by person → emit
> `person-XXXX/<src_rel_path>` links under your output directory.

---

## ⚠ License notice — read this first

The `pick-face` **code** is Apache-2.0; you may use it freely including
in commercial products.

The **default model weights** (`InsightFace buffalo_l`) are **NOT**
shipped with this project and are licensed under
**[InsightFace's non-commercial-research terms](https://github.com/deepinsight/insightface/blob/master/LICENSE)**.

**If you deploy pick-face commercially** you must self-train or license
another model. See **[docs/11-commercial-compliance.md](docs/11-commercial-compliance.md)**
for the three legal paths. pick-face refuses to download model weights
unless you pass `--allow-network` and explicitly type `I AGREE`, so you
cannot ship a copy by accident — but the **legal** choice is yours.

---

## 5-minute quickstart

```bash
# 1. Install (uv is the only supported package manager — see docs/AGENTS.md)
uv venv
uv pip install -e ".[heic]"          # add `raw` for RAW photos

# 2. Generate a starter config
pick-face init

# 3. Edit pick-face.toml — confirm model choice.
#    Default: accept_noncommercial_model_license = false (fail-safe).
#    For personal / academic use, set it to true.

# 4. Download model (requires --allow-network + "I AGREE")
pick-face init-models --allow-network --yes

# 5. Scan + index + cluster + link in one shot
pick-face run --src ~/Photos --out ~/Photos/by_face
```

What you get under `~/Photos/by_face`:

```
person-0001/2024-01-01 beach.jpg        # symlink (or hardlink/copy fallback)
person-0001/2024-02-14 dinner.jpg
person-0002/2024-03-05 office.jpg
report.md / report.json / report.html   # audit + license headers
low_confidence_faces.json               # candidates for `pick-face review apply`
```

---

## Documentation

The full docs site lives at
**[https://qinxiandiqi.github.io/pick-face/](https://qinxiandiqi.github.io/pick-face/)**
(or in this repo under `docs/`).

| Document | What it covers |
|---|---|
| **[docs/11-commercial-compliance.md](docs/11-commercial-compliance.md)** | **Read first** if shipping for paid use. |
| **[docs/12-compatibility-promise.md](docs/12-compatibility-promise.md)** | **1.0+ contract**: stable CLI, public Python API, persistence formats, deprecation policy. |
| [docs/01-product-requirement.md](docs/01-product-requirement.md) | Goals, user stories, acceptance criteria. |
| [docs/03-architecture-design.md](docs/03-architecture-design.md) | Module layout, CLI contract, exit codes. |
| [docs/04-algorithm-pipeline.md](docs/04-algorithm-pipeline.md) | Detect → align → embed → cluster pipeline. |
| [docs/05-data-and-storage.md](docs/05-data-and-storage.md) | SQLite / HNSW / symlink strategy. |
| [docs/06-engineering-plan.md](docs/06-engineering-plan.md) | Milestone + task breakdown. |
| [docs/09-face-recognition-pipeline.md](docs/09-face-recognition-pipeline.md) | End-to-end walkthrough (best onboarding). |
| [docs/10-model-stack.md](docs/10-model-stack.md) | SCRFD-10G, ArcFace, HDBSCAN, hnswlib — and why. |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common errors with copy-paste fixes. |

---

## Development

```bash
uv pip install -e ".[dev,docs]"
ruff check src tests
ruff format --check src tests
pytest -q
python tests/smoke_cli_scan.py         # end-to-end smoke
mkdocs serve                           # docs site at http://127.0.0.1:8000
```

CI runs lint + 230 unit tests + 5 smoke scripts on Ubuntu, Windows, and
macOS for every push — see [.github/workflows/ci.yml](.github/workflows/ci.yml).

---

## License

- Code & docs: Apache-2.0 — see [LICENSE](LICENSE).
- Default model weights: **NOT shipped** — see [docs/11-commercial-compliance.md](docs/11-commercial-compliance.md).