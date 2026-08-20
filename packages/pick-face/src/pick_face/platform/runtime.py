"""Runtime glue: ONNX provider probing + ModelPack factory (route B).

Reference:
- docs/03 §3 (Provider routing: auto → cuda → directml → cpu)
- docs/10 §2.1 (yunet-mfn / buffalo_l / antelopev2 / buffalo_sc)
- docs/11 §3.2 (AC-9: refuse NC-research model unless user opted in)
- docs/14 §2 (ModelPack Protocol + entry-points)

This module intentionally does *not* top-level-import `onnxruntime`. The
100+ MB model packs should be paid for at the first forward call, not at
every `pick-face --version`. Importing this module without onnxruntime is
fine; the error is raised when you actually call `load_pack_runner()` /
`load_insightface_runner()`.

After route B, the canonical entry point is `load_pack_runner(cfg)` —
it resolves the ModelPack via entry-points and returns a unified
`PackRunner`. The legacy `load_insightface_runner()` is kept as the
narrow implementation that backs the `buffalo_l` / `buffalo_sc` /
`antelopev2` opt-in packs (via `pick-face-modelpack-insightface`).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pick_face.core.config import PickFaceConfig
from pick_face.core.errors import (
    CommercialLicenseError,
    ModelLoadError,
    ModelNotFoundError,
)


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
    """Best-effort probe: cuda → directml → cpu (docs/03 §3, M3 / T-201).

    Enumerates the actually-installed onnxruntime providers and returns
    the chain in priority order. The first entry is the primary; the
    trailing CPUExecutionProvider is always present as a hard fallback
    so we never crash on a missing GPU runtime.

    Notes on coverage:
      - `onnxruntime-gpu` ships CUDA + TensorRT EP.
      - `onnxruntime-directml` ships the DirectML EP (Windows-friendly).
      - The base `onnxruntime` is CPU-only.
    Detection is one call to `get_available_providers()` (~10 ms once
    onnxruntime is imported), so this is safe to run on every CLI start.
    """
    try:
        import onnxruntime as ort  # noqa: F401
    except ImportError as e:
        raise ModelLoadError(
            "onnxruntime is not installed; install pick-face[gpu] or pick-face[gpu-cuda12]"
        ) from e

    try:
        available = set(ort.get_available_providers())
    except Exception:
        available = set()

    chain: list[str] = []
    if "CUDAExecutionProvider" in available:
        chain.append("CUDAExecutionProvider")
    if "TensorrtExecutionProvider" in available:
        chain.append("TensorrtExecutionProvider")
    if "DmlExecutionProvider" in available:
        chain.append("DmlExecutionProvider")
    # CPU is always the trailing fallback.
    if "CPUExecutionProvider" not in chain:
        chain.append("CPUExecutionProvider")
    return chain


def describe_provider_chain(providers: list[str]) -> str:
    """Render a provider chain as a short human-readable summary (T-201).

    Used by the CLI startup banner and report header so the user knows
    which accelerators were attempted / fell back.
    """
    if not providers:
        return "(no providers)"
    primary = providers[0]
    fallbacks = providers[1:]
    base = {
        "CUDAExecutionProvider": "CUDA",
        "TensorrtExecutionProvider": "TensorRT",
        "DmlExecutionProvider": "DirectML",
        "CPUExecutionProvider": "CPU",
    }
    head = base.get(primary, primary)
    if fallbacks:
        tail = " → ".join(base.get(p, p) for p in fallbacks)
        return f"{head} (fallback: {tail})"
    return head


def check_commercial(cfg: PickFaceConfig) -> None:
    """AC-9 guard: raise CommercialLicenseError if user is non-compliant.

    Delegates to the pack's ``LicenseClass`` via
    ``pick_face.platform.pack.require_compliance``. Kept as a top-level
    helper so existing CLI callers (init-models, etc.) don't have to
    rewrite their preflight.
    """
    from pick_face.platform.pack import discover_packs, require_compliance

    pack_id = cfg.runtime.effective_pack_id()
    packs = discover_packs()
    if pack_id in packs:
        require_compliance(packs[pack_id], cfg)
        return
    # No plugin registered → fall back to legacy model_name gating so
    # v1.x configs without `pick-face-modelpack-insightface` installed
    # still trip AC-9 instead of silently failing.
    if cfg.is_commercial_unsafe():
        raise CommercialLicenseError(
            f"Model {pack_id!r} is non-commercial-research licensed and "
            f"`accept_noncommercial_model_license` is false. See "
            f"docs/11-commercial-compliance.md for the four legal paths."
        )


# ---------------------------------------------------------------------------
# Pack runner — route B canonical entry point
# ---------------------------------------------------------------------------


class PackRunner:
    """Bundles detect → embed for any ModelPack plugin.

    A single ``runner.run(bgr)`` returns one tuple per detected face:
    ``(Detection, embedding_or_None)``. The Aligner is owned internally
    so the cluster stage never sees a non-aligned chip.
    """

    def __init__(
        self,
        *,
        pack,
        detector,
        embedder,
        aligner,
        det_thresh: float,
        providers: Sequence[str],
    ) -> None:
        self._pack = pack
        self._detector = detector
        self._embedder = embedder
        self._aligner = aligner
        self.name = pack.descriptor.pack_id
        self.det_thresh = det_thresh
        self.providers = list(providers)

    @property
    def pack(self):
        return self._pack

    @property
    def detector(self):
        return self._detector

    @property
    def embedder(self):
        return self._embedder

    @property
    def aligner(self):
        return self._aligner

    @property
    def model_version(self) -> str:
        # Detector + embedder both carry their filename; pick-face has
        # historically written `buffalo_l@<mtime>` into face.model_version
        # so older reports stay readable.
        try:
            return f"{self._pack.descriptor.pack_id}@{self._detector.model_version}"
        except Exception:
            return self._pack.descriptor.pack_id

    def warmup(self) -> None:
        """Best-effort warmup so the first real image doesn't pay cold-start."""
        import numpy as np

        blank = np.zeros((640, 640, 3), dtype=np.uint8)
        try:
            self._detector.warmup((640, 640))
            self.run(blank)
        except Exception:
            # Warmup failures are non-fatal — the first real image will retry.
            pass

    def detect(self, bgr):
        """Return list of (Detection, embedding_or_None) — see docstring."""
        import numpy as np

        out: list[tuple] = []
        for det in self._detector.detect(bgr):
            if det.det_score < self.det_thresh:
                continue
            emb = self._embedder.embed(det.chip)
            emb = np.asarray(emb, dtype=np.float32) if emb is not None else None
            out.append((det, emb))
        return out


