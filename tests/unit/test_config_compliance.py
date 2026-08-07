"""Tests for pick_face.core.config.commercial_unsafe logic (AC-9, docs/11 §3.2).

Route B (v2.0+): the default pack is ``yunet-sface`` (PERMISSIVE), so the
default config is no longer commercially unsafe. To exercise the NC
branches we explicitly set ``pack = "buffalo_l"``.
"""

from __future__ import annotations


def test_default_config_is_commercially_safe() -> None:
    """The v2.0+ default pack is ``yunet-sface`` (Apache-2.0) — commercial-safe out of the box."""
    from pick_face.core.config import PickFaceConfig

    cfg = PickFaceConfig()
    assert cfg.is_commercial_unsafe() is False
    assert cfg.runtime.pack == "yunet-sface"


def test_nc_pack_with_default_ack_is_unsafe() -> None:
    """Pointing at ``buffalo_l`` (NC-research) without ack trips AC-9."""
    from pick_face.core.config import PickFaceConfig

    cfg = PickFaceConfig(runtime={"pack": "buffalo_l"})
    assert cfg.is_commercial_unsafe() is True


def test_acknowledging_license_makes_config_compliant() -> None:
    from pick_face.core.config import PickFaceConfig

    cfg = PickFaceConfig(runtime={"pack": "buffalo_l", "accept_noncommercial_model_license": True})
    assert cfg.is_commercial_unsafe() is False


def test_non_insightface_model_is_always_compliant() -> None:
    """A user self-trained pack id like 'arcface-webface4m' must NOT
    trigger the preflight regardless of the flag."""
    from pick_face.core.config import PickFaceConfig

    cfg = PickFaceConfig(runtime={"pack": "arcface-webface4m"})
    assert cfg.is_commercial_unsafe() is False


def test_explicit_acknowledgment_with_alternative_model() -> None:
    from pick_face.core.config import PickFaceConfig

    cfg = PickFaceConfig(
        runtime={
            "pack": "arcface-webface4m",
            "accept_noncommercial_model_license": False,
        }
    )
    # Even though the user has NOT acknowledged, they're using a non-NC
    # pack — so it's still commercially safe.
    assert cfg.is_commercial_unsafe() is False


def test_legacy_model_name_still_gates_nc_packs() -> None:
    """A v1.x config with `model_name = "buffalo_l"` must still trip AC-9
    when no `pick-face-modelpack-insightface` plugin is installed.
    """
    from pick_face.core.config import PickFaceConfig

    cfg = PickFaceConfig(runtime={"model_name": "buffalo_l"})
    assert cfg.is_commercial_unsafe() is True
