# pick-face

> Local offline image face recognition & organization CLI.
> Scan → detect & embed faces → cluster by person → emit
> `person-XXXX/<src_rel_path>` links under your output directory.

---

## ⚠ License notice — read this first

The `pick-face` **code** is Apache-2.0; you may use it freely including
in commercial products.

The **default model pack** (`yunet-mfn`, OpenCV Zoo YuNet + MobileFaceNet INT8)
is **Apache-2.0** as well — fully commercial-friendly, no acknowledgment
required. You can deploy pick-face in commercial products out of the box
with no extra license work.

If you opt into the **InsightFace** model pack (`buffalo_l` / `buffalo_sc` /
`antelopev2`) via `pip install pick-face-modelpack-insightface`, those
weights are under
**[InsightFace's non-commercial-research terms](https://github.com/deepinsight/insightface/blob/master/LICENSE)**
and require explicit `accept_noncommercial_model_license = true`.

See [Commercial compliance](11-commercial-compliance.md) for the four
legal paths to commercial deployment. pick-face refuses to download
model weights unless you pass `--allow-network` and explicitly type
`I AGREE` (NC-research packs only).

| Asset | License | Commercial OK? |
|---|---|---|
| `pick-face` code & docs | Apache-2.0 | ✅ |
| **Default pack `yunet-mfn`** (OpenCV Zoo) | **Apache-2.0** | **✅** |
| `onnxruntime`, `hnswlib`, `hdbscan`, Pillow, OpenCV | MIT / Apache-2.0 / BSD | ✅ |
| `insightface` Python package (opt-in plugin code) | MIT | ✅ |
| `buffalo_l` / `buffalo_sc` / `antelopev2` weights (opt-in) | **InsightFace non-commercial-research** | **❌** |

---

## 5-minute quickstart

```bash
# 1. Install with uv
uv venv
uv pip install -e ".[heic]"          # add raw if you shoot RAW photos

# 2. Generate a starter config (default pack = yunet-mfn, Apache-2.0)
pick-face init

# 3. (Optional) Edit pick-face.toml — change `pack` if you want InsightFace:
#    - keep "yunet-mfn" for commercial-friendly Apache-2.0 default
#    - switch to "buffalo_l" for NC-research opt-in (requires ack)

# 4. Download model weights (requires --allow-network)
#    yunet-mfn: 5 MB, no ack needed (Apache-2.0)
pick-face init-models --pack yunet-mfn --allow-network
#    buffalo_l: 325 MB, requires --yes (I AGREE)
pick-face init-models --pack buffalo_l --allow-network --yes

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
  contract, exit codes, threading model, model pack discovery.
- [Algorithm pipeline](04-algorithm-pipeline.md) — detect → align →
  embed → cluster → must-link/cannot-link → review.
- [Data & storage](05-data-and-storage.md) — SQLite schema, HNSW index,
  staging symlink swap, atomic rollback.
- [Face recognition walkthrough](09-face-recognition-pipeline.md) —
  end-to-end read of every step (best onboarding doc).
- [Model stack](10-model-stack.md) — **model pack overview** (yunet-mfn
  default + InsightFace opt-in), detector/embedder backbones, accuracy
  / size / license trade-offs, ONNX EP matrix.
- [Raspberry Pi / ARM support](13-raspberry-pi-support.md) — Pi 3B/4/5,
  RK3588, Apple Silicon compatibility matrix, install steps, perf
  baselines, swap tips.
- [Model pack plugins](14-model-pack-plugins.md) — `ModelPack` Protocol,
  entry-points contract, 50-line example for writing your own pack.

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
(M0–M5, with M5 covering the model-pack plugin migration) and
[Architecture design §11](03-architecture-design.md) for the extras matrix
and exit-code contract (0 / 2 / 3 / 4 / 5).

---

## License

- Code: Apache-2.0
- Docs: Apache-2.0
- Default model pack `yunet-mfn`: Apache-2.0 (commercial-friendly, no ack)
- Opt-in `buffalo_l` / `buffalo_sc` / `antelopev2`: NC-research — see
  [Commercial compliance](11-commercial-compliance.md)