def load_pack_runner(cfg: PickFaceConfig) -> PackRunner:
    """Build a runner from the ModelPack plugin named in ``cfg.runtime.pack``.

    Resolution:
      1. ``discover_packs()[pack_id]`` — entry-point registration.
      2. AC-9 preflight (LicenseClass-driven).
      3. ``pack.build_detector`` / ``build_embedder`` / ``build_aligner``.

    Raises:
        KeyError: pack id not installed (CLI catches → exit 2).
        CommercialLicenseError: NC-research pack without ack.
        ModelLoadError: pack built OK but onnxruntime/cv2 missing.
        ModelNotFoundError: weights missing under ``model_dir/<pack_id>/``.
    """

    from pick_face.platform.pack import discover_packs, require_compliance

    pack_id = cfg.runtime.effective_pack_id()
    packs = discover_packs()
    if pack_id not in packs:
        installed = ", ".join(sorted(packs)) or "(none)"
        raise ModelNotFoundError(
            f"model pack {pack_id!r} is not installed. Installed packs: "
            f"{installed}. For NC-research packs run "
            f"`uv pip install pick-face-modelpack-insightface`; for "
            f"self-trained packs see docs/14-model-pack-plugins.md §3."
        )
    pack = packs[pack_id]
    require_compliance(pack, cfg)

    try:
        # onnxruntime is required by every shipped pack (yuNet-mfn + InsightFace).
        import onnxruntime  # noqa: F401
    except ImportError as e:
        raise ModelLoadError(
            "onnxruntime is not installed; install pick-face[gpu] or "
            "pick-face[gpu-cuda12] for InsightFace / CUDA, or just "
            "`uv pip install onnxruntime` for the default yunet-mfn pack."
        ) from e

    model_dir = cfg.runtime.model_dir
    det_size = (cfg.detection.det_size, cfg.detection.det_size)
    providers = resolve_providers(cfg.runtime.provider)
    detector = pack.build_detector(model_dir, det_size=det_size)
    embedder = pack.build_embedder(model_dir, providers=providers)
    aligner = pack.build_aligner()
    return PackRunner(
        pack=pack,
        detector=detector,
        embedder=embedder,
        aligner=aligner,
        det_thresh=cfg.detection.det_thresh,
        providers=providers,
    )


