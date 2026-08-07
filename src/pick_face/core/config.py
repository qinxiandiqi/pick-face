"""Configuration loader: pydantic v2 schema for `pick-face.toml`.

Reference:
- docs/01 §4 NF (可移植 / 许可证)
- docs/03 §11 (uv 包管理)
- docs/11 §3.2 (启动强校验 accept_noncommercial_model_license)
- docs/11 §3.5 (toml 模板 default false — fail-safe)
- docs/14 §2 (ModelPack Protocol + entry-points discovery)
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import tomllib
from pydantic import BaseModel, Field, field_validator

# -----------------------------------------------------------------------------
# Pack-id → LicenseClass mapping (route B).
#
# After route B, AC-9 is decided by `pick_face.platform.pack.discover_packs()`,
# NOT by hardcoded model-name sets. The constant below is kept ONLY as a
# fallback for backward compatibility (config files written under v1.x may
# still carry `model_name = "buffalo_l"` and we want to gate them correctly
# before the user has installed `pick-face-modelpack-insightface`).
# -----------------------------------------------------------------------------
_DEPRECATED_NC_PACK_IDS: frozenset[str] = frozenset(
    {"buffalo_l", "buffalo_sc", "antelopev2", "buffalo_m"}
)

# Default pack shipped with pick-face core (Apache-2.0, Pi-3B-friendly).
# History: v2.0.0-dev0 shipped as `yunet-mfn` (YuNet + MobileFaceNet INT8).
# Upstream `opencv/opencv_zoo` removed the MobileFaceNet INT8 weights
# during the 2025-07-31 HuggingFace migration (commit 8ac7b08869), so
# the default is now `yunet-sface` (YuNet + SFace INT8). The old id is
# still discoverable as a deprecated entry-point so v1.x configs keep
# working — see pick_face.platform.packs.yunet_sface._DeprecatedYuNetMFNPack.
DEFAULT_PACK_ID = "yunet-sface"


class RuntimeConfig(BaseModel):
    """[runtime] section. Defaults are fail-safe + commercial-friendly."""

    # ---- Route B: model pack ----
    pack: str = DEFAULT_PACK_ID  # entry-point id (kebab-case, see pick.py)
    model_dir: Path = Field(default_factory=lambda: Path("~/.cache/pick-face/models").expanduser())
    model_index_url: str | None = None  # for internal HTTP mirror (11 §3.5)
    accept_noncommercial_model_license: bool = False  # 11 §3.2 fail-safe

    # ---- Deprecated (v1.x compat) ----
    # If a v1.x toml sets `model_name = "buffalo_l"`, we map it onto the
    # matching NC pack id so the AC-9 gate still trips. v2.0 emits a
    # deprecation warning at load (see load_config() below).
    model_name: str | None = None

    # ---- Inference ----
    provider: Literal["auto", "cpu", "cuda", "directml", "tensorrt"] = "auto"
    workers: int = Field(default=1, ge=1, le=64)
    prefetch: int = Field(default=4, ge=1, le=32)

    @field_validator("model_dir", mode="before")
    @classmethod
    def _expand_user(cls, v: object) -> Path:
        return Path(str(v)).expanduser() if v is not None else v  # type: ignore[arg-type]

    def effective_pack_id(self) -> str:
        """Resolve the active pack id, applying the legacy `model_name` alias.

        Returns:
            - ``self.pack`` if the user set it explicitly.
            - The matching NC pack id (``buffalo_l`` etc.) if the toml
              only carried the v1.x ``model_name`` field.
        """
        if self.pack and self.pack != DEFAULT_PACK_ID:
            return self.pack
        if self.model_name in _DEPRECATED_NC_PACK_IDS:
            return self.model_name  # legacy path
        return self.pack or DEFAULT_PACK_ID


class DetectionConfig(BaseModel):
    """[detection] section."""

    det_thresh: float = Field(default=0.5, ge=0.0, le=1.0)
    det_size: int = Field(default=640, ge=128, le=4096)


class ClusteringConfig(BaseModel):
    """[clustering] section. Threshold authority lives in docs/04 §3.1."""

    min_cluster_size: int = Field(default=4, ge=2, le=100)
    min_samples: int = Field(default=2, ge=1, le=10)
    # Default merge_threshold dropped from 0.55 → 0.0 in v2.0.0: the v1.x
    # default was tuned for ArcFace w600k_r50 (512-D). SFace INT8 (128-D)
    # produces a much tighter cosine distribution — empirical AT&T runs
    # showed distinct-identity centroids with pairwise cosine ≥ 0.55,
    # so any positive threshold over-merges all faces into 1 cluster.
    # The 2-pass centroid merge is opt-in via toml `merge_threshold`;
    # users with higher-dim embeddings (ArcFace 512-D) can set ~0.55.
    # See tests/integration/test_real_faces_ac1.py for the empirical
    # tuning that pinned the v2.0.0 default.
    merge_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    strong_match: float = Field(default=0.60, ge=0.0, le=1.0)
    loose_match: float = Field(default=0.45, ge=0.0, le=1.0)
    different: float = Field(default=0.30, ge=0.0, le=1.0)
    low_confidence: float = Field(default=0.40, ge=0.0, le=1.0)
    recluster_threshold: int = Field(default=50, ge=0, le=10_000)
    recluster_interval_hours: int = Field(default=24, ge=1, le=24 * 30)


class LinkConfig(BaseModel):
    """[link] section."""

    prefer: Literal["symlink", "hardlink", "copy", "junction"] = "symlink"
    copy_fallback: bool = True


class PickFaceConfig(BaseModel):
    """Top-level config (pick-face.toml)."""

    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)
    link: LinkConfig = Field(default_factory=LinkConfig)

    def is_commercial_unsafe(self) -> bool:
        """AC-9 preflight: True iff using a non-commercial pack without consent.

        Resolution order (route B):
          1. If `runtime.pack` is registered, defer to the pack's
             ``LicenseClass`` (see ``pick_face.platform.pack.require_compliance``).
          2. If the pack isn't installed, fall back to the legacy
             ``model_name`` set so v1.x configs still trip the gate.
        """
        from pick_face.platform.pack import LicenseClass, discover_packs

        pack_id = self.runtime.effective_pack_id()
        try:
            packs = discover_packs()
        except Exception:
            packs = {}
        if pack_id in packs:
            pack = packs[pack_id]
            return (
                pack.descriptor.license_class is LicenseClass.NC_RESEARCH
                and not self.runtime.accept_noncommercial_model_license
            )
        # Fallback: legacy model_name based gate.
        return (
            pack_id in _DEPRECATED_NC_PACK_IDS
            and not self.runtime.accept_noncommercial_model_license
        )


def load_config(path: Path | str) -> PickFaceConfig:
    """Load and validate `pick-face.toml` from *path*.

    Raises:
        FileNotFoundError: path does not exist.
        tomllib.TOMLDecodeError: malformed TOML.
        pydantic.ValidationError: schema mismatch (caught by CLI as ConfigError).
    """
    import warnings

    p = Path(path)
    with open(p, "rb") as f:
        data = tomllib.load(f)
    cfg = PickFaceConfig.model_validate(data)
    # Deprecation signal for v1.x configs that still set `model_name`.
    if cfg.runtime.model_name:
        warnings.warn(
            f"`[runtime] model_name = {cfg.runtime.model_name!r}` is "
            f"deprecated in v2.0; please migrate to `pack = "
            f"{_DEPRECATED_NC_PACK_IDS_AND_DEFAULT.get(cfg.runtime.model_name, cfg.runtime.model_name)!r}` "
            f"(see docs/14-model-pack-plugins.md §6).",
            DeprecationWarning,
            stacklevel=2,
        )
    return cfg


def write_default_config(path: Path | str) -> None:
    """Write a freshly-commented default config to *path*.

    The header is the only documentation surface for many users, so it
    explicitly names the commercial-license toggle (11 §3.2 fail-safe).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")


