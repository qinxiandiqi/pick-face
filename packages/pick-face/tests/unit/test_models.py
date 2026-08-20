"""Tests for pick_face.platform.models.

We do NOT touch the network here — the License Notice text + .license_ack
JSON are the auditable surface (docs/11 §3.3 / §3.4). The actual weight
download is delegated to `insightface.model_zoo` and is exercised
separately in smoke.
"""

from __future__ import annotations

import json
from pathlib import Path

from pick_face.core.config import PickFaceConfig
from pick_face.platform.models import (
    is_insightface_model,
    license_ack_summary,
    license_notice_for,
    read_license_ack,
    write_license_ack,
)


def test_license_notice_for_buffalo_mentions_noncommercial() -> None:
    text = license_notice_for("buffalo_l")
    assert "InsightFace" in text
    assert "Non-Commercial Research Use Only" in text
    assert "I AGREE" in text


def test_license_notice_for_custom_model_is_short() -> None:
    text = license_notice_for("arcface_webface4m")
    assert "NOT shipped by pick-face" in text


def test_is_insightface_model() -> None:
    assert is_insightface_model("buffalo_l")
    assert is_insightface_model("buffalo_sc")
    assert not is_insightface_model("arcface_webface4m")
    assert not is_insightface_model("")


def test_write_license_ack_creates_json(tmp_pure: Path) -> None:
    model_dir = tmp_pure / "models" / "buffalo_l"
    p = write_license_ack(model_dir, "buffalo_l", acked_by="tester")
    assert p == model_dir / ".license_ack"
    assert p.exists()
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload["model"] == "buffalo_l"
    assert payload["license"] == "InsightFace non-commercial-research"
    assert payload["acked_by"] == "tester"
    assert "InsightFace" in payload["ack_text"]


def test_read_license_ack_round_trip(tmp_pure: Path) -> None:
    model_dir = tmp_pure / "models" / "buffalo_l"
    write_license_ack(model_dir, "buffalo_l", acked_by="alice")
    ack = read_license_ack(model_dir)
    assert ack is not None
    assert ack["acked_by"] == "alice"


def test_read_license_ack_missing_returns_none(tmp_pure: Path) -> None:
    assert read_license_ack(tmp_pure / "nope") is None


def test_license_ack_summary_includes_user(tmp_pure: Path) -> None:
    # Redirect model_dir via env won't expand: easier to write manually.
    model_dir = tmp_pure / "models" / "buffalo_l"
    write_license_ack(model_dir, "buffalo_l", acked_by="alice")
    cfg2 = PickFaceConfig(runtime={"model_name": "buffalo_l", "model_dir": tmp_pure / "models"})
    s = license_ack_summary(cfg2)
    assert s is not None
    assert "alice" in s


def test_license_ack_summary_missing_returns_none(tmp_pure: Path) -> None:
    cfg = PickFaceConfig(runtime={"model_name": "buffalo_l", "model_dir": tmp_pure / "models"})
    assert license_ack_summary(cfg) is None
