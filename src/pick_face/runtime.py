"""InsightFace-backed implementations of Detector/Embedder/Aligner.

Reference:
- docs/03 §3 (Provider routing: auto → cuda → directml → cpu)
- docs/09 §4–6 (detect/align/embed pipeline; SCRFD + ArcFace w600k_r50)
- docs/10 §2.1 (buffalo_l / antelopev2 / buffalo_sc)
- docs/11 §3.2 (AC-9: refuse non-commercial model unless user opted in)

This module intentionally does *not* top-level-import `insightface` /
`onnxruntime`. The 100+ MB InsightFace pack should be paid for at the first
forward call, not at every `pick-face --version`. Importing this module
without those packages is fine; the error is raised when you actually call
`load_insightface_runner()`.
"""

from __future__ import annotations

from typing import Sequence

from pick_face.errors import (
    CommercialLicenseError,
    ModelLoadError,
    ModelNotFoundError,
)
from pick_face.config import PickFaceConfig, INSIGHTFACE_MODELS


def resolve_providers(requested: str) -> list[str]:
    """Map --provider string to an ordered onnxruntime provider list.

    Order matters: the first installed provider wins, and `auto` probes
    cuda → directml → cpu in that order on the user's machine.
    """
    requested = requested.lower()
    if requested == "auto":
        return _probe_providers()
    if requested == "cpu":
        return ["CPUExecutionProvider"]
    if requested == "cuda":
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    if requested == "directml":
        return ["DmlExecutionProvider", "CPUExecutionProvider"]
    if requested == "tensorrt":
        return ["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]
    raise ModelLoadError(f"unknown provider: {requested!r}")


def _probe_providers() -> list[str]:
    """Best-effort probe: cuda → directml → cpu.

    Cheap and side-effect-free: just imports ``onnxruntime`` once.
    """
    try:
        import onnxruntime  # noqa: F401
    except ImportError as e:
        raise ModelLoadError(
            "onnxruntime is not installed; install pick-face[gpu] or pick-face[gpu-cuda12]"
        ) from e
    # We don't enumerate providers here (it can take ~200 ms on cold start);
    # the runtime decision happens at the first model prepare().
    return ["CPUExecutionProvider"]


def check_commercial(cfg: PickFaceConfig) -> None:
    """AC-9 guard: raise CommercialLicenseError if user is non-compliant.

    Per docs/11 §3.2: if `model_name` is one of the InsightFace packs and
    `accept_noncommercial_model_license = false` (fail-safe default), we
    refuse to start.
    """
    if cfg.is_commercial_unsafe():
        raise CommercialLicenseError(
            f"Model {cfg.runtime.model_name!r} is licensed for non-commercial "
            "research only (InsightFace buffalo* / antelopev2). You have not "
            "acknowledged the license in [runtime] accept_noncommercial_model_license. "
            "See docs/11-commercial-compliance.md for the three legal paths."
        )


def load_insightface_runner(cfg: PickFaceConfig) -> "_InsightFaceRunner":
    """Build an InsightFace-backed detector+embedder.

    Returns a single object that bundles detect→align→embed (InsightFace's
    FaceAnalysis.get() returns faces with embeddings already done).

    Raises:
        ModelLoadError: onnxruntime / insightface not installed.
        ModelNotFoundError: local model pack missing *and* --allow-network
            wasn't requested.
        CommercialLicenseError: see check_commercial above.
    """
    check_commercial(cfg)

    try:
        import insightface  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError as e:
        raise ModelLoadError(
            "insightface + onnxruntime not installed in this environment. "
            "Install with: uv pip install 'pick-face[gpu]'" if "insightface" in str(e) else
            "onnxruntime not installed; install pick-face[gpu]"
        ) from e

    from insightface.app import FaceAnalysis

    providers = resolve_providers(cfg.runtime.provider)
    model_dir = str(cfg.runtime.model_dir)
    model_root = model_dir.rsplit("/", 1)[0] if model_dir.endswith(cfg.runtime.model_name) else model_dir

    # The pack files live in <model_root>/<model_name>/. If absent, we raise
    # ModelNotFoundError with a clear next step (init-models --allow-network).
    from pathlib import Path
    pack_dir = Path(model_root) / cfg.runtime.model_name
    if not pack_dir.exists():
        raise ModelNotFoundError(
            f"model pack not found at {pack_dir}. Run "
            "`pick-face init-models --allow-network` to download, or set "
            "[runtime] model_dir to a directory that already contains it."
        )

    try:
        app = FaceAnalysis(
            name=cfg.runtime.model_name,
            root=model_root,
            providers=providers,
            allowed_modules=None,
        )
        app.prepare(ctx_id=0, det_size=(cfg.detection.det_size, cfg.detection.det_size))
    except Exception as e:
        raise ModelLoadError(f"insightface.prepare failed: {e}") from e

    return _InsightFaceRunner(
        app=app,
        model_name=cfg.runtime.model_name,
        det_thresh=cfg.detection.det_thresh,
        det_size=(cfg.detection.det_size, cfg.detection.det_size),
        providers=providers,
    )


class _InsightFaceRunner:
    """Bundles detect → align → embed in one wrapper.

    Single `.run(bgr)` returns one Detection per face, already with the
    aligned 112x112 chip populated and the embedding NOT included
    (InsightFace returns the embedding too; we keep it for the cluster
    stage rather than the Detection).
    """

    def __init__(self, app, model_name: str, det_thresh: float,
                 det_size: tuple[int, int], providers: Sequence[str]) -> None:
        self._app = app
        self.name = model_name
        self.model_version = f"{model_name}@{getattr(app, 'model_dir', '').rsplit('/', 1)[-1] or 'unknown'}"
        self.det_thresh = det_thresh
        self.det_size = det_size
        self.providers = list(providers)

    def warmup(self) -> None:
        """First-pass warmup: run a tiny blank image through to force alloc."""
        import numpy as np

        blank = np.zeros((self.det_size[1], self.det_size[0], 3), dtype=np.uint8)
        try:
            self._app.get(blank)
        except Exception:
            # Warmup failures are non-fatal — the first real image will retry.
            pass

    def detect(self, bgr):
        """Detect & embed faces in *bgr* image.

        Returns a list of tuples (Detection, embedding_or_None).
        """
        import numpy as np

        from pick_face.align import warp_to_112
        from pick_face.detector import detection_from_insightface

        faces = self._app.get(bgr)
        out: list[tuple] = []
        for f in faces:
            if float(f.det_score) < self.det_thresh:
                continue
            kps = np.asarray(f.kps, dtype=np.float32)
            chip = warp_to_112(bgr, kps)
            det = detection_from_insightface(f, chip)
            embedding = getattr(f, "embedding", None)
            emb = np.asarray(embedding, dtype=np.float32) if embedding is not None else None
            out.append((det, emb))
        return out
