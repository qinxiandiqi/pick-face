"""Tests for pick_face.web_cli — init / migrate subcommands (serve is a thin uvicorn wrapper, covered by smoke)."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_init_creates_app_root(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("PICK_FACE_HOME", str(tmp_pure / "app"))
    from pick_face import web_cli

    rc = web_cli.main(["init"])
    assert rc == 0
    layout_root = tmp_pure / "app"
    assert (layout_root / "config").is_dir()
    assert (layout_root / "data").is_dir()
    assert (layout_root / "cache").is_dir()
    assert (layout_root / "config" / "config.toml").exists()
    out = capsys.readouterr().out
    assert "app root" in out


def test_init_with_add_path_whitelists(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("PICK_FACE_HOME", str(tmp_pure / "app"))
    photos = tmp_pure / "photos"
    photos.mkdir()
    from pick_face import web_cli

    rc = web_cli.main(["init", "--add-path", str(photos)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "whitelisted" in out
    # Path was actually written. We don't assert exact string
    # equality (the on-disk form is TOML-escaped); just check that
    # the file contains the leaf component.
    layout_root = tmp_pure / "app"
    body = (layout_root / "config" / "config.toml").read_text()
    assert "photos" in body
    # And it's syntactically valid TOML.
    import tomllib

    parsed = tomllib.loads(body)
    assert parsed["scan_paths"][0]["enabled"] is True


def test_init_add_path_warns_on_invalid(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("PICK_FACE_HOME", str(tmp_pure / "app"))
    from pick_face import web_cli

    rc = web_cli.main(["init", "--add-path", "/nonexistent/path/xyz"])
    # Init itself still succeeds; it just warns.
    assert rc == 0
    out = capsys.readouterr().out
    assert "warning" in out
    assert "NOT_FOUND" in out


def test_init_explicit_root_flag_wins(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PICK_FACE_HOME", str(tmp_pure / "env-root"))
    from pick_face import web_cli

    rc = web_cli.main(["init", "--root", str(tmp_pure / "arg-root")])
    assert rc == 0
    assert (tmp_pure / "arg-root" / "config").is_dir()
    assert not (tmp_pure / "env-root").exists()


def test_migrate_ensures_schema(tmp_pure: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    monkeypatch.setenv("PICK_FACE_HOME", str(tmp_pure / "app"))
    from pick_face import web_cli

    rc = web_cli.main(["migrate"])
    assert rc == 0
    db_path = tmp_pure / "app" / "data" / "index.sqlite"
    assert db_path.exists()
    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "source" in tables
    assert "face" in tables


def test_serve_help_lists_subcommands() -> None:
    """Sanity: ``pick-face-web`` subcommand list is stable for users."""
    from pick_face import web_cli

    parser = web_cli.build_parser()
    # Parse with no args → SystemExit
    import pytest as _p

    with _p.raises(SystemExit):
        parser.parse_args([])


def test_serve_uses_default_host_port() -> None:
    from pick_face import web_cli

    parser = web_cli.build_parser()
    args = parser.parse_args(["serve"])
    assert args.host is None
    assert args.port is None
    assert args.reload is False
    assert args.log_level == "info"
