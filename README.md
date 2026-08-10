# pick-face

> Local offline image face recognition & organization CLI.
> Scan → detect & embed faces → cluster by person → emit
> `person-XXXX/<src_rel_path>` links under your output directory.

---

## ⚠ License notice — read this first

The `pick-face` **code** is Apache-2.0; you may use it freely including
in commercial products.

**Route B (v2.0+): the default model pack `yunet-sface` is MIT, and the
optional high-precision tier `yunet-arcface` is Apache-2.0.** Both ship
in the core wheel and require no license acknowledgment. You can deploy
pick-face commercially **out of the box**.

If you opt into **InsightFace** model packs (`buffalo_l` / `buffalo_sc` /
`antelopev2`) via `pip install pick-face-modelpack-insightface`, those
weights are under
**[InsightFace's non-commercial-research terms](https://github.com/deepinsight/insightface/blob/master/LICENSE)**
and require explicit `accept_noncommercial_model_license = true`.

See **[docs/11-commercial-compliance.md](docs/11-commercial-compliance.md)**
for the four legal paths to commercial deployment. pick-face refuses to
download NC-research weights unless you pass `--allow-network` and
explicitly type `I AGREE`.

| Asset | License | Commercial OK? |
|---|---|---|
| `pick-face` code & docs | Apache-2.0 | ✅ |
| **Default pack `yunet-sface`** (OpenCV Zoo per-model) | **MIT** | **✅** |
| **High-precision tier `yunet-arcface`** (ONNX Model Zoo + OpenCV Zoo) | **Apache-2.0 + MIT** | **✅** |
| `onnxruntime`, `hnswlib`, `hdbscan`, Pillow, OpenCV | MIT / Apache-2.0 / BSD | ✅ |
| `insightface` Python package (opt-in plugin) | MIT | ✅ |
| `buffalo_l` / `buffalo_sc` / `antelopev2` weights (opt-in) | **InsightFace non-commercial-research** | **❌** |

---

## 5-minute quickstart

```bash
# 1. Install (uv is the only supported package manager — see docs/AGENTS.md)
uv venv
uv pip install -e ".[heic]"          # add `raw` for RAW photos

# 2. Generate a starter config
#    Default: pack = "yunet-sface" (MIT, commercial-friendly)
pick-face init

# 3. (Optional) Edit pick-face.toml — switch `pack` if you want high-precision.
#    Keep "yunet-sface" for the MIT default.
#    Switch to "yunet-arcface" for 512-D ArcFace (Apache-2.0, GPU recommended).
#    Switch to "buffalo_l" for InsightFace (NC-research, opt-in only).

# 4. Download model weights (requires --allow-network)
#    yunet-sface: ~10 MB, no acknowledgment (MIT)
pick-face init-models --pack yunet-sface --allow-network
#    yunet-arcface: --quant fp32 ~261 MB / --quant int8 ~66 MB (Apache-2.0)
pick-face init-models --pack yunet-arcface --quant int8 --allow-network
#    buffalo_l: 325 MB, requires --yes "I AGREE" (NC-research)
pip install pick-face-modelpack-insightface
pick-face init-models --pack buffalo_l --allow-network --yes

# 5. Scan + index + cluster + link in one shot
pick-face run --src ~/Photos --out ~/Photos/by_face
```

What you get under `~/Photos/by_face`:

```
person-0001/2024-01-01 beach.jpg        # symlink (or hardlink/copy fallback)
person-0001/2024-02-14 dinner.jpg
person-0002/2024-03-05 office.jpg
report.md / report.json / report.html   # audit + pack/license headers
low_confidence_faces.json               # candidates for `pick-face review apply`
```

---

## Raspberry Pi / ARM support

`pick-face` runs out of the box on Raspberry Pi 3B (1 GB) and up via the
default `yunet-sface` pack (~10 MB on disk, ~150 MB RAM). See
**[docs/13-raspberry-pi-support.md](docs/13-raspberry-pi-support.md)**
for the full compatibility matrix, install steps, and performance
baselines.

| Device | Default pack | Notes |
|---|---|---|
| Raspberry Pi 3B / 3B+ (1 GB) | `yunet-sface` | Open swap 1 GB |
| Raspberry Pi 4B 1-2 GB | `yunet-sface` | 1 GB tight, 2 GB comfortable |
| Raspberry Pi 4B 4-8 GB / Pi 5 | `yunet-sface` (default) / `yunet-arcface --quant int8` (high-precision) | INT8 ~66 MB on disk, ~256 MB RAM |
| Orange Pi 5 (RK3588S) | `yunet-sface` | 4× A76 + NPU (M6+) |
| Apple Silicon (M1/M2/M3) | `yunet-sface` (CoreML EP) | 8 GB+ |
| x86-64 + NVIDIA | `yunet-arcface --quant fp32` (high-precision) / `buffalo_l` (opt-in) | CUDA EP on ArcFace |

---

## Documentation

The full docs site lives at
**[https://qinxiandiqi.github.io/pick-face/](https://qinxiandiqi.github.io/pick-face/)**
(or in this repo under `docs/`).

| Document | What it covers |
|---|---|
| **[docs/11-commercial-compliance.md](docs/11-commercial-compliance.md)** | **Read first** if shipping for paid use. Four legal paths (Route B default is option D — Apache-2.0). |
| **[docs/12-compatibility-promise.md](docs/12-compatibility-promise.md)** | **1.0+ contract**: stable CLI, public Python API, persistence formats, deprecation policy. |
| [docs/01-product-requirement.md](docs/01-product-requirement.md) | Goals, user stories, acceptance criteria. |
| [docs/03-architecture-design.md](docs/03-architecture-design.md) | Module layout, CLI contract, exit codes, model pack discovery. |
| [docs/04-algorithm-pipeline.md](docs/04-algorithm-pipeline.md) | Detect → align → embed → cluster pipeline. |
| [docs/05-data-and-storage.md](docs/05-data-and-storage.md) | SQLite / HNSW / symlink strategy. |
| [docs/06-engineering-plan.md](docs/06-engineering-plan.md) | Milestone + task breakdown (M0–M5, with M5 covering model pack migration). |
| [docs/09-face-recognition-pipeline.md](docs/09-face-recognition-pipeline.md) | End-to-end walkthrough (best onboarding). |
| [docs/10-model-stack.md](docs/10-model-stack.md) | **Model pack overview**: yunet-mfn (default) + InsightFace (opt-in) + accuracy / size / license trade-offs. |
| [docs/13-raspberry-pi-support.md](docs/13-raspberry-pi-support.md) | Pi 3B/4/5, RK3588, Apple Silicon compatibility, install, perf. |
| [docs/14-model-pack-plugins.md](docs/14-model-pack-plugins.md) | `ModelPack` Protocol, entry-points contract, write your own pack (50-line example). |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common errors with copy-paste fixes. |

---

## Development

```bash
uv pip install -e ".[dev,docs]"
ruff check src tests
ruff format --check src tests
pytest -q                              # 230+ unit tests
python tests/smoke_cli_scan.py         # end-to-end smoke
mkdocs serve                           # docs site at http://127.0.0.1:8000
```

CI runs lint + 230 unit tests + 5 smoke scripts on Ubuntu, Windows, and
macOS for every push — see [.github/workflows/ci.yml](.github/workflows/ci.yml).

Real-face tests (`-m real_data`) are opt-in: they require fetching a
~4.5 MB AT&T/ORL fixture via `scripts/fetch_face_dataset.py` first.

---

## License

- Code & docs: Apache-2.0 — see [LICENSE](LICENSE).
- Default model pack `yunet-mfn`: Apache-2.0 (commercial-friendly, no
  acknowledgment required).
- Opt-in `buffalo_l` / `buffalo_sc` / `antelopev2` (via
  `pick-face-modelpack-insightface`): NC-research — see
  [docs/11-commercial-compliance.md](docs/11-commercial-compliance.md).
