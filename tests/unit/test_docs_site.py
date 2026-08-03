"""Sanity-check the docs site config without invoking mkdocs.

This is a minimal gate so the mkdocs.yml stays parseable even if mkdocs
isn't installed locally. mkdocs itself is exercised in CI via the
`docs` job (M4 / T-303).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
MKDOCS_YML = REPO / "mkdocs.yml"


def test_mkdocs_yml_exists() -> None:
    assert MKDOCS_YML.exists(), f"missing {MKDOCS_YML}"


def test_mkdocs_yml_parses_as_yaml() -> None:
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load(MKDOCS_YML.read_text(encoding="utf-8"))
    assert data["site_name"] == "pick-face"
    assert "nav" in data
    assert "theme" in data


def test_mkdocs_nav_references_existing_files() -> None:
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load(MKDOCS_YML.read_text(encoding="utf-8"))
    nav = data.get("nav", [])
    missing: list[str] = []
    for entry in nav:
        # Each entry is either a str (file) or a 2-list [title, file-or-subnav].
        if isinstance(entry, str):
            target = entry
        elif isinstance(entry, list) and len(entry) >= 2:
            target = entry[1]
        else:
            continue
        if isinstance(target, str) and target.endswith(".md"):
            full = REPO / "docs" / target
            if not full.exists():
                missing.append(target)
    assert not missing, f"mkdocs nav references missing files: {missing}"


def test_docs_index_exists() -> None:
    """The mkdocs landing page exists."""
    assert (REPO / "docs" / "index.md").exists()


def test_docs_index_links_to_compliance_first() -> None:
    """docs/index.md must mention the commercial-compliance doc near the top."""
    text = (REPO / "docs" / "index.md").read_text(encoding="utf-8")
    # The compliance doc link must appear within the first 60 lines.
    head = "\n".join(text.splitlines()[:60])
    assert "11-commercial-compliance" in head


def test_readme_references_compliance() -> None:
    """README.md must reference the commercial-compliance doc."""
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert "11-commercial-compliance" in text
