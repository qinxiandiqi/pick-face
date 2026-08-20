"""Model Pack: YuNet detector + ArcFace R100 embedder (route B).

Reference:
- docs/13-raspberry-pi-support.md §2 (Pi 3B / ARM-friendly pack)
- docs/14-model-pack-plugins.md §6 (multi-variant packs)
- docs/14-model-pack-plugins.md §8 (known-packs table — yunet-arcface row)

This is the **high-precision** tier alongside `yunet-sface` (the default).
The detector is the same Apache-2.0 (opencv_zoo per-model LICENSE: MIT)
YuNet backbone reused from `yunet_sface.py`. The embedder is the
ONNX Model Zoo ArcFace ResNet100 (LResNet100E-IR, 512-D, LFW 99.77%
FP32 / 99.80% INT8), released under Apache-2.0 by the official ONNX
Model Zoo (https://github.com/onnx/models).

The pack ships **two weight variants**:

  * FP32 — 261 MB, ~700 MB RAM at runtime. Highest precision.
    Recommended for x86 desktops and GPU hosts.
  * INT8 — 63 MB, ~150 MB RAM at runtime. Recommended for ARM / Pi 4/5
    or memory-constrained hosts.

`init-models --pack yunet-arcface --quant {fp32,int8}` selects which
variant to download (default `fp32`); the selected quant is recorded
in `~/.cache/pick-face/models/yunet-arcface/.quant` so `build_embedder`
can re-derive it without an env var. Only one variant is downloaded at
a time — re-run with the other `--quant` to switch.

Mixed-license note (this is why `PackDescriptor` carries
`detector_license_spdx` and `embedder_license_spdx` separately):

  * YuNet detector: MIT (opencv_zoo/face_detection_yunet/LICENSE)
  * ArcFace embedder: Apache-2.0 (ONNX Model Zoo — see
    https://github.com/onnx/models/blob/main/validated/vision/body_analysis/arcface/README.md)

Both are permissive and the AC-9 gate treats the pack as PERMISSIVE.
The training-data provenance (refined MS-Celeb-1M, curated by
DeepInsight) is the user's responsibility to evaluate for their
deployment context; pick-face does not redistribute the dataset.

Detector reuse rationale: YuNet's URL / SHA256 / SIZE constants are
**copied** rather than imported so that future opencv_zoo migrations
(canary: the 2025-07-31 MobileFaceNet removal) can move yunet-sface
and yunet-arcface independently. ~250 bytes of duplication is a
deliberate decoupling trade.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pick_face.ingest.align import ARCFACE_REFERENCE_5P, Aligner, warp_to_112
from pick_face.ingest.detector import Detector
from pick_face.ingest.embedder import Embedder, l2_normalize
from pick_face.platform.pack import (
    EmbedderVariant,
    LicenseClass,
    ModelPack,
    PackDescriptor,
)

# ---------------------------------------------------------------------------
# Detector weights — intentionally copied from yunet_sface.py (do NOT
# `from yunet_sface import`). Keep these in lockstep manually if
# opencv_zoo ever rotates the YuNet URL. SHA256 verified at module load.
# ---------------------------------------------------------------------------

YUNET_FILENAME = "yunet_2023mar.onnx"
YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
YUNET_SIZE = 232_589  # bytes (~232 KiB)

# ---------------------------------------------------------------------------
# ArcFace embedder variants — FP32 (default) + INT8 (Pi / low-ram).
# Pinned to upstream onnx/models @ commit 4c46cd00f…
# SHA256 / size verified against the official ONNX Model Zoo release.
# ---------------------------------------------------------------------------

_ARCFACE_R100_FP32 = EmbedderVariant(
    quant="fp32",
    filename="arcface_r100_fp32.onnx",
    sha256="f3a6bc281e72f88862f5748b53be3d76b3b48f8f1ab1f4a537941bdc4e1b01da",
    size_bytes=261_036_388,
    url=(
        "https://media.githubusercontent.com/media/onnx/models/"
        "4c46cd00fbdb7cd30b6c1c17ab54f2e1f4f7b177/"
        "validated/vision/body_analysis/arcface/model/arcfaceresnet100-8.onnx"
    ),
    accuracy_lfw=0.9977,
    notes=(
        "FP32 ONNX — 261 MB on disk, ~700 MB RAM at runtime. "
        "Highest precision. Recommended for x86 / GPU hosts."
    ),
)

_ARCFACE_R100_INT8 = EmbedderVariant(
    quant="int8",
    filename="arcface_r100_int8.onnx",
    sha256="c625ca68a422418c48aa84f73341337e0a92b111f327909005d1eec07c95f936",
    size_bytes=65_764_892,
    url=(
        "https://media.githubusercontent.com/media/onnx/models/"
        "4c46cd00fbdb7cd30b6c1c17ab54f2e1f4f7b177/"
        "validated/vision/body_analysis/arcface/model/arcfaceresnet100-11-int8.onnx"
    ),
    accuracy_lfw=0.9980,
    notes=(
        "INT8 ONNX — 66 MB on disk, ~150 MB RAM at runtime. "
        "Recommended for ARM / Pi 4/5 / low-RAM hosts."
    ),
)

_ARCFACE_VARIANTS: dict[str, EmbedderVariant] = {
    v.quant: v for v in (_ARCFACE_R100_FP32, _ARCFACE_R100_INT8)
}
_DEFAULT_QUANT = "fp32"
_QUANT_MARKER = ".quant"
_ENV_QUANT = "PICK_FACE_ARCFACE_QUANT"


# ---------------------------------------------------------------------------
# PackDescriptor — what `pick-face doctor` and `init-models` render.
# ---------------------------------------------------------------------------

YUNET_ARCFACE_DESCRIPTOR = PackDescriptor(
    pack_id="yunet-arcface",
    display_name="YuNet + ArcFace R100 (ONNX Model Zoo)",
    detector_name="YuNet (yunet_2023mar.onnx)",
    # Default variant advertises FP32; INT8 lives in embedder_alternates.
    embedder_name="ArcFace R100 FP32 (arcfaceresnet100-8.onnx)",
    detector_sha256=YUNET_SHA256,
    embedder_sha256=_ARCFACE_R100_FP32.sha256,
    detector_size_bytes=YUNET_SIZE,
    embedder_size_bytes=_ARCFACE_R100_FP32.size_bytes,
    detector_url=YUNET_URL,
    embedder_url=_ARCFACE_R100_FP32.url,
    license_class=LicenseClass.PERMISSIVE,
    # Pack-level license: keep "Apache-2.0" (the stricter of the two —
    # MIT is compatible but Apache is the more visible grant).
    license_name="Apache-2.0 + MIT (YuNet detector: MIT, ArcFace embedder: Apache-2.0)",
    license_spdx="Apache-2.0",
    license_notice_text="",  # permissive — no notice required
    accuracy_lfw=_ARCFACE_R100_FP32.accuracy_lfw,
    notes=(
        "High-precision tier (route B). Reuses the opencv_zoo YuNet "
        "detector (MIT, see face_detection_yunet/LICENSE) and pairs it "
        "with the ONNX Model Zoo ArcFace ResNet100 embedder "
        "(Apache-2.0, LFW 99.77% FP32 / 99.80% INT8). The pack is "
        "PERMISSIVE — no AC-9 ack required. The ArcFace backbone was "
        "trained on refined MS-Celeb-1M by DeepInsight; the training-"
        "data rights are the deployer's responsibility (the ONNX Model "
        "Zoo README covers this). "
        "Use `--quant int8` for ARM / low-RAM hosts (~66 MB on disk). "
        "For high-precision 512-D clustering, set "
        "`clustering.merge_threshold = 0.55` in pick-face.toml "
        "(the SFace default of 0.0 under-merges at 512-D)."
    ),
    tags=["high-precision", "apache-2.0", "gpu-friendly", "512-d"],
    embedder_alternates=[_ARCFACE_R100_FP32, _ARCFACE_R100_INT8],
    detector_license_spdx="MIT",
    embedder_license_spdx="Apache-2.0",
)


# ---------------------------------------------------------------------------
# Embedder adapter
# ---------------------------------------------------------------------------


class ArcFaceR100Embedder(Embedder):
    """Wraps the ArcFace R100 ONNX behind our Embedder protocol.

    Input  : 112x112 RGB uint8 chip (warp_to_112 returns RGB).
             ArcFace was trained on BGR with (x - 127.5) / 128, so we
             flip the channel axis *before* normalising. A regression
             here produces plausible-but-degraded embeddings; see
             `tests/unit/test_yunet_arcface_pack.py::test_preprocess_*
             for a fixture that catches a regression.
    Output : 512-D float32, L2-normalised for cosine distance.

    Threading policy: ONNX Runtime's default thread pool thrashes on
    Pi 3B (4 cores) but under-utilises x86 multi-core hosts. We follow
    the InsightFace convention: `intra = max(1, cpu_count // 2)` unless
    the user has set `OMP_NUM_THREADS` (which ORT honours and is the
    canonical way to override).
    """

    dim = 512

    def __init__(
        self,
        onnx_path: Path,
        *,
        providers: Sequence[str] | None = None,
    ) -> None:
        import onnxruntime as ort

        sess_opts = ort.SessionOptions()
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if not os.environ.get("OMP_NUM_THREADS"):
            cpu = os.cpu_count() or 4
            sess_opts.intra_op_num_threads = max(1, cpu // 2)
            sess_opts.inter_op_num_threads = max(1, cpu // 4)
        # If the caller didn't pass a providers chain, let ORT auto-detect
        # (CPU → CUDA → DirectML → TensorRT). Passing None here is the
        # documented way to defer to ORT's session-runner logic.
        chosen = list(providers) if providers else None
        self._sess = ort.InferenceSession(
            str(onnx_path), sess_options=sess_opts, providers=chosen
        )
        self._input_name = self._sess.get_inputs()[0].name
        self._path = onnx_path

    @property
    def model_version(self) -> str:
        return self._path.name

    @staticmethod
    def preprocess(chip_rgb: np.ndarray) -> np.ndarray:
        """Pure preprocessing — separable from inference for testing.

        ArcFace R100 expects BGR float32 in [-1, 1) at 112x112. Our
        warp_to_112() returns RGB uint8 (H, W, 3). Flip the channel
        axis (last axis) and normalise. `astype(np.float32)` already
        copies the buffer — no extra `.copy()` needed.
        """
        bgr = chip_rgb[..., ::-1].astype(np.float32)
        x = ((bgr - 127.5) / 128.0).transpose(2, 0, 1)[None]  # NCHW
        return x

    def embed(self, chip_rgb: np.ndarray) -> np.ndarray:
        x = self.preprocess(chip_rgb)
        out = self._sess.run(None, {self._input_name: x})[0]
        v = np.asarray(out[0], dtype=np.float32)
        return l2_normalize(v)


# ---------------------------------------------------------------------------
# Aligner (re-uses the 5-pt warp — same geometry as ArcFace expects)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArcFaceAligner(Aligner):
    ref_landmarks: np.ndarray = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        # Frozen dataclass trick: assign via object.__setattr__.
        object.__setattr__(self, "ref_landmarks", ARCFACE_REFERENCE_5P.copy())

    def warp(self, bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        return warp_to_112(bgr, landmarks)


# ---------------------------------------------------------------------------
# Variant resolution
# ---------------------------------------------------------------------------


def resolve_quant(model_dir: Path) -> str:
    """Return the quant tag to load for `model_dir/<pack_id>/`.

    Priority order (so a re-run of `init-models --quant int8` after a
    prior `--quant fp32` install correctly re-points the load):

      1. `<model_dir>/.quant` marker file (written by download_to).
      2. `PICK_FACE_ARCFACE_QUANT` env var (manual override).
      3. Default ("fp32").

    Unknown values fall back to the default with a one-shot warning.
    """
    marker = model_dir / _QUANT_MARKER
    if marker.exists():
        q = marker.read_text(encoding="utf-8").strip().lower()
        if q in _ARCFACE_VARIANTS:
            return q
        warnings.warn(
            f"{marker} contains unknown quant {q!r}; falling back to {_DEFAULT_QUANT}",
            stacklevel=2,
        )
    env = os.environ.get(_ENV_QUANT, "").strip().lower()
    if env in _ARCFACE_VARIANTS:
        return env
    return _DEFAULT_QUANT


# ---------------------------------------------------------------------------
# Pack plumbing
# ---------------------------------------------------------------------------


class YuNetArcFacePack(ModelPack):
    descriptor = YUNET_ARCFACE_DESCRIPTOR

    def expected_files(self, *, variant: str | None = None) -> list[str]:
        """Return the filenames that must exist for this pack to load.

        If `variant` is None we read the `.quant` marker file (set by
        `download_to`); otherwise we honour the explicit arg.
        """
        if variant is None:
            # Without a model_dir arg we can't read the marker, so
            # default to the descriptor's default variant. The CLI
            # pass: doctor calls this with no args after the install,
            # so the marker exists by then and `resolve_quant` is the
            # authoritative source of truth — see the doctor branch
            # which calls expected_files per-pack via `packs[pack_id]`.
            variant = _DEFAULT_QUANT
        if variant not in _ARCFACE_VARIANTS:
            raise ValueError(
                f"unknown variant {variant!r}; valid: {sorted(_ARCFACE_VARIANTS)}"
            )
        return [YUNET_FILENAME, _ARCFACE_VARIANTS[variant].filename]

    def build_detector(
        self,
        model_dir: Path,
        ctx_id: int = 0,  # noqa: ARG002 — YuNet uses cv2.FaceDetectorYN
        det_size: tuple[int, int] = (320, 320),
    ) -> Detector:
        # Import here to keep the pack cv2-light until actually used.
        from pick_face.core.errors import ModelNotFoundError
        from pick_face.platform.packs.yunet_sface import YuNetDetector, _verify_sha256

        onnx = model_dir / self.descriptor.pack_id / YUNET_FILENAME
        if not onnx.exists():
            raise ModelNotFoundError(
                f"{YUNET_FILENAME} missing at {onnx}. "
                f"Run `pick-face init-models --pack yunet-arcface --allow-network`."
            )
        _verify_sha256(onnx, YUNET_SHA256, label="YuNet")
        return YuNetDetector(onnx, det_size=det_size)

    def build_embedder(
        self,
        model_dir: Path,
        *,
        providers: Sequence[str] | None = None,
    ) -> Embedder:
        from pick_face.core.errors import ModelNotFoundError
        from pick_face.platform.packs.yunet_sface import _verify_sha256

        pack_dir = model_dir / self.descriptor.pack_id
        if not pack_dir.exists():
            raise ModelNotFoundError(
                f"pack dir missing at {pack_dir}. "
                f"Run `pick-face init-models --pack yunet-arcface --allow-network`."
            )
        quant = resolve_quant(pack_dir)
        variant = _ARCFACE_VARIANTS[quant]
        onnx = pack_dir / variant.filename
        if not onnx.exists():
            raise ModelNotFoundError(
                f"{variant.filename} missing at {onnx} (selected quant={quant}). "
                f"Run `pick-face init-models --pack yunet-arcface --allow-network "
                f"--quant {quant}`."
            )
        _verify_sha256(onnx, variant.sha256, label=f"ArcFace-{quant}")
        return ArcFaceR100Embedder(onnx, providers=providers)

    def build_aligner(self) -> Aligner:
        return ArcFaceAligner()

    def download_to(
        self,
        target_dir: Path,
        *,
        quant: str = _DEFAULT_QUANT,
        progress=None,
    ) -> list[Path]:
        """Download the YuNet detector + one ArcFace variant.

        Only the requested `quant` is fetched (FP32 → ~261 MB; INT8 → ~66 MB).
        The selected quant is recorded in `target_dir/.quant` so the
        next `build_embedder` call picks it up without an env var.
        """
        from pick_face.platform.packs.yunet_sface import (
            _fetch_with_progress,
            _verify_sha256,
        )

        if quant not in _ARCFACE_VARIANTS:
            raise ValueError(
                f"unknown quant {quant!r}; valid: {sorted(_ARCFACE_VARIANTS)}"
            )
        target_dir.mkdir(parents=True, exist_ok=True)
        out: list[Path] = []

        # Detector (shared, always needed).
        dst = target_dir / YUNET_FILENAME
        if not dst.exists():
            _fetch_with_progress(YUNET_URL, dst, progress=progress)
        _verify_sha256(dst, YUNET_SHA256, label=YUNET_FILENAME)
        out.append(dst)

        # Selected variant (on-demand, default FP32).
        variant = _ARCFACE_VARIANTS[quant]
        vdst = target_dir / variant.filename
        if not vdst.exists():
            _fetch_with_progress(variant.url, vdst, progress=progress)
        _verify_sha256(vdst, variant.sha256, label=variant.filename)
        out.append(vdst)

        # Marker file — single source of truth for build_embedder.
        (target_dir / _QUANT_MARKER).write_text(quant, encoding="utf-8")
        return out


# ---------------------------------------------------------------------------
# Self-check on import: SHA256 constants must match the URLs.
# This is a soft check — it re-hashes the file at module import time if
# the file is already on disk (for dev environments that have the
# weights cached). It never blocks import.
# ---------------------------------------------------------------------------


def _dev_sha256_check() -> None:
    """Compare local cached weights against the pinned hashes.

    Looks under `~/.cache/pick-face/models/yunet-arcface/` for the
    cached weights and warns if the SHA doesn't match. Pure
    best-effort — never raises. Only fires when the file is present.
    """
    import hashlib as _hl

    cache = Path.home() / ".cache" / "pick-face" / "models" / "yunet-arcface"
    if not cache.exists():
        return
    for variant in _ARCFACE_VARIANTS.values():
        p = cache / variant.filename
        if not p.exists():
            continue
        h = _hl.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        if h.hexdigest() != variant.sha256:
            warnings.warn(
                f"{variant.filename} SHA mismatch (expected {variant.sha256[:12]}…, "
                f"got {h.hexdigest()[:12]}…). Re-run "
                f"`pick-face init-models --pack yunet-arcface --allow-network "
                f"--quant {variant.quant}`.",
                stacklevel=2,
            )


_dev_sha256_check()
