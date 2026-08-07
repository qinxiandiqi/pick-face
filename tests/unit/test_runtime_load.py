"""Tests for pick_face.runtime AC-9 path (without InsightFace loaded).

The check_commercial / ModelNotFoundError branches are exercised here so a
regression in those flows can't slip into CI unnoticed. The expensive branch
(`load_insightface_runner` actually building `FaceAnalysis`) is verified in
the integration suite, not here.

Route B (v2.0+): the default pack is the bundled yunet-sface
(PERMISSIVE — no AC-9 gate). To exercise the AC-9 branches in this
file we explicitly set `pack = "buffalo_l"` (which is NC-research and
requires `accept_noncommercial_model_license = true`).

insightface is now an opt-in dep (route B), so these tests skip cleanly
when the package isn't installed — they cover the legacy
``load_insightface_runner`` shim that backs the
``pick-face-modelpack-insightface`` plugin.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pick_face.core.config import PickFaceConfig
from pick_face.core.errors import CommercialLicenseError, ModelLoadError, ModelNotFoundError
from pick_face.platform.runtime import load_insightface_runner

# Skip the whole module if insightface.app isn't installed (route B default).
# insightface is an opt-in dep; some installs may have a stub top-level
# package but be missing the `app` submodule — we check the submodule.
pytest.importorskip("insightface.app")


def _nc_cfg(**runtime_overrides) -> PickFaceConfig:
    """Build a config targeting the NC-research buffalo_l pack (AC-9 path)."""
    rt = {"pack": "buffalo_l", **runtime_overrides}
    return PickFaceConfig(runtime=rt)


def test_load_runner_fails_compliance_first(tmp_pure: Path) -> None:
    """AC-9 must be checked BEFORE we try to instantiate FaceAnalysis.

    A user with the default config (`accept=false`) and a non-existent
    model_dir must see the CommercialLicenseError, not a confusing
    ModelNotFoundError from onnxruntime.
    """
    cfg = _nc_cfg()
    cfg.runtime.model_dir = tmp_pure / "nope"  # doesn't exist
    with pytest.raises(CommercialLicenseError):
        load_insightface_runner(cfg)


def test_load_runner_fails_model_not_found_when_compliant(tmp_pure: Path) -> None:
    """A user acknowledging the license but pointing at a missing pack must
    see a clear ModelNotFoundError with a hint to run init-models."""
    cfg = _nc_cfg(accept_noncommercial_model_license=True)
    cfg.runtime.model_dir = tmp_pure / "nope"
    with pytest.raises(ModelNotFoundError, match="init-models"):
        load_insightface_runner(cfg)


def test_load_runner_fails_when_insightface_missing(tmp_pure: Path, monkeypatch) -> None:
    """If insightface isn't installed, we must raise ModelLoadError — even
    if compliance passes and the pack directory exists."""
    cfg = _nc_cfg(accept_noncommercial_model_license=True)
    # Make the pack directory exist so we get past the path check.
    pack_dir = tmp_pure / "buffalo_l"
    pack_dir.mkdir(parents=True, exist_ok=True)
    cfg.runtime.model_dir = tmp_pure  # insightface searches <root>/<model_name>

    # Simulate the import failing
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in ("insightface", "insightface.app"):
            raise ImportError(f"no module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ModelLoadError):
        load_insightface_runner(cfg)
