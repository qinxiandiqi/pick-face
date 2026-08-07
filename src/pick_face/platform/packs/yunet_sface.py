"""Default Model Pack: YuNet detector + SFace INT8 embedder (route B).

Reference:
- docs/13-raspberry-pi-support.md §2 (Pi 3B / ARM-friendly pack)
- docs/14-model-pack-plugins.md (plugin contract)

History:
  * v2.0.0-dev0 (T-503): originally bundled MobileFaceNet INT8 as the
    embedder, but the upstream `opencv_zoo` repo removed
    `models/face_recognition_mobilefacenet_20221220/` entirely during
    the 2025-07-31 HuggingFace migration (commit 8ac7b08869). SFace is
    the only remaining Apache-2.0 face embedder in opencv_zoo, so the
    pack was renamed from `yunet-mfn` → `yunet-sface`. The detector
    (YuNet 2023mar) is unchanged. See docs/14 §2.3.

Both backbones come from the OpenCV Zoo model collection (Apache-2.0).
This is the **default** model pack going forward: it satisfies the
Pi 3B target (≤10 MB on disk, ≤150 MB RAM), the AC-9 commercial
compliance goal (Apache-2.0), and is the best publicly-available
open-license replacement for the InsightFace MobileFaceNet stack.

The detector is the OpenCV `FaceDetectorYN` wrapper, which gives us
5-point landmarks for free (so the ArcFace-style Aligner in
`pick_face.ingest.align` works without modification).

Note: `yunet-mfn` is kept as a deprecated alias — `init-models --pack
yunet-mfn` now raises a clear error pointing users to `yunet-sface`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from pick_face.ingest.align import ARCFACE_REFERENCE_5P, Aligner, warp_to_112
from pick_face.ingest.detector import Detection, Detector
from pick_face.ingest.embedder import Embedder, l2_normalize
from pick_face.platform.pack import (
    LicenseClass,
    ModelPack,
    PackDescriptor,
)

# ---------------------------------------------------------------------------
# Weights metadata — pinned to upstream opencv_zoo main @ 2026-08-07.
# SHA256 are populated (no longer placeholders); CI re-pins via
# `scripts/pin_sha256.py` whenever we deliberately bump versions.
# ---------------------------------------------------------------------------

YUNET_FILENAME = "yunet_2023mar.onnx"
YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
YUNET_SIZE = 232_589  # bytes

SFACE_FILENAME = "face_recognition_sface_2021dec_int8.onnx"
SFACE_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_recognition_sface/face_recognition_sface_2021dec_int8.onnx"
)
SFACE_SHA256 = "2b0e941e6f16cc048c20aee0c8e31f569118f65d702914540f7bfdc14048d78a"
SFACE_SIZE = 9_896_933  # bytes (~9.9 MB)

YUNET_SFACE_DESCRIPTOR = PackDescriptor(
    pack_id="yunet-sface",
    display_name="YuNet + SFace INT8 (OpenCV Zoo)",
    detector_name="YuNet (face_detection_yunet_2023mar.onnx)",
    embedder_name="SFace INT8 (face_recognition_sface_2021dec_int8.onnx)",
    detector_sha256=YUNET_SHA256,
    embedder_sha256=SFACE_SHA256,
    detector_size_bytes=YUNET_SIZE,
    embedder_size_bytes=SFACE_SIZE,
    detector_url=YUNET_URL,
    embedder_url=SFACE_URL,
    license_class=LicenseClass.PERMISSIVE,
    license_name="Apache-2.0 (OpenCV Zoo)",
    license_spdx="Apache-2.0",
    license_notice_text="",  # permissive — no notice required
    accuracy_lfw=0.9945,  # SFace INT8 author-reported; YuNet alone ~99.16%
    notes=(
        "ARM-friendly default pack. ~10 MB on disk, ~150 MB RAM at runtime. "
        "Recommended for Pi 3B / RK3588 / low-end laptops. AC-9 commercial "
        "compliant (Apache-2.0). Replaces the yunet-mfn pack (MobileFaceNet "
        "INT8) after upstream removed the MobileFaceNet weights during the "
        "2025-07-31 opencv_zoo → HuggingFace migration."
    ),
    tags=["arm-friendly", "low-ram", "default"],
)


# ---------------------------------------------------------------------------
# Detector adapter
# ---------------------------------------------------------------------------


class YuNetDetector(Detector):
    """Wraps cv2.FaceDetectorYN behind our Detector protocol.

    YuNet's output is a (N, 15) float32 matrix; columns are
    (x, y, w, h, *5 landmarks x,y, score). We unpack into Detection
    objects and warp each face to 112x112 using the existing aligner.
    """

    def __init__(self, onnx_path: Path, det_size: tuple[int, int] = (320, 320)) -> None:
        import cv2  # local import — pick-face core must stay cv2-light

        self._cv2 = cv2
        self._detector = cv2.FaceDetectorYN.create(
            str(onnx_path),
            "",
            (det_size[0], det_size[1]),
            score_threshold=0.6,
            nms_threshold=0.3,
            top_k=5000,
        )
        self._det_size = det_size

    @property
    def name(self) -> str:
        return "YuNet"

    @property
    def model_version(self) -> str:
        return YUNET_FILENAME

    def warmup(self, det_size: tuple[int, int]) -> None:
        # Run a blank image through to force-allocate internal buffers.
        blank = np.zeros((det_size[1], det_size[0], 3), dtype=np.uint8)
        try:
            self._detector.detect(blank)
        except Exception:
            pass

    def detect(self, bgr: np.ndarray) -> list[Detection]:
        # YuNet is fully convolutional — accept any input size, rescale
        # bbox back to original image coords (we used det_size at create).
        h, w = bgr.shape[:2]
        if (w, h) != self._det_size:
            self._detector.setInputSize((w, h))
        _, raw = self._detector.detect(bgr)
        if raw is None:
            return []
        out: list[Detection] = []
        for row in raw:
            x, y, ww, hh = row[0:4]
            score = float(row[14])
            landmarks = np.asarray(row[4:14], dtype=np.float32).reshape(5, 2)
            chip = warp_to_112(bgr, landmarks)
            out.append(
                Detection(
                    bbox=(float(x), float(y), float(x + ww), float(y + hh)),
                    det_score=score,
                    landmarks=landmarks,
                    chip=chip,
                    quality=_rough_quality_chip(chip),
                )
            )
        return out


# ---------------------------------------------------------------------------
# Embedder adapter
# ---------------------------------------------------------------------------


class SFaceEmbedder(Embedder):
    """Wraps a SFace ONNX (INT8-quantised) behind our Embedder.

    Input  : 112x112 RGB float32 in [0, 1]  (NCHW)
    Output : 128-D float32, L2-normalised for cosine distance.

    SFace INT8 is the Apache-2.0 face embedder shipped by opencv_zoo;
    it replaced MobileFaceNet INT8 after the upstream MobileFaceNet
    weights were removed in 2025 (see module docstring).
    """

    dim = 128  # SFace embeds to 128-D (same dim as the deprecated MFN)

    def __init__(self, onnx_path: Path) -> None:
        import onnxruntime as ort

        sess_opts = ort.SessionOptions()
        sess_opts.intra_op_num_threads = 1  # Pi 3B: avoid context thrash
        sess_opts.inter_op_num_threads = 1
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._sess = ort.InferenceSession(
            str(onnx_path), sess_options=sess_opts, providers=["CPUExecutionProvider"]
        )
        self._input_name = self._sess.get_inputs()[0].name

    @property
    def model_version(self) -> str:
        return SFACE_FILENAME

    def embed(self, chip_rgb: np.ndarray) -> np.ndarray:
        # SFace expects RGB float32 in [0, 1], NCHW. Our warp_to_112()
        # already returns a 112x112 RGB uint8 chip; just normalise.
        x = chip_rgb.astype(np.float32) / 255.0
        x = np.transpose(x, (2, 0, 1))[None, ...]  # NCHW
        out = self._sess.run(None, {self._input_name: x})[0]
        v = np.asarray(out[0], dtype=np.float32)
        return l2_normalize(v)


# ---------------------------------------------------------------------------
# Aligner (re-uses ArcFace-style 5-pt warp — same geometry as InsightFace)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArcFaceAligner(Aligner):
    ref_landmarks: np.ndarray = field(default_factory=lambda: ARCFACE_REFERENCE_5P.copy())

    def warp(self, bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        return warp_to_112(bgr, landmarks)


# ---------------------------------------------------------------------------
# Pack plumbing
# ---------------------------------------------------------------------------


class YuNetSfacePack(ModelPack):
    descriptor = YUNET_SFACE_DESCRIPTOR

    def expected_files(self) -> list[str]:
        return [YUNET_FILENAME, SFACE_FILENAME]

    def build_detector(
        self, model_dir: Path, ctx_id: int = 0, det_size: tuple[int, int] = (320, 320)
    ) -> Detector:
        onnx = model_dir / self.descriptor.pack_id / YUNET_FILENAME
        if not onnx.exists():
            from pick_face.core.errors import ModelNotFoundError

            raise ModelNotFoundError(
                f"{YUNET_FILENAME} missing at {onnx}. "
                f"Run `pick-face init-models --pack yunet-sface --allow-network`."
            )
        _verify_sha256(onnx, YUNET_SHA256, label="YuNet")
        return YuNetDetector(onnx, det_size=det_size)

    def build_embedder(self, model_dir: Path) -> Embedder:
        onnx = model_dir / self.descriptor.pack_id / SFACE_FILENAME
        if not onnx.exists():
            from pick_face.core.errors import ModelNotFoundError

            raise ModelNotFoundError(
                f"{SFACE_FILENAME} missing at {onnx}. "
                f"Run `pick-face init-models --pack yunet-sface --allow-network`."
            )
        _verify_sha256(onnx, SFACE_SHA256, label="SFace")
        return SFaceEmbedder(onnx)

    def build_aligner(self) -> Aligner:
        return ArcFaceAligner()

    def download_to(self, target_dir: Path, *, progress=None) -> list[Path]:
        """Fetch from GitHub release URLs. Pure stdlib so the pack
        stays dependency-free beyond numpy / opencv / onnxruntime."""

        target_dir.mkdir(parents=True, exist_ok=True)
        out: list[Path] = []
        for url, fname, expected in [
            (YUNET_URL, YUNET_FILENAME, YUNET_SHA256),
            (SFACE_URL, SFACE_FILENAME, SFACE_SHA256),
        ]:
            dst = target_dir / fname
            _fetch_with_progress(url, dst, progress=progress)
            _verify_sha256(dst, expected, label=fname)
            out.append(dst)
        return out


# ---------------------------------------------------------------------------
# Deprecated alias — `yunet-mfn` (route B initial name).
#
# Kept as a friendly redirect: trying to `init-models --pack yunet-mfn`
# surfaces a clear message instead of a cryptic 404. The actual MFN
# URL upstream is gone, so the only honest thing to do is to refuse.
# ---------------------------------------------------------------------------


class _DeprecatedYuNetMFNPack(ModelPack):
    """Deprecated alias for the original v2.0.0-dev0 default pack.

    The pack id `yunet-mfn` was renamed to `yunet-sface` after the
    upstream MobileFaceNet INT8 weights were removed from
    `opencv/opencv_zoo` (commit 8ac7b08869, 2025-07-31). Use
    `pick-face init-models --pack yunet-sface` instead.
    """

    descriptor = PackDescriptor(
        pack_id="yunet-mfn",
        display_name="[DEPRECATED] YuNet + MobileFaceNet INT8 — use yunet-sface",
        detector_name="(deprecated)",
        embedder_name="(deprecated — MobileFaceNet INT8 removed upstream)",
        detector_sha256="",
        embedder_sha256="",
        detector_size_bytes=0,
        embedder_size_bytes=0,
        detector_url=None,
        embedder_url=None,
        license_class=LicenseClass.PERMISSIVE,
        license_name="Apache-2.0 (deprecated — see yunet-sface)",
        license_spdx="Apache-2.0",
        notes=(
            "DEPRECATED alias. Upstream removed MobileFaceNet INT8 in 2025; "
            "use `yunet-sface` (YuNet + SFace INT8) for an equivalent "
            "Apache-2.0 pack. See docs/14 §2.3."
        ),
        tags=["deprecated"],
    )

    def expected_files(self) -> list[str]:
        return []

    def build_detector(self, model_dir: Path, ctx_id: int = 0, det_size=(320, 320)) -> Detector:  # noqa: ARG002
        raise RuntimeError(
            "pack 'yunet-mfn' is deprecated (upstream MobileFaceNet INT8 "
            "weights were removed from opencv_zoo in 2025). "
            "Use `pick-face init-models --pack yunet-sface` instead."
        )

    def build_embedder(self, model_dir: Path) -> Embedder:  # noqa: ARG002
        raise RuntimeError(
            "pack 'yunet-mfn' is deprecated (upstream MobileFaceNet INT8 "
            "weights were removed from opencv_zoo in 2025). "
            "Use `pick-face init-models --pack yunet-sface` instead."
        )

    def build_aligner(self) -> Aligner:
        raise RuntimeError("pack 'yunet-mfn' is deprecated; use yunet-sface.")

    def download_to(self, target_dir: Path, *, progress=None) -> list[Path]:  # noqa: ARG002
        raise RuntimeError(
            "pack 'yunet-mfn' is deprecated (upstream MobileFaceNet INT8 "
            "weights were removed from opencv_zoo in 2025). "
            "Use `pick-face init-models --pack yunet-sface --allow-network`."
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rough_quality_chip(chip: np.ndarray) -> float:
    """Cheap blur score, same heuristic as InsightFace path (see
    pick_face.ingest.detector._rough_quality)."""
    import math

    import cv2

    gray = cv2.cvtColor(chip, cv2.COLOR_RGB2GRAY)
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    if lap_var <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - math.exp(-lap_var / 100.0)))


def _verify_sha256(path: Path, expected: str, *, label: str) -> None:
    if expected.startswith("<TBD"):
        # First-build placeholder; emit a warning and skip. CI populates
        # the real hash before any release is tagged.
        import warnings

        warnings.warn(f"{label} SHA256 not pinned; skipping verification", stacklevel=2)
        return
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != expected:
        raise RuntimeError(
            f"{label} sha256 mismatch: expected {expected}, got {actual}. "
            f"Refusing to load — re-download or pin a new hash."
        )


def _fetch_with_progress(url: str, dst: Path, *, progress=None) -> None:
    import urllib.request

    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 — intentional
        total = int(resp.headers.get("Content-Length") or 0)
        with dst.open("wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                if progress and total:
                    progress(len(chunk), total)
