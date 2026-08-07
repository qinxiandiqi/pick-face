"""Model Pack plugin protocol + registry (route B).

Reference:
- docs/13-raspberry-pi-support.md (roadmap, model packs matrix)
- docs/14-model-pack-plugins.md (new — plugin contract)

A *Model Pack* is a self-contained detector + embedder (and optional
    aligner) bundle, distributed as a separate Python package with a
    registered entry-point. pick-face core never imports the pack's
    actual implementation modules — it talks to whatever implements
    `ModelPack` via the plugin loader.

The contract is intentionally small: a pack declares its id, license
class, detector factory, embedder factory, and a self-description for
`init-models` / `report`. It does NOT carry weights — weights are
fetched by `init-models` (or supplied by the user) into
`[runtime].model_dir`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from pick_face.ingest.align import Aligner
from pick_face.ingest.detector import Detector
from pick_face.ingest.embedder import Embedder


class LicenseClass(str, Enum):
    """License class of a model pack — drives AC-9 gating.

    NC-research: pick-face enforces accept_noncommercial_model_license
        gate (default false). See docs/11 §3.2.
    permissive: Apache-2.0 / MIT / BSD-3 — no gating, no ack required.
    user_supplied: user provided the weights themselves. pick-face does
        not gate, but the report warns "verify your license".
    """

    NC_RESEARCH = "nc-research"
    PERMISSIVE = "permissive"
    USER_SUPPLIED = "user-supplied"


@dataclass(frozen=True)
class PackDescriptor:
    """Human-readable metadata for a model pack.

    Used by:
      * `pick-face init-models` to print the License Notice
      * `pick-face report` to render the "Model & License" header
      * `pick-face doctor` to show available packs on this host
    """

    pack_id: str  # e.g. "yunet-mfn", "buffalo_l", "scrfd-500m-mfn"
    display_name: str  # e.g. "YuNet + MobileFaceNet (OpenCV Zoo)"
    detector_name: str  # e.g. "YuNet (yunet_2023mar.onnx)"
    embedder_name: str  # e.g. "MobileFaceNet (mfn_align1k.onnx)"
    detector_sha256: str  # integrity check on disk
    embedder_sha256: str
    detector_size_bytes: int
    embedder_size_bytes: int
    detector_url: str | None  # filled by the pack, may be None for user_supplied
    embedder_url: str | None
    license_class: LicenseClass
    license_name: str  # e.g. "Apache-2.0", "InsightFace NC-research"
    license_spdx: str  # SPDX id for the LICENSE file; "" if user-supplied
    license_notice_text: str = ""  # full text shown by init-models if NC
    accuracy_lfw: float | None = None  # author-reported LFW accuracy (0..1)
    notes: str = ""
    # Free-form tags (e.g. ["arm-friendly", "low-ram", "no-landmark"])
    tags: list[str] = field(default_factory=list)


@runtime_checkable
class ModelPack(Protocol):
    """One detector+embedder bundle, pluggable via entry-points.

    Implementations live in their own PyPI package and advertise
    themselves under the `pick_face.model_packs` entry-point group.
    """

    descriptor: PackDescriptor

    def build_detector(
        self, model_dir: Path, ctx_id: int = 0, det_size: tuple[int, int] = (320, 320)
    ) -> Detector:
        """Construct a Detector. Implementations may load weights lazily."""
        ...

    def build_embedder(self, model_dir: Path) -> Embedder:
        """Construct an Embedder. Implementation owns model lifetime."""
        ...

    def build_aligner(self) -> Aligner:
        """Pure-geometry Aligner. YuNet gives 5-pt landmarks, so the
        default ArcFace-style 5-pt aligner is reused across packs."""
        ...

    def expected_files(self) -> list[str]:
        """Filenames that must exist under model_dir/pack_id/ for the
        pack to load. `init-models` verifies these after download."""
        ...

    def download_to(
        self,
        target_dir: Path,
        *,
        progress: callable | None = None,  # type: ignore[valid-type]
    ) -> list[Path]:
        """Fetch the weights into target_dir. Implementations may use
        any source (HTTP mirror, GitHub release, HF model hub, …).
        Returns the list of files written. Network calls live here."""
        ...


def discover_packs() -> dict[str, ModelPack]:
    """Find all installed model-pack plugins via entry-points.

    Returns:
        {pack_id: pack_instance}, merged from every installed
        `pick_face.model_packs` entry-point. Duplicates (same pack_id
        from two installs) raise — plugin authors must namespace
        uniquely.
    """
    from importlib import metadata

    eps = metadata.entry_points(group="pick_face.model_packs")
    out: dict[str, ModelPack] = {}
    for ep in eps:
        try:
            pack = ep.load()()
        except Exception as e:  # pragma: no cover — plugin bug
            raise RuntimeError(
                f"failed to load model-pack entrypoint {ep.name!r}: {e}"
            ) from e
        if not isinstance(pack, ModelPack):
            raise TypeError(
                f"entry-point {ep.name!r} is not a ModelPack "
                f"(got {type(pack).__name__})"
            )
        if pack.descriptor.pack_id in out:
            raise ValueError(
                f"duplicate model pack id {pack.descriptor.pack_id!r} "
                f"from entry-points {ep.name!r} and "
                f"{[k for k, v in out.items() if v is pack]!r}"
            )
        out[pack.descriptor.pack_id] = pack
    return out


def get_pack(pack_id: str) -> ModelPack:
    """Resolve `pack_id` from the installed plugin set.

    Raises:
        KeyError: pack_id not registered.
    """
    packs = discover_packs()
    if pack_id not in packs:
        installed = ", ".join(sorted(packs)) or "(none)"
        raise KeyError(
            f"model pack {pack_id!r} not installed. "
            f"Installed: {installed}. "
            f"Install with: uv pip install pick-face-modelpack-{pack_id}"
        )
    return packs[pack_id]


def require_compliance(pack: ModelPack, cfg: "PickFaceConfig") -> None:  # type: ignore[name-defined]  # noqa: F821
    """AC-9 gate, genericised over any pack.

    For LicenseClass.NC_RESEARCH we enforce
    `accept_noncommercial_model_license = true`. For PERMISSIVE and
    USER_SUPPLIED we silently allow; the report still names the license
    so the user is reminded.
    """
    from pick_face.core.errors import CommercialLicenseError

    if pack.descriptor.license_class is LicenseClass.NC_RESEARCH:
        if not cfg.runtime.accept_noncommercial_model_license:
            raise CommercialLicenseError(
                f"model pack {pack.descriptor.pack_id!r} is "
                f"{pack.descriptor.license_name} (non-commercial-research). "
                f"You have not acknowledged the license in [runtime] "
                f"accept_noncommercial_model_license. See "
                f"docs/11-commercial-compliance.md."
            )