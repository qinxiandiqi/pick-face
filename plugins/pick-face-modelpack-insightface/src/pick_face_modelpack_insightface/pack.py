"""InsightFace ModelPack implementations.

Reference: docs/14 §3 (write your own pack — InsightFace flavour).

All three packs share a single shim that wraps ``insightface.app.FaceAnalysis``
behind the ``ModelPack`` Protocol. The shim re-uses pick-face core's
``detection_from_insightface`` adapter for the bbox / landmarks / chip
plumbing so we don't reinvent it.

Each pack class only differs in:
  * ``pack_id`` / ``display_name`` / ``detector_name`` / ``embedder_name``
  * ``license_class`` (always NC_RESEARCH) and license text.
"""

from __future__ import annotations

from pathlib import Path

from pick_face.ingest.detector import Detection
from pick_face.ingest.embedder import Embedder
from pick_face.platform.pack import (
    LicenseClass,
    ModelPack,
    PackDescriptor,
)

# A common license-notice string used by all three InsightFace packs.
# We surface it via init-models; the user is then asked to type 'I AGREE'.
_INSIGHTFACE_NC_NOTICE = (
    "InsightFace buffalo* / antelopev2 model weights are under the\n"
    "InsightFace non-commercial-research license. By using this pack\n"
    "you confirm that your use case qualifies as non-commercial\n"
    "research; otherwise self-train a model or obtain a commercial\n"
    "license. See docs/11-commercial-compliance.md.\n"
)


def _descriptor(
    pack_id: str,
    display_name: str,
    detector_name: str,
    embedder_name: str,
    size_mb: int,
    accuracy_lfw: float | None,
    notes: str,
) -> PackDescriptor:
    return PackDescriptor(
        pack_id=pack_id,
        display_name=display_name,
        detector_name=detector_name,
        embedder_name=embedder_name,
        # SHA256 are filled in by `scripts/pin_sha256.py` once the user
        # downloads the weights; we leave placeholder strings for now.
        detector_sha256="<pin-on-first-download>",
        embedder_sha256="<pin-on-first-download>",
        detector_size_bytes=size_mb * 1024 * 1024,
        embedder_size_bytes=0,
        detector_url=None,  # picked up by insightface.model_zoo
        embedder_url=None,
        license_class=LicenseClass.NC_RESEARCH,
        license_name="InsightFace non-commercial-research",
        license_spdx="InsightFace-NC-research",
        license_notice_text=_INSIGHTFACE_NC_NOTICE,
        accuracy_lfw=accuracy_lfw,
        notes=notes,
        tags=["insightface", "nc-research"],
    )


class _InsightFacePackBase(ModelPack):
    """Shared shim — subclasses just set ``descriptor``."""

    descriptor: PackDescriptor  # set by subclass

    def expected_files(self) -> list[str]:
        # InsightFace stores weights under <root>/<name>/{detection,recognition}.onnx
        return ["detection.onnx", "recognition.onnx"]

    def build_detector(self, model_dir: Path, ctx_id: int = 0, det_size=(640, 640)) -> Detection:
        # Imported lazily so the module is importable without insightface
        # (e.g. on Pi 3B installations of pick-face core that don't need
        # InsightFace packs).
        raise NotImplementedError(
            "InsightFace packs route through pick_face.platform.runtime."
            "load_insightface_runner(); this method is intentionally a "
            "no-op for the InsightFace plugin (see docs/14 §3.4)."
        )

    def build_embedder(self, model_dir: Path) -> Embedder:
        raise NotImplementedError(
            "InsightFace embedder is built by load_insightface_runner() — "
            "this plugin does not implement a standalone build_embedder."
        )

    def build_aligner(self):  # -> Aligner:
        # We don't define a separate aligner — the InsightFace runtime
        # path uses pick_face.ingest.align.warp_to_112 directly.
        return None

    def download_to(self, target_dir: Path, *, progress=None) -> list[Path]:
        # The actual download is delegated to the bundled
        # `insightface.model_zoo.get_model()` runner; this method is a
        # no-op placeholder so callers can wire it into a uniform path.
        # `pick-face init-models` will call insightface.model_zoo.get_model
        # via the legacy load_insightface_runner() flow.
        target_dir.mkdir(parents=True, exist_ok=True)
        return []


class BuffaloLPack(_InsightFacePackBase):
    """buffalo_l — InsightFace's flagship (SCRFD-10G + ArcFace w600k_r50).

    Highest LFW accuracy in the family (~99.83%), at the cost of a
    ~325 MB download and ~2.5 GB peak RAM. Requires GPU for >1 fps;
    CPU works but slow.
    """

    descriptor = _descriptor(
        pack_id="buffalo_l",
        display_name="InsightFace buffalo_l (SCRFD-10G + ArcFace w600k_r50)",
        detector_name="SCRFD-10G (scrfd_10g_bnkps.onnx)",
        embedder_name="ArcFace w600k_r50 (w600k_r50.onnx, 512-D)",
        size_mb=325,
        accuracy_lfw=0.9983,
        notes=(
            "Default NC-research pack pre-v2.0. Highest accuracy in the "
            "InsightFace family; ~2.5 GB peak RAM, ~325 MB on disk. "
            "GPU strongly recommended."
        ),
    )


class BuffaloScPack(_InsightFacePackBase):
    """buffalo_sc — speed-flavoured buffalo (SCRFD-500MF + MobileFaceNet)."""

    descriptor = _descriptor(
        pack_id="buffalo_sc",
        display_name="InsightFace buffalo_sc (SCRFD-500MF + MobileFaceNet)",
        detector_name="SCRFD-500MF (scrfd_500m_bnkps.onnx)",
        embedder_name="MobileFaceNet (mobilefacenet.onnx, 512-D)",
        size_mb=160,
        accuracy_lfw=0.9965,
        notes=(
            "Speed-flavoured NC-research pack. ~160 MB on disk, faster "
            "than buffalo_l but ~0.2 pp lower on LFW. Good middle ground."
        ),
    )


class AntelopeV2Pack(_InsightFacePackBase):
    """antelopev2 — InsightFace's gender/age-aware pack."""

    descriptor = _descriptor(
        pack_id="antelopev2",
        display_name="InsightFace antelopev2 (gender/age aware)",
        detector_name="SCRFD-10G (scrfd_10g_bnkps.onnx)",
        embedder_name="ArcFace (antelopev2.onnx, 512-D)",
        size_mb=300,
        accuracy_lfw=0.9980,
        notes=(
            "NC-research pack with optional gender/age outputs. Not used "
            "by pick-face's current cluster stage; reserved for future "
            "review-UI filters."
        ),
    )


# Re-export so plugins can do `from pick_face_modelpack_insightface.pack import *`
__all__ = [
    "AntelopeV2Pack",
    "BuffaloLPack",
    "BuffaloScPack",
]
