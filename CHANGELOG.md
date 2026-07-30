# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-30

### Added

- Initial release: local offline face recognition & organization CLI
- InsightFace `buffalo_l` integration (SCRFD detector + ArcFace embedder)
- HDBSCAN clustering with cosine metric + 2-pass centroid merge
- Symlink / hardlink / copy / junction fallback for cross-platform
- SQLite (WAL) + HNSW index for incremental & resumable runs
- 14 CLI subcommands: init / init-models / scan / index / cluster / link / run
  / report / review / review apply / gc / prune / rollback / rebuild
- Commercial compliance guard: `accept_noncommercial_model_license` field,
  `init-models` License Notice, `report.md` Model+License header,
  AC-9 acceptance test (`tests/acceptance/test_no_model_in_distribution.py`)
- Full documentation set in `docs/`

### Notes

- v0.1 uses InsightFace `buffalo_l` by default, which is non-commercial-research
  licensed. Commercial users must self-train or obtain a commercial license
  per `docs/11-commercial-compliance.md`.
