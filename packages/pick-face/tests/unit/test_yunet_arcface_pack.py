"""M5 / T-509 — Structural guards for the yunet-arcface high-precision tier.

These tests are the network-free / weights-free counterpart to the
real-face integration suite (`tests/integration/test_real_faces_ac1.py`).
We assert:

  * `yunet-arcface` shows up in `discover_packs()` with the right
    LicenseClass and SPDX tags.
  * The descriptor carries per-component license fields
    (`detector_license_spdx`, `embedder_license_spdx`) and an
    `embedder_alternates` list with both FP32 + INT8.
  * `expected_files(variant=…)` is variant-aware (B-3 fix): asking for
    `int8` doesn't include the FP32 filename, asking for `fp32` doesn't
    include INT8.
  * `ArcFaceR100Embedder.preprocess()` flips the channel axis
    correctly — a regression here produces silently-degraded embeddings.
  * `resolve_quant()` honours the `.quant` marker file over the env var
    over the default.
  * `require_compliance()` does not raise for the PERMISSIVE pack (AC-9).

No real weights are needed. Where a test would normally build an ONNX
session we stub with `unittest.mock`.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Discovery + descriptor
# ---------------------------------------------------------------------------


def test_yunet_arcface_is_discoverable() -> None:
    from pick_face.platform.pack import discover_packs

    packs = discover_packs()
    assert "yunet-arcface" in packs, f"yunet-arcface missing; got {sorted(packs)}"
    descriptor = packs["yunet-arcface"].descriptor
    assert descriptor.pack_id == "yunet-arcface"
    assert descriptor.license_class.value == "permissive"
    assert descriptor.license_spdx == "Apache-2.0"
    assert descriptor.detector_license_spdx == "MIT"
    assert descriptor.embedder_license_spdx == "Apache-2.0"


def test_yunet_arcface_carries_alternates() -> None:
    """B-2 fix: the descriptor must carry both FP32 + INT8 variants."""
    from pick_face.platform.pack import discover_packs

    descriptor = discover_packs()["yunet-arcface"].descriptor
    assert descriptor.embedder_alternates is not None
    quants = {v.quant for v in descriptor.embedder_alternates}
    assert quants == {"fp32", "int8"}, f"expected fp32+int8; got {quants}"
    # Default-variant fields agree with the FP32 alternate.
    fp32 = next(v for v in descriptor.embedder_alternates if v.quant == "fp32")
    assert descriptor.embedder_sha256 == fp32.sha256
    assert descriptor.embedder_size_bytes == fp32.size_bytes
    assert descriptor.embedder_url == fp32.url


def test_yunet_arcface_high_precision_tag() -> None:
    from pick_face.platform.pack import discover_packs

    descriptor = discover_packs()["yunet-arcface"].descriptor
    assert "high-precision" in descriptor.tags, (
        "yunet-arcface must self-tag as 'high-precision' so `doctor` "
        "users can find it as the non-default tier"
    )


def test_yunet_arcface_passes_ac9_without_ack() -> None:
    """PERMISSIVE pack must skip the AC-9 gate — no ack required."""
    from pick_face.core.config import PickFaceConfig
    from pick_face.platform.pack import discover_packs, require_compliance

    pack = discover_packs()["yunet-arcface"]
    # Default config: accept_noncommercial_model_license = false (fail-safe).
    cfg = PickFaceConfig()
    require_compliance(pack, cfg)  # must not raise


# ---------------------------------------------------------------------------
# Variant-aware expected_files (B-3 fix)
# ---------------------------------------------------------------------------


def test_expected_files_default_returns_fp32() -> None:
    from pick_face.platform.packs.yunet_arcface import YuNetArcFacePack

    pack = YuNetArcFacePack()
    files = pack.expected_files()  # no marker + no variant arg → default
    assert files == [
        "yunet_2023mar.onnx",
        "arcface_r100_fp32.onnx",
    ]


def test_expected_files_int8_excludes_fp32() -> None:
    from pick_face.platform.packs.yunet_arcface import YuNetArcFacePack

    pack = YuNetArcFacePack()
    files = pack.expected_files(variant="int8")
    assert files == [
        "yunet_2023mar.onnx",
        "arcface_r100_int8.onnx",
    ]


def test_expected_files_unknown_variant_raises() -> None:
    from pick_face.platform.packs.yunet_arcface import YuNetArcFacePack

    pack = YuNetArcFacePack()
    with pytest.raises(ValueError, match="unknown variant"):
        pack.expected_files(variant="fp16")


# ---------------------------------------------------------------------------
# Variant resolution (I-2: marker file over env var over default)
# ---------------------------------------------------------------------------


def test_resolve_quant_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PICK_FACE_ARCFACE_QUANT", raising=False)
    # No marker → default.
    from pick_face.platform.packs.yunet_arcface import resolve_quant

    assert resolve_quant(tmp_path) == "fp32"


def test_resolve_quant_marker_wins_over_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PICK_FACE_ARCFACE_QUANT", "fp32")
    (tmp_path / ".quant").write_text("int8", encoding="utf-8")
    from pick_face.platform.packs.yunet_arcface import resolve_quant

    assert resolve_quant(tmp_path) == "int8"


def test_resolve_quant_env_when_no_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PICK_FACE_ARCFACE_QUANT", "int8")
    from pick_face.platform.packs.yunet_arcface import resolve_quant

    assert resolve_quant(tmp_path) == "int8"


def test_resolve_quant_unknown_marker_falls_back(tmp_path: Path) -> None:
    (tmp_path / ".quant").write_text("fp16", encoding="utf-8")
    from pick_face.platform.packs.yunet_arcface import resolve_quant

    with pytest.warns(UserWarning, match="unknown quant"):
        assert resolve_quant(tmp_path) == "fp32"


def test_resolve_quant_unknown_env_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PICK_FACE_ARCFACE_QUANT", "fp16")
    from pick_face.platform.packs.yunet_arcface import resolve_quant

    assert resolve_quant(tmp_path) == "fp32"


# ---------------------------------------------------------------------------
# Preprocessing correctness (I-3)
# ---------------------------------------------------------------------------


def test_preprocess_channel_order_is_bgr() -> None:
    """A regression in `chip_rgb[..., ::-1]` would silently degrade
    embeddings. Construct a 1-hot RGB fixture and assert the BGR swap.
    """
    from pick_face.platform.packs.yunet_arcface import ArcFaceR100Embedder

    # Pure red RGB → pure blue BGR after the flip.
    red_rgb = np.zeros((112, 112, 3), dtype=np.uint8)
    red_rgb[..., 0] = 255  # R=255, G=0, B=0
    x = ArcFaceR100Embedder.preprocess(red_rgb)
    # After BGR flip: first channel should hold "red-as-BGR" = 0 (because
    # the original B was 0). Second channel: original G = 0. Third
    # channel: original R = 255.
    # BGR normalisation: (x - 127.5) / 128. So channel 0 (BGR-B) ≈ -0.996,
    # channel 1 (BGR-G) ≈ -0.996, channel 2 (BGR-R) ≈ +0.996.
    assert x.shape == (1, 3, 112, 112), f"unexpected shape {x.shape}"
    # BGR-B (red-as-BGR B-channel) — was 0
    assert x[0, 0, 0, 0] == pytest.approx((0 - 127.5) / 128.0, abs=1e-4)
    # BGR-G (red-as-BGR G-channel) — was 0
    assert x[0, 1, 0, 0] == pytest.approx((0 - 127.5) / 128.0, abs=1e-4)
    # BGR-R (red-as-BGR R-channel) — was 255
    assert x[0, 2, 0, 0] == pytest.approx((255 - 127.5) / 128.0, abs=1e-4)


def test_preprocess_blue_becomes_red_after_flip() -> None:
    """Pure blue RGB (R=0, G=0, B=255) — after flip the third (R-as-BGR)
    channel should carry 255 (= +0.996)."""
    from pick_face.platform.packs.yunet_arcface import ArcFaceR100Embedder

    blue_rgb = np.zeros((112, 112, 3), dtype=np.uint8)
    blue_rgb[..., 2] = 255  # R=0, G=0, B=255
    x = ArcFaceR100Embedder.preprocess(blue_rgb)
    # After BGR swap: BGR-order is (B, G, R) = (255, 0, 0).
    # Third channel (R-as-BGR) = 0; first (B-as-BGR) = 255.
    assert x[0, 0, 0, 0] == pytest.approx((255 - 127.5) / 128.0, abs=1e-4)
    assert x[0, 2, 0, 0] == pytest.approx((0 - 127.5) / 128.0, abs=1e-4)


def test_preprocess_output_dtype_is_float32() -> None:
    from pick_face.platform.packs.yunet_arcface import ArcFaceR100Embedder

    chip = np.full((112, 112, 3), 128, dtype=np.uint8)
    x = ArcFaceR100Embedder.preprocess(chip)
    assert x.dtype == np.float32


# ---------------------------------------------------------------------------
# download_to: only writes the requested variant (not both) + marker
# ---------------------------------------------------------------------------


def test_download_to_fp32_only_writes_fp32(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B-1 fix: `--quant fp32` must not also download INT8 (save 66 MiB)."""
    from pick_face.platform.packs.yunet_arcface import YuNetArcFacePack

    pack = YuNetArcFacePack()
    target = tmp_path / "yunet-arcface"

    def fake_fetch(url: str, dst: Path, *, progress=None) -> None:
        # Don't actually hit the network — just create a stub file of the
        # expected size so SHA verification passes.
        size = (
            232_589
            if "yunet" in url
            else 261_036_388
            if "fp32" in url
            else 65_764_892
        )
        dst.write_bytes(b"\x00" * size)

    def fake_verify(dst: Path, expected: str, *, label: str) -> None:
        # Stub — real bytes won't match the SHA.
        return None

    with patch(
        "pick_face.platform.packs.yunet_sface._fetch_with_progress",
        side_effect=fake_fetch,
    ):
        with patch(
            "pick_face.platform.packs.yunet_sface._verify_sha256",
            side_effect=fake_verify,
        ):
            out = pack.download_to(target, quant="fp32")

    # Detector + FP32 embedder only.
    assert sorted(p.name for p in out) == [
        "arcface_r100_fp32.onnx",
        "yunet_2023mar.onnx",
    ]
    assert "arcface_r100_int8.onnx" not in [p.name for p in out]
    # Marker records the choice.
    assert (target / ".quant").read_text(encoding="utf-8").strip() == "fp32"


