"""Tests for pick_face.config.commercial_unsafe logic (AC-9, docs/11 §3.2)."""

from __future__ import annotations


def test_default_config_is_commercially_unsafe() -> None:
    """The default that `pick-face init` writes must *fail* the AC-9 preflight
    with model_name='buffalo_l' (it IS an InsightFace pack)."""
    from pick_face.config import INSIGHTFACE_MODELS, PickFaceConfig

    cfg = PickFaceConfig()
    assert cfg.is_commercial_unsafe() is True
    assert "buffalo_l" in INSIGHTFACE_MODELS


def test_acknowledging_license_makes_config_compliant() -> None:
    from pick_face.config import PickFaceConfig

    cfg = PickFaceConfig(runtime={"accept_noncommercial_model_license": True})
    assert cfg.is_commercial_unsafe() is False


def test_non_insightface_model_is_always_compliant() -> None:
    """A user self-trained model name like 'arcface_webface4m' must NOT
    trigger the preflight regardless of the flag."""
    from pick_face.config import PickFaceConfig

    cfg = PickFaceConfig(runtime={"model_name": "arcface_webface4m"})
    assert cfg.is_commercial_unsafe() is False


def test_explicit_acknowledgment_with_alternative_model() -> None:
    from pick_face.config import PickFaceConfig

    cfg = PickFaceConfig(runtime={
        "model_name": "arcface_webface4m",
        "accept_noncommercial_model_license": False,
    })
    # Even though the user has NOT acknowledged, they're using a non-InsightFace
    # model — so it's still commercially safe.
    assert cfg.is_commercial_unsafe() is False
