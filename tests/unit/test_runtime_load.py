"""Tests for pick_face.runtime AC-9 path (without InsightFace loaded).

The check_commercial / ModelNotFoundError branches are exercised here so a
regression in those flows can't slip into CI unnoticed. The expensive branch
(`load_insightface_runner` actually building `FaceAnalysis`) is verified in
the integration suite, not here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pick_face.config import PickFaceConfig
from pick_face.errors import CommercialLicenseError, ModelLoadError, ModelNotFoundError
from pick_face.runtime import check_commercial, load_insightface_runner


def test_load_runner_fails_compliance_first(tmp_pure: Path) -> None:
    """AC-9 must be checked BEFORE we try to instantiate FaceAnalysis.

    A user with the default config (`accept=false`) and a non-existent
    model_dir must see the CommercialLicenseError, not a confusing
    ModelNotFoundError from onnxruntime.
    """
    cfg = PickFaceConfig()
    cfg.runtime.model_dir = tmp_pure / "nope"  # doesn't exist
    with pytest.raises(CommercialLicenseError):
        load_insightface_runner(cfg)


def test_load_runner_fails_model_not_found_when_compliant(tmp_pure: Path) -> None:
    """A user acknowledging the license but pointing at a missing pack must
    see a clear ModelNotFoundError with a hint to run init-models."""
    cfg = PickFaceConfig(runtime={"accept_noncommercial_model_license": True})
    cfg.runtime.model_dir = tmp_pure / "nope"
    with pytest.raises(ModelNotFoundError, match="init-models"):
        load_insightface_runner(cfg)


def test_load_runner_fails_when_insightface_missing(tmp_pure: Path, monkeypatch) -> None:
    """If insightface isn't installed, we must raise ModelLoadError — even
    if compliance passes and the pack directory exists."""
    cfg = PickFaceConfig(runtime={"accept_noncommercial_model_license": True})
    # Make the pack directory exist so we get past the path check.
    pack_dir = tmp_pure / cfg.runtime.model_name
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
