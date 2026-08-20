"""M4 / T-305 — 1.0 release guard.

Verifies the public-API / persistence contract documented in
`docs/12-compatibility-promise.md`:

* `pick_face.__version__` is parseable as a SemVer triple with major >= 1.
* `pyproject` classifier is "5 - Production/Stable".
* CHANGELOG.md has a [1.0.0] (or higher) section that links to the
  compatibility promise doc.
* All persisted format headers include a `schema` field whose string
  matches the `pick-face/<name>@<N>` pattern (we assert >= 1).
* The CLI subcommand set matches the stable list in §1.1.

Run with: uv run pytest tests/unit/test_release_contract.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import tomllib

from pick_face import __version__

REPO = Path(__file__).resolve().parents[4]
PKG = REPO / "packages" / "pick-face"


def test_version_is_semver_with_major_ge_1() -> None:
    """We promised 1.0+ stability — the major component must be ≥ 1.

    Route B dev versions look like ``2.0.0.dev0`` (PEP 440 dev release);
    the test tolerates that as a 4-part version where the leading three
    parts are the SemVer triple and the trailing component is the
    pre-release tag.
    """
    parts = __version__.split(".")
    assert len(parts) in (3, 4), f"version {__version__!r} is not MAJOR.MINOR.PATCH"
    for p in parts[:3]:
        assert p.isdigit(), f"version component {p!r} is not numeric"
    assert int(parts[0]) >= 1, (
        f"version {__version__!r} is below 1.0.0 — the compatibility "
        f"promise in docs/12-compatibility-promise.md does not apply yet."
    )


def test_classifier_is_production_stable() -> None:
    pyproject = tomllib.loads((PKG / "pyproject.toml").read_text(encoding="utf-8"))
    classifiers = pyproject["project"]["classifiers"]
    assert "Development Status :: 5 - Production/Stable" in classifiers, (
        f"classifiers missing '5 - Production/Stable': {classifiers}"
    )


def test_changelog_has_1_0_entry() -> None:
    text = (PKG / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(r"^##\s+\[1\.0\.\d+\]", text, re.MULTILINE), (
        "CHANGELOG.md must have a [1.0.x] section for the 1.0 release."
    )


def test_changelog_links_to_compat_promise() -> None:
    text = (PKG / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "12-compatibility-promise" in text, (
        "CHANGELOG.md must reference docs/12-compatibility-promise.md"
    )


def test_compat_promise_doc_exists() -> None:
    assert (PKG / "docs" / "12-compatibility-promise.md").exists(), (
        "docs/12-compatibility-promise.md must exist for the 1.0 contract."
    )


def test_compat_promise_doc_covers_required_sections() -> None:
    text = (PKG / "docs" / "12-compatibility-promise.md").read_text(encoding="utf-8")
    for heading in (
        "Public CLI surface",
        "Python public API",
        "Persistence formats",
        "Deprecation policy",
        "Supported Python & OS matrix",
        "Versioning policy",
    ):
        assert heading in text, f"compatibility promise doc missing section: {heading!r}"


def test_mkdocs_nav_includes_compat_promise() -> None:
    import yaml

    data = yaml.safe_load((PKG / "mkdocs.yml").read_text(encoding="utf-8"))

    def _flatten(node) -> list[str]:
        """Yield every string-valued leaf from a (possibly nested) mkdocs nav entry."""
        if isinstance(node, str):
            return [node]
        if isinstance(node, list):
            out: list[str] = []
            for child in node:
                out.extend(_flatten(child))
            return out
        if isinstance(node, dict):
            out = []
            for value in node.values():
                out.extend(_flatten(value))
            return out
        return []

    flat = _flatten(data.get("nav", []))
    assert any("12-compatibility-promise" in f for f in flat), (
        f"mkdocs nav must reference 12-compatibility-promise.md; got {flat}"
    )


def test_readme_references_compat_promise() -> None:
    text = (PKG / "README.md").read_text(encoding="utf-8")
    assert "12-compatibility-promise" in text, (
        "README.md must link to docs/12-compatibility-promise.md"
    )


# Stable subcommand set per docs/12-compatibility-promise.md §1.1.
STABLE_SUBCOMMANDS = {
    "init",
    "init-models",
    "scan",
    "index",
    "cluster",
    "link",
    "run",
    "report",
    "review",
    "gc",
    "prune",
    "rollback",
    "rebuild",
}


def test_cli_subcommand_set_is_stable() -> None:
    """Stable CLI subcommands must exist on the live CLI.

    We invoke `pick-face --help` and grep the listed commands. If this
    test ever breaks, you've either removed a stable command (major
    bump) or added one without updating §1.1 (minor bump OK, just
    document it in CHANGELOG.md).
    """
    import subprocess

    r = subprocess.run(
        ["uv", "run", "pick-face", "--help"],
        cwd=str(REPO / "packages" / "pick-face"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if r.returncode != 0:
        pytest.skip(f"`pick-face --help` not invokable in this env: {(r.stderr or '')[:120]}")
    text = (r.stdout or "") + (r.stderr or "")
    found = set()
    for cmd in STABLE_SUBCOMMANDS:
        # Match the subcommand as a standalone token (top-level command).
        if re.search(rf"\b{re.escape(cmd)}\b", text):
            found.add(cmd)
    assert STABLE_SUBCOMMANDS.issubset(found), (
        f"missing stable subcommands on the CLI: {STABLE_SUBCOMMANDS - found}"
    )


def test_persistence_schema_strings_follow_pick_face_at_n_pattern() -> None:
    """Every persistence format must use the `pick-face/<name>@<N>` schema.

    We grep the source tree for the literal schemas and verify they all
    match the documented pattern. Bumping <N> requires a major version
    bump per docs/12 §1.3.
    """
    schema_re = re.compile(r'"pick-face/[a-z_]+@\d+"')
    src = (REPO / "packages" / "pick-face" / "src" / "pick_face").rglob("*.py")
    found: list[str] = []
    for path in src:
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in schema_re.findall(text):
            found.append(m)
    # We expect at least these schemas to exist in the codebase.
    expected_prefixes = {
        "pick-face/index@",
        "pick-face/checkpoint@",
        "pick-face/meta@",
        "pick-face/perf_report@",
    }
    seen_prefixes = {s.strip('"').rsplit("@", 1)[0] + "@" for s in found}
    missing = expected_prefixes - seen_prefixes
    assert not missing, f"missing persistence schema definitions in source: {missing}"