# Lookup table for the v1.x→v2.x `model_name` → `pack` mapping used only
# to render the deprecation warning. New packs always go through entry-points.
_DEPRECATED_NC_PACK_IDS_AND_DEFAULT: dict[str, str] = {
    "buffalo_l": "buffalo_l",  # opt-in via pick-face-modelpack-insightface
    "buffalo_sc": "buffalo_sc",
    "antelopev2": "antelopev2",
    "buffalo_m": "buffalo_m",
}

# Default config text emitted by `pick-face init`.
# NOTE: keep the comment in sync with docs/11 §3.2 and docs/14 §2.
DEFAULT_CONFIG_TEXT = """\
# pick-face configuration
# See docs/AGENTS.md for the full doc index.
# See docs/11-commercial-compliance.md for the commercial-license guide.
# See docs/14-model-pack-plugins.md for the ModelPack plugin contract.

[runtime]
# ----- MODEL PACK (route B) -----
# `pack` selects which ModelPack plugin to load via entry-points
# (group `pick_face.model_packs`). The default `yunet-sface` ships in
# pick-face core and is Apache-2.0 (Pi 3B friendly, ~10 MB on disk).
# Other packs come from separate packages, e.g.
#   uv pip install pick-face-modelpack-insightface   # buffalo_l, buffalo_sc
# See `pick-face doctor` for the list of installed packs.
pack = "yunet-sface"

# Directory where the model pack weights are stored.
# Default: ~/.cache/pick-face/models (overridable via PICK_FACE_MODEL_DIR).
model_dir = "~/.cache/pick-face/models"

# Optional: HTTP mirror for self-hosted model distribution.
# Set e.g. "https://internal.corp/models/" and pass --allow-network.
# model_index_url = ""

# ⚠ REQUIRED only for NC-research packs (e.g. buffalo_l). Default false
# (fail-safe). pick-face refuses to load an NC pack with this = false
# (exit code 2). See docs/11-commercial-compliance.md §3.2.
accept_noncommercial_model_license = false

# ----- INFERENCE -----
# "auto" probes cuda -> directml -> cpu at startup.
provider = "auto"
workers = 1
prefetch = 4

[detection]
det_thresh = 0.5
det_size = 640

[clustering]
min_cluster_size = 4
min_samples = 2
merge_threshold = 0.0
strong_match = 0.60
loose_match = 0.45
different = 0.30
low_confidence = 0.40
recluster_threshold = 50
recluster_interval_hours = 24

[link]
prefer = "symlink"
copy_fallback = true
"""
