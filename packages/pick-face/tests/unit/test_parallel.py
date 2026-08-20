"""Tests for pick_face.parallel (M3 / T-202).

We exercise the serial path (workers=1) thoroughly because multiprocess
spawn is brittle in CI. The parallel path is smoke-tested with workers=2.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pick_face.output.parallel import _FailedItem, run_pool


def _double(x: int) -> int:
    return x * 2


def _raise(x: int) -> int:
    raise ValueError(f"nope {x}")


def test_run_pool_serial_preserves_order() -> None:
    out = run_pool([1, 2, 3, 4, 5], _double, workers=1, progress="quiet")
    assert out == [2, 4, 6, 8, 10]


def test_run_pool_serial_empty() -> None:
    out = run_pool([], _double, workers=1, progress="quiet")
    assert out == []


def test_run_pool_serial_captures_failures() -> None:
    """A failing item is returned as _FailedItem, others succeed."""
    out = run_pool([1, 2, 3], _raise, workers=1, progress="quiet")
    assert len(out) == 3
    for item in out:
        assert isinstance(item, _FailedItem)
        assert "nope" in item.error


def test_run_pool_serial_mixed_results() -> None:
    def maybe(x: int) -> int | _FailedItem:
        if x % 2 == 0:
            return _FailedItem(item=x, error="even")
        return x

    out = run_pool([1, 2, 3, 4], maybe, workers=1, progress="quiet")
    assert out[0] == 1
    assert isinstance(out[1], _FailedItem)
    assert out[2] == 3
    assert isinstance(out[3], _FailedItem)


def test_run_pool_json_progress_emits_one_line_per_event(capsys) -> None:
    events: list[dict] = []
    run_pool(
        [1, 2, 3],
        _double,
        workers=1,
        progress="json",
        on_progress=events.append,
    )
    captured = capsys.readouterr()
    # stdout must have exactly N+2 JSON lines: start, item_done*3, done
    lines = [ln for ln in captured.out.splitlines() if ln.startswith("{")]
    assert len(lines) == 1 + 3 + 1
    # Every line parses.
    for ln in lines:
        json.loads(ln)


def test_run_pool_quiet_emits_nothing(capsys) -> None:
    run_pool([1, 2], _double, workers=1, progress="quiet")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_run_pool_human_progress_emits_to_stderr(capsys) -> None:
    run_pool([1, 2, 3], _double, workers=1, progress="human")
    captured = capsys.readouterr()
    # Human mode writes to stderr; stdout stays clean.
    assert "start" in captured.err
    assert "done" in captured.err.lower() or "✓" in captured.err
    assert captured.out == ""


def test_run_pool_on_progress_receives_events() -> None:
    events: list[dict] = []
    run_pool(
        [1, 2],
        _double,
        workers=1,
        progress="quiet",
        on_progress=events.append,
    )
    kinds = [e["event"] for e in events]
    assert kinds[0] == "start"
    assert kinds[-1] == "done"
    item_done = [e for e in events if e["event"] == "item_done"]
    assert len(item_done) == 2
    # Done counter strictly increases.
    counts = [e["done"] for e in item_done]
    assert counts == sorted(counts)
    assert counts[-1] == 2


def test_run_pool_invalid_workers() -> None:
    with pytest.raises(ValueError):
        run_pool([1], _double, workers=0)


def test_run_pool_invalid_progress_mode() -> None:
    with pytest.raises(ValueError):
        run_pool([1], _double, workers=1, progress="tui")


def test_run_pool_on_progress_exception_does_not_kill_run() -> None:
    def bad_cb(_event: dict) -> None:
        raise RuntimeError("bad callback")

    # Should NOT raise — bad callbacks are swallowed.
    out = run_pool([1, 2], _double, workers=1, progress="quiet", on_progress=bad_cb)
    assert out == [2, 4]


def test_run_pool_parallel_preserves_order() -> None:
    """workers=2 with a tiny workload still produces ordered output."""
    out = run_pool([1, 2, 3, 4, 5, 6], _double, workers=2, progress="quiet")
    assert out == [2, 4, 6, 8, 10, 12]


def test_run_pool_parallel_captures_failures() -> None:
    out = run_pool([1, 2, 3], _raise, workers=2, progress="quiet")
    assert len(out) == 3
    for item in out:
        assert isinstance(item, _FailedItem)


def test_run_pool_handles_path_items() -> None:
    """Path items are summarized as strings in progress events."""
    events: list[dict] = []
    paths = [Path("/a"), Path("/b")]
    run_pool(paths, _double, workers=1, progress="quiet", on_progress=events.append)
    item_done = [e for e in events if e["event"] == "item_done"]
    # The double(str(Path)) raises, so we expect _FailedItem — but the
    # important thing is that summary doesn't crash on Path objects.
    assert len(item_done) == 2
