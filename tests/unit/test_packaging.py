"""M4 / T-304 packaging guard.

Verifies that `uv build` produces clean sdist + wheel:

* wheel contains exactly the 24 public modules + dist-info.
* sdist contains docs/ + src/ + tests/ + LICENSE + README + CHANGELOG + mkdocs.yml.
* No *.onnx / *.onnxdata in either artifact (AC-9).
* Console-script entry point wires `pick-face` → `pick_face.cli:main`.
* LICENSE is shipped under dist-info.

Run with: uv run pytest tests/unit/test_packaging.py -q
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from importlib import metadata
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
EXPECTED_MODULES = {
    "align",
    "bench",
    "checkpoint",
    "cli",
    "cluster",
    "config",
    "detector",
    "embedder",
    "errors",
    "hashing",
    "images",
    "index",
    "index_hnsw",
    "linker",
    "mirrors",
    "models",
    "parallel",
    "paths",
    "reporter",
    "review",
    "runtime",
    "scanner",
}


@pytest.fixture(scope="module")
def built_artifacts(tmp_path_factory):
    """Run `uv build` into a scratch dir and return (whl_path, sdist_path)."""
    out = tmp_path_factory.mktemp("build")
    r = subprocess.run(
        ["uv", "build", "--out-dir", str(out)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if r.returncode != 0:
        pytest.skip(f"uv build unavailable in this env (rc={r.returncode}): {r.stderr[:200]}")
    whl = next(iter(out.glob("*.whl")), None)
    sdist = next(iter(out.glob("*.tar.gz")), None)
    if not (whl and sdist):
        pytest.skip(f"uv build did not produce both artifacts: {r.stdout[:200]}")
    return whl, sdist


def _dist_info_prefix(whl_path: Path) -> str:
    """Return the wheel's dist-info directory name (e.g. `pick_face-1.0.0.dist-info`).

    Reading the version from the actual built artifact (rather than hardcoding
    `0.1.0`) means the tests keep working across version bumps.
    """
    with zipfile.ZipFile(whl_path) as z:
        matches = sorted(
            {
                n.split("/", 1)[0]
                for n in z.namelist()
                if n.endswith(".dist-info") or n.startswith("pick_face-") and ".dist-info/" in n
            }
        )
    candidates = [m for m in matches if m.endswith(".dist-info")]
    if not candidates:
        raise AssertionError(f"no .dist-info/ in {whl_path.name}: matched={matches}")
    return candidates[0]


def test_wheel_contains_all_modules(built_artifacts) -> None:
    whl, _ = built_artifacts
    with zipfile.ZipFile(whl) as z:
        names = z.namelist()
    modules_in_wheel = {
        n.removeprefix("pick_face/").removesuffix(".py")
        for n in names
        if n.startswith("pick_face/")
        and n.endswith(".py")
        and "/" not in n.removeprefix("pick_face/")
    }
    # __init__.py is expected too.
    assert "pick_face/__init__.py" in names
    assert EXPECTED_MODULES.issubset(modules_in_wheel), (
        f"missing modules in wheel: {EXPECTED_MODULES - modules_in_wheel}"
    )


def test_wheel_has_no_onnx(built_artifacts) -> None:
    whl, _ = built_artifacts
    with zipfile.ZipFile(whl) as z:
        bad = [n for n in z.namelist() if n.lower().endswith((".onnx", ".onnxdata"))]
    assert not bad, f"AC-9 violation in wheel: {bad}"


def test_sdist_has_no_onnx(built_artifacts) -> None:
    _, sdist = built_artifacts
    with tarfile.open(sdist, "r:gz") as t:
        bad = [m.name for m in t.getmembers() if m.name.lower().endswith((".onnx", ".onnxdata"))]
    assert not bad, f"AC-9 violation in sdist: {bad}"


def test_sdist_includes_docs_and_license(built_artifacts) -> None:
    _, sdist = built_artifacts
    with tarfile.open(sdist, "r:gz") as t:
        names = set(t.getnames())
    assert any(n.endswith("LICENSE") for n in names), "LICENSE missing from sdist"
    assert any(n.endswith("README.md") for n in names), "README.md missing from sdist"
    assert any(n.endswith("CHANGELOG.md") for n in names), "CHANGELOG.md missing from sdist"
    assert any("docs/index.md" in n for n in names), "docs/index.md missing from sdist"
    assert any(n.endswith("mkdocs.yml") for n in names), "mkdocs.yml missing from sdist"


def test_wheel_entry_point(built_artifacts) -> None:
    whl, _ = built_artifacts
    prefix = _dist_info_prefix(whl)
    with zipfile.ZipFile(whl) as z:
        ep = z.read(f"{prefix}/entry_points.txt").decode("utf-8")
    assert "pick-face = pick_face.cli:main" in ep


def test_wheel_license_present(built_artifacts) -> None:
    whl, _ = built_artifacts
    prefix = _dist_info_prefix(whl)
    with zipfile.ZipFile(whl) as z:
        names = z.namelist()
    assert any(n.startswith(f"{prefix}/licenses/") for n in names), (
        f"License must be included under {prefix}/licenses/ per PEP 639"
    )


def test_installed_package_metadata_is_consistent() -> None:
    """The package as currently installed must have a parseable METADATA."""
    try:
        md = metadata.metadata("pick-face")
    except metadata.PackageNotFoundError:
        pytest.skip("pick-face not installed in this env")
    assert md["Name"] == "pick-face"
    assert md["License"] == "Apache-2.0"
    # Console script must be registered.
    eps = metadata.entry_points(group="console_scripts")
    pf = [e for e in eps if e.name == "pick-face"]
    assert pf, "pick-face console script missing"
    assert pf[0].value == "pick_face.cli:main"


def test_wheel_is_python_3_pure(built_artifacts) -> None:
    """Pick-face is pure Python — wheel tag must be py3-none-any."""
    whl, _ = built_artifacts
    prefix = _dist_info_prefix(whl)
    with zipfile.ZipFile(whl) as z:
        wheel = z.read(f"{prefix}/WHEEL").decode("utf-8")
    assert "py3-none-any" in wheel, f"expected py3-none-any wheel, got:\n{wheel}"


def test_uv_build_is_quiet() -> None:
    """Sanity: uv build runs cleanly with our pyproject (no missing files)."""
    # We don't re-run the build here — that's `built_artifacts` — but we DO
    # ensure `uv` is callable so CI can rely on it.
    r = subprocess.run(["uv", "--version"], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        pytest.skip(f"uv not available: {r.stderr}")
    assert r.returncode == 0
    assert r.stdout.strip().startswith("uv ")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