# ---------------------------------------------------------------------------
# Legacy InsightFace runner (route A, opt-in via pick-face-modelpack-insightface)
# ---------------------------------------------------------------------------
#
# Kept as a narrow implementation that backs the `buffalo_l` /
# `buffalo_sc` / `antelopev2` opt-in packs. The default yunet-mfn pack
# does NOT use this class — it goes through load_pack_runner() above.
# Tests still import this symbol for backward-compat coverage.


def load_insightface_runner(cfg: PickFaceConfig) -> _InsightFaceRunner:
    """Build an InsightFace-backed detector+embedder (route A, opt-in).

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
            "Install with: uv pip install 'pick-face[gpu]'"
            if "insightface" in str(e)
            else "onnxruntime not installed; install pick-face[gpu]"
        ) from e

    from insightface.app import FaceAnalysis

    providers = resolve_providers(cfg.runtime.provider)
    model_dir = str(cfg.runtime.model_dir)
    model_root = (
        model_dir.rsplit("/", 1)[0]
        if model_dir.endswith(cfg.runtime.model_name or "")
        else model_dir
    )

    # The pack files live in <model_root>/<model_name>/. If absent, we raise
    # ModelNotFoundError with a clear next step (init-models --allow-network).
    pack_dir = Path(model_root) / (cfg.runtime.model_name or "buffalo_l")
    if not pack_dir.exists():
        raise ModelNotFoundError(
            f"model pack not found at {pack_dir}. Run "
            "`pick-face init-models --allow-network` to download, or set "
            "[runtime] model_dir to a directory that already contains it."
        )

    try:
        app = FaceAnalysis(
            name=cfg.runtime.model_name or "buffalo_l",
            root=model_root,
            providers=providers,
            allowed_modules=None,
        )
        app.prepare(ctx_id=0, det_size=(cfg.detection.det_size, cfg.detection.det_size))
    except Exception as e:
        raise ModelLoadError(f"insightface.prepare failed: {e}") from e

    return _InsightFaceRunner(
        app=app,
        model_name=cfg.runtime.model_name or "buffalo_l",
        det_thresh=cfg.detection.det_thresh,
        det_size=(cfg.detection.det_size, cfg.detection.det_size),
        providers=providers,
    )


class _InsightFaceRunner:
    """Bundles detect → align → embed in one wrapper (route A legacy).

    Single `.run(bgr)` returns one Detection per face, already with the
    aligned 112x112 chip populated and the embedding NOT included
    (InsightFace returns the embedding too; we keep it for the cluster
    stage rather than the Detection).
    """

    def __init__(
        self,
        app,
        model_name: str,
        det_thresh: float,
        det_size: tuple[int, int],
        providers: Sequence[str],
    ) -> None:
        self._app = app
        self.name = model_name
        self.model_version = (
            f"{model_name}@{getattr(app, 'model_dir', '').rsplit('/', 1)[-1] or 'unknown'}"
        )
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

        from pick_face.ingest.align import warp_to_112
        from pick_face.ingest.detector import detection_from_insightface

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
