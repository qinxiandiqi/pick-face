"""M5 / T-508 — Route B structural guards.

These tests assert invariants that protect the route-B default pack
contract (docs/14 §2 / docs/13 §3):

* The default model pack is shipped by pick-face core (yunet-sface) and
  is Apache-2.0 — Pi 3B friendly out of the box.
* The `insightface` package is NOT in pick-face core's default deps
  (it stays opt-in via `[insightface]` extras or the
  `pick-face-modelpack-insightface` plugin). Catches accidental
  re-additions that would force the InsightFace NC-research license
  onto every user.
* The yunet-sface pack is registered as a `pick_face.model_packs`
  entry-point so `discover_packs()` finds it on a fresh install.

History: the default pack was originally `yunet-mfn` (YuNet +
MobileFaceNet INT8). After upstream `opencv/opencv_zoo` removed the
MobileFaceNet INT8 weights in 2025, the default is `yunet-sface`
(YuNet + SFace INT8). The deprecated `yunet-mfn` id is still
registered as an alias — `test_yunet_mfn_alias_still_registered`
guards that v1.x configs keep working.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import tomllib

REPO = Path(__file__).resolve().parent.parent.parent


def test_default_pack_is_yunet_sface() -> None:
    """Route B: the default pack id must be ``yunet-sface`` (Apache-2.0)."""
    from pick_face.core.config import DEFAULT_PACK_ID, PickFaceConfig

    assert DEFAULT_PACK_ID == "yunet-sface"
    cfg = PickFaceConfig()
    assert cfg.runtime.pack == "yunet-sface"


def test_yunet_sface_pack_is_discoverable() -> None:
    """`yunet-sface` must show up in `discover_packs()` on a fresh install."""
    from pick_face.platform.pack import discover_packs

    packs = discover_packs()
    assert "yunet-sface" in packs, f"yunet-sface missing; got {sorted(packs)}"
    descriptor = packs["yunet-sface"].descriptor
    assert descriptor.pack_id == "yunet-sface"
    assert descriptor.license_name.startswith("Apache-2.0"), (
        f"yunet-sface must be Apache-2.0 (commercial-friendly), got {descriptor.license_name!r}"
    )
    assert "arm-friendly" in descriptor.tags or "low-ram" in descriptor.tags, (
        "yunet-sface should advertise ARM-friendly / low-ram tags so Pi 3B "
        "users can find it via `pick-face doctor`"
    )


def test_no_insightface_in_default_deps() -> None:
    """`insightface` must NOT appear in the [project].dependencies table.

    Catches accidental re-additions. InsightFace stays opt-in via
    `[insightface]` extras or the third-party
    `pick-face-modelpack-insightface` plugin.
    """
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject["project"]["dependencies"]
    offenders = [d for d in deps if d.lower().startswith("insightface")]
    assert not offenders, (
        f"`insightface` must not be a default dep of pick-face core "
        f"(route B: keep it opt-in only); found: {offenders}"
    )


def test_yunet_sface_entry_point_registered() -> None:
    """`yunet-sface` must be registered under the `pick_face.model_packs`
    entry-point group so `discover_packs()` can find it without explicit
    imports.
    """
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    eps = pyproject["project"].get("entry-points", {}).get("pick_face.model_packs", {})
    assert "yunet-sface" in eps, (
        f"`yunet-sface` must be registered under [project.entry-points."
        f'"pick_face.model_packs"]; got: {sorted(eps)}'
    )


def test_yunet_mfn_alias_still_registered() -> None:
    """Deprecated `yunet-mfn` must remain a registered entry-point so
    v1.x configs that still reference the old id don't silently fail
    at startup — the alias raises a clear "use yunet-sface" message.
    """
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    eps = pyproject["project"].get("entry-points", {}).get("pick_face.model_packs", {})
    assert "yunet-mfn" in eps, (
        f"`yunet-mfn` deprecated alias must remain registered for back-compat; got: {sorted(eps)}"
    )


def test_onnxruntime_is_default_dep() -> None:
    """The bundled yunet-sface pack needs onnxruntime at runtime.

    This is fine to be a default dep — onnxruntime is MIT and the
    Pi 3B / ARM wheel is small enough (~25 MB). The contrast with
    `insightface` is that we don't pull any NC-research weights by
    default.
    """
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject["project"]["dependencies"]
    assert any(d.lower().startswith("onnxruntime") for d in deps), (
        "onnxruntime must remain a default dep so the yunet-sface pack "
        "loads without an extra `uv pip install` step."
    )


@pytest.mark.parametrize(
    "pack_id,expected_class",
    [
        ("yunet-sface", "permissive"),
    ],
)
def test_default_pack_license_class(pack_id: str, expected_class: str) -> None:
    """Spot-check the LicenseClass advertised by the default pack."""
    from pick_face.platform.pack import discover_packs

    pack = discover_packs()[pack_id]
    assert pack.descriptor.license_class.value == expected_class