def test_download_to_int8_only_writes_int8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pick_face.platform.packs.yunet_arcface import YuNetArcFacePack

    pack = YuNetArcFacePack()
    target = tmp_path / "yunet-arcface"

    def fake_fetch(url: str, dst: Path, *, progress=None) -> None:
        size = (
            232_589
            if "yunet" in url
            else 65_764_892
        )
        dst.write_bytes(b"\x00" * size)

    def fake_verify(dst: Path, expected: str, *, label: str) -> None:
        return None

    with patch(
        "pick_face.platform.packs.yunet_sface._fetch_with_progress",
        side_effect=fake_fetch,
    ):
        with patch(
            "pick_face.platform.packs.yunet_sface._verify_sha256",
            side_effect=fake_verify,
        ):
            out = pack.download_to(target, quant="int8")

    assert sorted(p.name for p in out) == [
        "arcface_r100_int8.onnx",
        "yunet_2023mar.onnx",
    ]
    assert "arcface_r100_fp32.onnx" not in [p.name for p in out]
    assert (target / ".quant").read_text(encoding="utf-8").strip() == "int8"


def test_download_to_unknown_quant_raises(tmp_path: Path) -> None:
    from pick_face.platform.packs.yunet_arcface import YuNetArcFacePack

    pack = YuNetArcFacePack()
    with pytest.raises(ValueError, match="unknown quant"):
        pack.download_to(tmp_path / "yunet-arcface", quant="fp16")


