"""Tests for pick_face.runtime that don't require InsightFace installed.

Route B (v2.0+): the default pack is ``yunet-mfn`` (PERMISSIVE), so the
default config is no longer blocked. NC packs like ``buffalo_l`` must
be opted in explicitly. The tests below cover both shapes.
"""

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


def test_check_commercial_passes_for_default_config() -> None:
    """The v2.0+ default yunet-mfn pack is Apache-2.0 → AC-9 passes."""
    cfg = PickFaceConfig()
    check_commercial(cfg)  # must not raise


def test_check_commercial_blocks_nc_pack_without_ack() -> None:
    cfg = PickFaceConfig(runtime={"pack": "buffalo_l"})
    with pytest.raises(CommercialLicenseError):
        check_commercial(cfg)


def test_check_commercial_blocks_other_nc_packs() -> None:
    """Legacy NC pack ids still trip AC-9 when used via legacy ``model_name``."""
    for name in ("buffalo_sc", "antelopev2", "buffalo_m"):
        cfg = PickFaceConfig(runtime={"model_name": name})
        with pytest.raises(CommercialLicenseError):
            check_commercial(cfg)


def test_check_commercial_passes_when_acknowledged() -> None:
    cfg = PickFaceConfig(runtime={"pack": "buffalo_l", "accept_noncommercial_model_license": True})
    check_commercial(cfg)  # must not raise


def test_check_commercial_passes_for_alternative_model() -> None:
    cfg = PickFaceConfig(runtime={"pack": "arcface-webface4m"})
    check_commercial(cfg)  # must not raise
