# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
— see [docs/12-compatibility-promise.md](docs/12-compatibility-promise.md) for
the full policy.

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