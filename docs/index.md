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
another model. See [Commercial compliance](11-commercial-compliance.md)
for the three legal paths. pick-face refuses to download model weights
unless you pass `--allow-network` and explicitly type `I AGREE`, so
you cannot ship a copy by accident — but the **legal** choice is yours.

| Asset | License | Commercial OK? |
|---|---|---|
| `pick-face` code & docs | Apache-2.0 | ✅ |
| `insightface`, `onnxruntime`, `hnswlib`, `hdbscan`, Pillow, OpenCV | MIT / Apache-2.0 / BSD | ✅ |
| **`buffalo_l` weights** (downloaded at runtime) | **InsightFace non-commercial-research** | **❌** |

---

## 5-minute quickstart

```bash
# 1. Install with uv
uv venv
uv pip install -e ".[heic]"          # add raw if you shoot RAW photos

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

## Documentation map

**Start here:**

- [Commercial compliance](11-commercial-compliance.md) — read this **before**
  shipping anything for paid use.
- [Product requirement](01-product-requirement.md) — what pick-face does,
  acceptance criteria, and out-of-scope.

**Architecture & engineering:**

- [Architecture design](03-architecture-design.md) — module layout, CLI
  contract, exit codes, threading model.
- [Algorithm pipeline](04-algorithm-pipeline.md) — detect → align →
  embed → cluster → must-link/cannot-link → review.
- [Data & storage](05-data-and-storage.md) — SQLite schema, HNSW index,
  staging symlink swap, atomic rollback.
- [Face recognition walkthrough](09-face-recognition-pipeline.md) —
  end-to-end read of every step (best onboarding doc).
- [Model stack](10-model-stack.md) — SCRFD-10G, ArcFace w600k_r50,
  HDBSCAN, hnswlib — and why we picked them.

**Research & decision log:**

- [Technical pre-research](02-technical-pre-research.md)
- [Risks & decisions (ADRs)](07-risk-and-decisions.md)
- [Review notes](08-review-notes.md)

**Operational:**

- [Troubleshooting](troubleshooting.md) — common errors with copy-paste
  fixes.
- [AGENTS index](AGENTS.md) — entry point for AI agents / contributors.

---

## Development

```bash
uv pip install -e ".[dev,docs]"
ruff check src tests
ruff format --check src tests
pytest -q                              # 230+ tests
python tests/smoke_cli_scan.py         # end-to-end smoke
mkdocs serve                           # docs site at :8000
mkdocs build                           # static site under site/
```

See [Engineering plan](06-engineering-plan.md) for the milestone breakdown
and [Architecture design §7](03-architecture-design.md) for the exit-code
contract (0 / 2 / 3 / 4 / 5).

---

## License

- Code: Apache-2.0
- Docs: Apache-2.0
- Default model weights: **NOT shipped** — see [Commercial compliance](11-commercial-compliance.md).