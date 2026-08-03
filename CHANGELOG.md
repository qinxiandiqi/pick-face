# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
— see [docs/12-compatibility-promise.md](docs/12-compatibility-promise.md) for
the full policy.

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