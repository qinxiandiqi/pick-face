# Compatibility promise

> Single source of truth for the pick-face **public API contract** and the
> policies we follow when evolving it. If a change violates this document,
> it is a bug — please [open an issue](https://github.com/qinxiandiqi/pick-face/issues).

This document applies starting with **`pick-face 1.0.0`** and follows
[Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

> **v3.0 note**: pick-face v3.0 introduces the **Web service** surface
> alongside the existing CLI. CLI commands (`pick-face run`,
> `pick-face init`, etc.) remain supported as documented in §1.1; the new
> `pick-face-web` subcommand set is documented in §1.2.

---

## 1. What we promise

### 1.1 Public CLI surface (stable)

The following CLI surface is **stable** within a major version:

- **Subcommand names** (`init`, `init-models`, `scan`, `index`, `cluster`,
  `link`, `run`, `report`, `review`, `review apply`, `gc`, `prune`,
  `rollback`, `rebuild`).
- **Top-level flags** on each subcommand (the `--*` options documented in
  `pick-face <subcommand> --help`).
- **Exit codes**: `0` (success), `2` (validation / license refusal),
  `3` (model / config not found), `4` (operational error),
  `5` (interrupted — SIGTERM / SIGBREAK). See
  [docs/03 §9](03-architecture-design.md) and
  [docs/11 §3.6](11-commercial-compliance.md).
- **File outputs**: the layout under `<out>/` (`person-XXXX/`,
  `report.md`, `report.json`, `report.html`, `low_confidence_faces.json`,
  `.cache/index.sqlite`, `.cache/<model>/.license_ack`).
- **SQLite schema** (`source`, `face`, `cluster`, `link`,
  `review_decision`, `schema_migrations`) — column names, types, and
  foreign keys. Adding new tables or columns is allowed; renaming or
  removing columns is **not** within a major version.

### 1.2 Python public API (stable)

The following imports are stable:

```python
# 1. Top-level namespace — every name re-exported from pick_face/__init__.py
from pick_face import (
    __version__, __license__,
    # config
    PickFaceConfig, ClusteringConfig, DetectionConfig, LinkConfig,
    RuntimeConfig, load_config, write_default_config,
    # errors
    PickFaceError, ConfigError, CliArgError, CommercialLicenseError,
    FaceError, ImageDecodeError, InterruptedError, ModelLoadError,
    ModelNotFoundError, OutputNotWritableError, PipelineFailureError,
    SourceNotFoundError,
    EXIT_OK, EXIT_CONFIG, EXIT_MODEL, EXIT_PIPELINE, EXIT_INTERRUPTED,
    # hashing / images / paths
    content_hash, content_hash_bytes, file_id, HASH_ALGO,
    DecodedImage, decode, MAX_LONG_EDGE,
    APP_NAME, APP_AUTHOR, default_data_dir, default_model_dir, ensure_dir,
    # reporter
    ReportStats, render_markdown, render_json, render_html,
    write_report, collect_stats,
    collect_low_confidence_faces, write_low_confidence_json,
    # store
    HnswIndex, open_db, SCHEMA_VERSION,
    # platform
    resolve_providers, describe_provider_chain, check_commercial,
    run_benchmark, BenchResult,
)

# 2. Sub-package paths (preferred for new code)
from pick_face.core.config import PickFaceConfig
from pick_face.core.errors import PickFaceError
from pick_face.store.index import open_db
from pick_face.store.index_hnsw import HnswIndex
from pick_face.output.reporter import render_markdown, render_json, render_html
from pick_face.platform.runtime import resolve_providers
```

The 5-domain layout (`pick_face.core` / `pick_face.ingest` /
`pick_face.store` / `pick_face.output` / `pick_face.platform`) is
**stable from v1.0 onward**. Breaking it requires a major version bump.

Anything not in this list (e.g. `pick_face.ingest.cluster`,
`pick_face.ingest.embedder`, `pick_face.core.hashing`) is **internal** —
call sites exist for tests and CLI glue, and we may refactor at any time.

### 1.3 Persistence formats (stable)

- **`pick-face/index@1`** — HNSW index binary header (T-203).
- **`pick-face/checkpoint@1`** — long-task checkpoint (T-204).
- **`pick-face/meta@1`** — per-cluster metadata JSON (T-108).
- **`pick-face/index@1`** — top-level cluster index JSON (T-108).
- **`pick-face/perf_report@1`** — `bench` JSON output (T-205).
- **`pick-face/report/markdown@1`**, **`pick-face/report/json@1`** —
  report output schemas (the `run_id`, `model`, `stats` keys).

Each format has a magic number or `schema` field; readers must refuse to
parse a payload whose magic/schema is unknown.

---

## 2. What we may change in a minor / patch release

These may change **without notice** between minor versions, but the
change is always noted in `CHANGELOG.md`:

- Default values for **optional** config fields (e.g.
  `clustering.min_cluster_size`, `runtime.batch_size`).
- Internal Python modules (e.g. `pick_face.ingest.cluster`,
  `pick_face.ingest.scanner`, `pick_face.ingest.detector`,
  `pick_face.ingest.embedder`, `pick_face.core.hashing`,
  `pick_face.output.linker`, `pick_face.store.review`,
  `pick_face.output.mirrors`, `pick_face.output.parallel`,
  `pick_face.platform.runtime`, `pick_face.platform.models`,
  `pick_face.core.images`, `pick_face.cli`, `pick_face.platform.bench`,
  `pick_face.store.checkpoint`, `pick_face.store.index_hnsw`,
  `pick_face.ingest.align`).
- Performance characteristics (timings, memory).
- Warning text and log formatting.
- Default install extras (e.g. promoting `heic` to default).
- Adding new optional fields to JSON / TOML configs (old keys still parse).
- Adding new SQLite tables / columns (old ones still present).
- Adding new CLI subcommands (existing ones unchanged).

---

## 3. What requires a major version bump

Breaking the promises in §1 always requires a major version bump:

- Removing or renaming a public CLI subcommand / flag.
- Changing an exit code.
- Changing a public Python import path or function signature.
- Renaming / removing a SQLite column or changing a foreign key.
- Changing the magic/schema number of any persisted format above.

We may also reserve a major bump for "soft" breaks that downstream
pipelines care about: changing the default CLI output directory layout,
changing how the link table is structured, etc.

---

## 4. Deprecation policy

When we need to remove something in §1:

1. The feature is marked **deprecated** in `CHANGELOG.md` of a minor
   release, with a stated removal version.
2. The feature emits a one-line warning to stderr on every invocation
   that uses it.
3. The feature continues to work for at least **two minor releases**
   before removal.
4. Removal happens in a major release whose `CHANGELOG.md` entry
   explicitly calls out the removal.

Exception: a **security** issue may force an immediate removal. Such
removals are noted prominently in the release notes.

---

## 5. Supported Python & OS matrix

We support:

- **Python**: 3.10, 3.11, 3.12, 3.13 (see `requires-python` in `pyproject.toml`).
- **Operating systems**: Linux (x86_64, aarch64), macOS (x86_64,
  Apple Silicon), Windows 10/11 (x86_64).

For a given major version, the **minimum** Python version may be raised
in a minor release only with **six months' notice** in `CHANGELOG.md`.

OS support follows the underlying Python packaging toolchain
(uv / pip / wheels). We do not support end-of-life Python releases.

---

## 6. Default model weights (commercial compliance)

The default model `InsightFace buffalo_l` is **non-commercial-research**
licensed by InsightFace and is **NOT** shipped with pick-face. This is
not a compatibility break — it's a legal requirement documented in
[11-commercial-compliance.md](11-commercial-compliance.md). Users who
need commercial use must switch to a self-trained or commercially
licensed model via `[runtime] model_name` and `[runtime] model_dir`.

This promise makes **no** legal representation about the user's right
to use the default model weights; see §1 of the compliance doc.

---

## 7. Versioning policy summary

| Change kind | Version bump |
|---|---|
| Bug fix, no API change | PATCH (1.0.x) |
| Add a new CLI subcommand / flag with default OFF | MINOR (1.x.0) |
| Add a new optional config field, default OFF | MINOR |
| Add a new SQLite table / column | MINOR |
| Deprecate (but keep working) a public surface | MINOR |
| Change a default that downstream pipelines care about | MINOR |
| Remove a deprecated public surface | MAJOR (x.0.0) |
| Change an exit code | MAJOR |
| Rename a public Python import or function | MAJOR |
| Bump the `schema` field of any persisted format | MAJOR |
| Raise the minimum Python version | MAJOR (with 6 months notice) |

---

## 8. Reporting an unintentional break

If you find a change in `1.0.0+` that breaks your pipeline and you
believe it violates §1 above:

1. Open an issue with the label `compat`.
2. Include the pick-face version (`pick-face --version`) and the
   minimum reproduction snippet.
3. We will treat unintentional compat breaks as bugs and ship a fix in
   the next patch release.

This document itself evolves under SemVer — its amendment in a minor
release is allowed if it tightens the policy (we never loosen it
without a MAJOR bump).