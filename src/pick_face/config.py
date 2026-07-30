"""Configuration loader: pydantic v2 schema for `pick-face.toml`.

Reference:
- docs/01 §4 NF (可移植 / 许可证)
- docs/03 §11 (uv 包管理)
- docs/11 §3.2 (启动强校验 accept_noncommercial_model_license)
- docs/11 §3.5 (toml 模板 default false — fail-safe)
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# InsightFace `buffalo_*` weight pack names (non-commercial-research licensed).
# See docs/11 §1.2.
INSIGHTFACE_MODELS: frozenset[str] = frozenset(
    {"buffalo_l", "buffalo_sc", "antelopev2", "buffalo_m"}
)


class RuntimeConfig(BaseModel):
    """[runtime] section. Defaults are fail-safe: non-commercial = false."""

    model_name: str = "buffalo_l"
    model_dir: Path = Field(default_factory=lambda: Path("~/.insightface/models").expanduser())
    model_index_url: str | None = None  # for internal HTTP mirror (11 §3.5)
    accept_noncommercial_model_license: bool = False  # 11 §3.2 fail-safe
    provider: Literal["auto", "cpu", "cuda", "directml", "tensorrt"] = "auto"
    workers: int = Field(default=1, ge=1, le=64)
    prefetch: int = Field(default=4, ge=1, le=32)

    @field_validator("model_dir", mode="before")
    @classmethod
    def _expand_user(cls, v: object) -> Path:
        return Path(str(v)).expanduser() if v is not None else v  # type: ignore[arg-type]


class DetectionConfig(BaseModel):
    """[detection] section."""

    det_thresh: float = Field(default=0.5, ge=0.0, le=1.0)
    det_size: int = Field(default=640, ge=128, le=4096)


class ClusteringConfig(BaseModel):
    """[clustering] section. Threshold authority lives in docs/04 §3.1."""

    min_cluster_size: int = Field(default=3, ge=2, le=100)
    min_samples: int = Field(default=2, ge=1, le=10)
    merge_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
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
        """AC-9 preflight: True iff using a non-commercial model without consent."""
        return (
            self.runtime.model_name in INSIGHTFACE_MODELS
            and not self.runtime.accept_noncommercial_model_license
        )


def load_config(path: Path | str) -> PickFaceConfig:
    """Load and validate `pick-face.toml` from *path*.

    Raises:
        FileNotFoundError: path does not exist.
        tomllib.TOMLDecodeError: malformed TOML.
        pydantic.ValidationError: schema mismatch (caught by CLI as ConfigError).
    """
    p = Path(path)
    with open(p, "rb") as f:
        data = tomllib.load(f)
    return PickFaceConfig.model_validate(data)


def write_default_config(path: Path | str) -> None:
    """Write a freshly-commented default config to *path*.

    The header is the only documentation surface for many users, so it
    explicitly names the commercial-license toggle (11 §3.2 fail-safe).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")


# Default config text emitted by `pick-face init`.
# NOTE: keep the comment in sync with docs/11 §3.2.
DEFAULT_CONFIG_TEXT = """\
# pick-face configuration
# See docs/AGENTS.md for the full doc index.
# See docs/11-commercial-compliance.md for the commercial-license guide.

[runtime]
# ----- MODEL & LICENSE (AC-9) -----
# `model_name` selects which model pack to use from `model_dir`.
# Default: "buffalo_l" (InsightFace — NON-COMMERCIAL RESEARCH ONLY).
# For commercial use, self-train (face.evoLVe + WebFace4M) and set this
# to your model id, e.g. "arcface_r50_webface4m".
model_name = "buffalo_l"

# Directory where the model pack is stored. Default: ~/.insightface/models
# (overridable via INSIGHTFACE_HOME or PICK_FACE_MODEL_DIR env).
model_dir = "~/.insightface/models"

# Optional: HTTP mirror for self-hosted model distribution.
# Set e.g. "https://internal.corp/models/" and pass --allow-network.
# model_index_url = ""

# ⚠ REQUIRED: set true ONLY if your use case qualifies as non-commercial
# research per InsightFace's license. Default false (fail-safe).
# Pick-face will refuse to start when using buffalo_* with this = false
# (exit code 2). See docs/11-commercial-compliance.md §2.1.
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
min_cluster_size = 3
min_samples = 2
merge_threshold = 0.55
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
