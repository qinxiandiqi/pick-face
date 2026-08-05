"""Tests for pick_face.runtime that don't require InsightFace installed."""

from __future__ import annotations

import pytest

from pick_face.core.config import PickFaceConfig
from pick_face.core.errors import CommercialLicenseError, ModelLoadError
from pick_face.platform.runtime import check_commercial, resolve_providers

# ---------------------------------------------------------------------------
# resolve_providers
# ---------------------------------------------------------------------------


def test_resolve_cpu_provider_explicit() -> None:
    providers = resolve_providers("cpu")
    assert providers == ["CPUExecutionProvider"]


def test_resolve_cuda_provider_with_cpu_fallback() -> None:
    providers = resolve_providers("cuda")
    assert "CPUExecutionProvider" in providers
    assert "CUDAExecutionProvider" in providers[0]


def test_resolve_directml_provider_with_cpu_fallback() -> None:
    providers = resolve_providers("directml")
    assert "DmlExecutionProvider" in providers


def test_resolve_unknown_provider_raises() -> None:
    with pytest.raises(ModelLoadError):
        resolve_providers("vpu")


# ---------------------------------------------------------------------------
# check_commercial (AC-9 preflight)
# ---------------------------------------------------------------------------


def test_check_commercial_blocks_default_config() -> None:
    cfg = PickFaceConfig()  # buffalo_l + accept=False
    with pytest.raises(CommercialLicenseError):
        check_commercial(cfg)


def test_check_commercial_blocks_other_insightface_models() -> None:
    for name in ("buffalo_sc", "antelopev2", "buffalo_m"):
        cfg = PickFaceConfig(runtime={"model_name": name})
        with pytest.raises(CommercialLicenseError):
            check_commercial(cfg)


def test_check_commercial_passes_when_acknowledged() -> None:
    cfg = PickFaceConfig(runtime={"accept_noncommercial_model_license": True})
    check_commercial(cfg)  # must not raise


def test_check_commercial_passes_for_alternative_model() -> None:
    cfg = PickFaceConfig(runtime={"model_name": "arcface_webface4m"})
    check_commercial(cfg)  # must not raise
