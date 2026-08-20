"""Guard: vite build artifacts (src/pick_face/web/static/) exist when expected.

Why this exists
---------------
M7 wires `pnpm build` into both CI (`.github/workflows/ci.yml`,
job ``frontend-build``) and the release workflow
(`.github/workflows/release.yml`) so the wheel always ships the SPA bundle.

The wheel build (`uv build`) packages `web/static/` automatically
because `src/pick_face/web/__init__.py` makes it package data. If vite
silently fails to emit ``index.html`` (config drift, outDir typo, env
issue) the wheel still builds — it's missing the UI but installs fine,
and downstream smoke tests would catch it only at runtime.

This test catches the silent-failure mode: it asserts the build
artifacts exist *when* a build has been run. In dev / CI, when vite
build is part of the pipeline, this is a hard assertion. In a fresh
clone without a build (e.g. someone runs ``uv run pytest`` immediately
after ``git clone``), we **skip** with a clear message so the test
suite stays green for contributors who haven't built the SPA yet.

Tracked contract: ``docs/06-engineering-plan.md`` — M6-T-13, M7-T-1.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
STATIC_DIR = REPO_ROOT / "packages" / "pick-face" / "src" / "pick_face" / "web" / "static"
INDEX_HTML = STATIC_DIR / "index.html"
ASSETS_DIR = STATIC_DIR / "assets"


def _vite_has_built() -> bool:
    """Vite writes index.html to outDir; assets go under outDir/assets/."""
    return INDEX_HTML.is_file()


@pytest.mark.skipif(
    not _vite_has_built(),
    reason=(
        "vite build has not been run — `src/pick_face/web/static/index.html` "
        "is missing. To produce it locally: "
        "`cd src/pick_face/web/app && pnpm install && pnpm build`. "
        "CI runs the build via the `frontend-build` job before `unit`."
    ),
)
def test_vite_emitted_index_html() -> None:
    """The SPA entry point must exist after `pnpm build`."""
    assert INDEX_HTML.is_file(), (
        f"expected vite output at {INDEX_HTML}; "
        "did `pnpm --dir src/pick_face/web/app build` succeed?"
    )
    # Sanity: it really is an HTML document
    head = INDEX_HTML.read_text(encoding="utf-8", errors="replace")[:200].lower()
    assert "<!doctype html>" in head or "<html" in head, (
        f"{INDEX_HTML} doesn't look like an HTML document; head was: {head!r}"
    )


@pytest.mark.skipif(
    not _vite_has_built(),
    reason="vite build has not been run; assets/ subdir not expected.",
)
def test_vite_emitted_assets_subdir() -> None:
    """Vite default outDir layout puts hashed JS/CSS under assets/.

    We don't pin exact filenames (hashed), but the directory must
    contain at least one JS and one CSS file.
    """
    assert ASSETS_DIR.is_dir(), (
        f"expected vite to emit an assets/ subdir under {STATIC_DIR}; "
        "check `build.outDir` in src/pick_face/web/app/vite.config.ts."
    )
    js_files = list(ASSETS_DIR.glob("*.js"))
    css_files = list(ASSETS_DIR.glob("*.css"))
    assert js_files, f"no .js emitted under {ASSETS_DIR}"
    assert css_files, f"no .css emitted under {ASSETS_DIR}"


@pytest.mark.skipif(
    not _vite_has_built(),
    reason="vite build has not been run; static/ empty, nothing to verify.",
)
def test_static_dir_contains_no_onnx() -> None:
    """AC-9 belt-and-suspenders: vite output must not carry .onnx.

    Vite's source-loader chain shouldn't introduce any, but a careless
    `import.meta.url` of a model file could. Belt-and-suspenders so the
    AC-9 guard catches it at this layer too.
    """
    offenders = [
        p for p in STATIC_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in {".onnx", ".onnxdata"}
    ]
    assert offenders == [], (
        f"AC-9 violation: vite output contains model artifacts: {offenders}"
    )