# ---------------------------------------------------------------------------
# build_embedder: routes through resolve_quant (I-2)
# ---------------------------------------------------------------------------


def test_build_embedder_default_quant_is_fp32(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No marker → FP32 (the descriptor's default)."""
    from pick_face.platform.packs.yunet_arcface import YuNetArcFacePack

    pack = YuNetArcFacePack()
    pack_dir = tmp_path / "yunet-arcface"
    pack_dir.mkdir()
    # Pre-populate FP32 file with the right size so ModelNotFoundError
    # doesn't fire.
    (pack_dir / "yunet_2023mar.onnx").write_bytes(b"\x00" * 232_589)
    (pack_dir / "arcface_r100_fp32.onnx").write_bytes(b"\x00" * 261_036_388)

    # Stub out the actual SHA check (real bytes won't match the SHA).
    with patch(
        "pick_face.platform.packs.yunet_sface._verify_sha256", lambda *a, **k: None
    ):
        # Stub ort.InferenceSession so we don't need the real onnxruntime
        # session to actually load anything.
        with patch("onnxruntime.InferenceSession") as mock_sess:
            mock_sess.return_value.get_inputs.return_value = [
                type("I", (), {"name": "input"})()
            ]
            embedder = pack.build_embedder(tmp_path)

    # ArcFaceR100Embedder exposes its weight file via model_version.
    assert embedder.model_version == "arcface_r100_fp32.onnx"
    assert embedder.dim == 512


def test_build_embedder_marker_selects_int8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pick_face.platform.packs.yunet_arcface import YuNetArcFacePack

    pack = YuNetArcFacePack()
    pack_dir = tmp_path / "yunet-arcface"
    pack_dir.mkdir()
    (pack_dir / "yunet_2023mar.onnx").write_bytes(b"\x00" * 232_589)
    (pack_dir / "arcface_r100_int8.onnx").write_bytes(b"\x00" * 65_764_892)
    (pack_dir / ".quant").write_text("int8", encoding="utf-8")

    with patch(
        "pick_face.platform.packs.yunet_sface._verify_sha256", lambda *a, **k: None
    ):
        with patch("onnxruntime.InferenceSession") as mock_sess:
            mock_sess.return_value.get_inputs.return_value = [
                type("I", (), {"name": "input"})()
            ]
            embedder = pack.build_embedder(tmp_path)

    assert embedder.model_version == "arcface_r100_int8.onnx"


# ---------------------------------------------------------------------------
# Providers threading (I-7)
# ---------------------------------------------------------------------------


def test_build_embedder_threads_providers_to_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pick_face.platform.packs.yunet_arcface import YuNetArcFacePack

    pack_dir = tmp_path / "yunet-arcface"
    pack_dir.mkdir()
    (pack_dir / "yunet_2023mar.onnx").write_bytes(b"\x00" * 232_589)
    (pack_dir / "arcface_r100_fp32.onnx").write_bytes(b"\x00" * 261_036_388)

    with patch(
        "pick_face.platform.packs.yunet_sface._verify_sha256", lambda *a, **k: None
    ):
        with patch("onnxruntime.InferenceSession") as mock_sess:
            mock_sess.return_value.get_inputs.return_value = [
                type("I", (), {"name": "input"})()
            ]
            pack = YuNetArcFacePack()
            pack.build_embedder(
                tmp_path, providers=["CUDAExecutionProvider", "CPUExecutionProvider"]
            )

    # The mock was called with providers=... — assert the value.
    call_kwargs = mock_sess.call_args.kwargs
    assert "providers" in call_kwargs
    assert call_kwargs["providers"] == [
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]


def test_build_embedder_no_providers_lets_ort_autodetect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pick_face.platform.packs.yunet_arcface import YuNetArcFacePack

    pack_dir = tmp_path / "yunet-arcface"
    pack_dir.mkdir()
    (pack_dir / "yunet_2023mar.onnx").write_bytes(b"\x00" * 232_589)
    (pack_dir / "arcface_r100_fp32.onnx").write_bytes(b"\x00" * 261_036_388)

    with patch(
        "pick_face.platform.packs.yunet_sface._verify_sha256", lambda *a, **k: None
    ):
        with patch("onnxruntime.InferenceSession") as mock_sess:
            mock_sess.return_value.get_inputs.return_value = [
                type("I", (), {"name": "input"})()
            ]
            pack = YuNetArcFacePack()
            pack.build_embedder(tmp_path)  # no providers → None

    call_kwargs = mock_sess.call_args.kwargs
    assert call_kwargs.get("providers") is None


# ---------------------------------------------------------------------------
# runtime.py plumbing
# ---------------------------------------------------------------------------


def test_load_pack_runner_passes_providers_to_embedder() -> None:
    """I-7: `load_pack_runner` must call `pack.build_embedder(model_dir,
    providers=...)` so GPU hosts route ArcFace to CUDA.

    Inspect the runtime source directly — it's the source of truth and
    a structural assertion is more durable than mocking the whole
    discover/compliance dance.
    """
    import re
    from pathlib import Path

    src = Path("src/pick_face/platform/runtime.py").read_text(encoding="utf-8")
    # The line that builds the embedder must include the providers= kwarg.
    assert re.search(r"pack\.build_embedder\(\s*model_dir\s*,\s*providers=providers\s*\)", src), (
        "runtime.load_pack_runner must call pack.build_embedder with "
        "providers=providers so GPU providers reach the ARCfaceR100 session"
    )


# ---------------------------------------------------------------------------
# Pack-level descriptor invariants
# ---------------------------------------------------------------------------


def test_descriptor_notes_call_out_merge_threshold_hint() -> None:
    """N-4: the descriptor's notes should mention `merge_threshold = 0.55`
    for high-precision 512-D clustering — this is the only place a user
    reading the descriptor learns the migration tip from the docstring.
    """
    from pick_face.platform.pack import discover_packs

    descriptor = discover_packs()["yunet-arcface"].descriptor
    assert "merge_threshold = 0.55" in descriptor.notes
    assert "MS-Celeb-1M" in descriptor.notes  # training-data provenance


def test_descriptor_has_no_nc_notice() -> None:
    """PERMISSIVE pack — no license notice text required."""
    from pick_face.platform.pack import discover_packs

    descriptor = discover_packs()["yunet-arcface"].descriptor
    assert descriptor.license_notice_text == ""


# ---------------------------------------------------------------------------
# yunet-sface compatibility — the three signatures must still work
# ---------------------------------------------------------------------------


def test_yunet_sface_signatures_accept_new_kwargs() -> None:
    """Backward-compat: yunet-sface's build_embedder / expected_files /
    download_to must accept the new keyword args (variant=, providers=,
    quant=) so route B's contracts stay uniform.
    """
    import inspect

    from pick_face.platform.packs.yunet_sface import YuNetSfacePack

    pack = YuNetSfacePack()
    # expected_files with variant= kwarg
    assert pack.expected_files(variant="fp32") == pack.expected_files(variant="int8")
    # build_embedder must accept providers= kwarg
    sig = inspect.signature(pack.build_embedder)
    assert "providers" in sig.parameters
    # download_to must accept quant= kwarg
    sig = inspect.signature(pack.download_to)
    assert "quant" in sig.parameters
