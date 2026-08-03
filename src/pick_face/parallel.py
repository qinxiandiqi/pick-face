"""Process-level parallelism + progress reporting (M3 / T-202).

Reference:
- docs/03 §3 (workers / prefetch knobs)
- docs/09 §13 (parallel indexing: workers pull from a queue, emit
  per-source progress so the UI can update live)
- docs/06 §T-202 (--progress json + TUI)

Design:
  - Public entry point is `run_pool()`. Callers hand it:
      * `items`: iterable of input units (paths / source_ids).
      * `process_one`: a top-level function that takes ONE item and
        returns a per-item result (or raises).
      * `workers`: number of processes (1 = serial).
      * `prefetch`: queue depth per worker.
      * `progress`: "human" | "json" | "quiet".
      * `on_progress`: optional callback (done, total, item, result).
  - The function returns a list of per-item results in INPUT ORDER.
    Items that raised are returned as `_FailedItem` so the caller can
    decide whether to retry or surface as warnings.
  - Progress events:
        {"event": "start", "total": N}
        {"event": "progress", "done": K, "total": N, "rate": float}
        {"event": "item_done", "done": K, "total": N, "item": ...,
         "result": ... or "error": "..."}
        {"event": "done", "done": N, "total": N, "elapsed_sec": float}

Why multiprocessing (not threading): the detector/embedder is CPU-bound
ONNX, and onnxruntime releases the GIL for forward passes only on a
few specific builds. Multiprocessing is the portable answer.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class _FailedItem:
    item: Any
    error: str


def _process_item(item: Any, process_one: Callable[[Any], Any]) -> Any:
    """Top-level wrapper: returns the result or an _FailedItem marker."""
    try:
        return process_one(item)
    except Exception as e:
        return _FailedItem(item=item, error=f"{type(e).__name__}: {e}")


def run_pool(
    items: Sequence[Any],
    process_one: Callable[[Any], Any],
    *,
    workers: int = 1,
    prefetch: int = 4,
    progress: str = "human",
    on_progress: Callable[[dict], None] | None = None,
) -> list[Any]:
    """Process *items* in parallel; return results in input order.

    Args:
        items: input units.
        process_one: top-level callable (must be picklable for spawn).
        workers: process pool size. 1 = serial.
        prefetch: queue depth per worker (currently advisory; the
            pool's internal queue depth is fixed). Documented so users
            have a knob to expect when more parallelism shows up.
        progress: "human" | "json" | "quiet". "human" emits a progress
            line on stderr (one update per item); "json" writes one JSON
            object per line to stdout; "quiet" emits nothing.
        on_progress: optional callback receiving the same event dicts.

    Returns:
        List of per-item results in input order. Failures appear as
        _FailedItem so the caller can decide whether to retry.

    Raises:
        ValueError: workers<1, prefetch<1, or unknown progress mode.
    """
    if workers < 1:
        raise ValueError(f"workers must be ≥1, got {workers}")
    if prefetch < 1:
        raise ValueError(f"prefetch must be ≥1, got {prefetch}")
    if progress not in ("human", "json", "quiet"):
        raise ValueError(f"unknown progress mode: {progress!r}")

    # prefetch is currently advisory — the ProcessPoolExecutor owns its
    # own queue depth. We keep it in the signature so callers have a knob
    # to expect when M3 T-202 (true prefetch + backpressure) lands.
    total = len(items)
    started = time.monotonic()
    _emit({"event": "start", "total": total}, progress, on_progress)

    results: list[Any] = [None] * total  # type: ignore[list-item]

    if workers == 1 or total <= 1:
        # Serial path. Avoids the spawn dance on Windows.
        for i, item in enumerate(items):
            r = _process_item(item, process_one)
            results[i] = r
            _emit_item(progress, on_progress, i + 1, total, item, r)
    else:
        ctx = mp.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as ex:
            future_to_index = {
                ex.submit(_process_item, item, process_one): i for i, item in enumerate(items)
            }
            for done_count, fut in enumerate(as_completed(future_to_index), start=1):
                i = future_to_index[fut]
                r = fut.result()
                results[i] = r
                _emit_item(progress, on_progress, done_count, total, items[i], r)

    elapsed = time.monotonic() - started
    _emit(
        {"event": "done", "done": total, "total": total, "elapsed_sec": elapsed},
        progress,
        on_progress,
    )
    return results


def _emit_item(
    mode: str,
    on_progress: Callable[[dict], None] | None,
    done: int,
    total: int,
    item: Any,
    result: Any,
) -> None:
    _emit(
        {
            "event": "item_done",
            "done": done,
            "total": total,
            "item": _summarize_item(item),
            "result": _summarize_result(result),
        },
        mode,
        on_progress,
    )


def _summarize_item(item: Any) -> Any:
    """Make item JSON-serializable for progress events."""
    if isinstance(item, (str, int, float, bool, type(None))):
        return item
    try:
        from pathlib import Path

        if isinstance(item, Path):
            return str(item)
    except Exception:
        pass
    return repr(item)


def _summarize_result(result: Any) -> Any:
    """Truncate long results so progress output stays readable."""
    if isinstance(result, _FailedItem):
        return {"error": result.error}
    if isinstance(result, (str, int, float, bool, type(None))):
        return result
    return repr(result)[:200]


def _emit(event: dict, mode: str, on_progress: Callable[[dict], None] | None) -> None:
    """Send a progress event to the requested sinks."""
    if on_progress is not None:
        try:
            on_progress(event)
        except Exception:
            pass
    if mode == "json":
        sys.stdout.write(json.dumps(event, sort_keys=True, default=str) + "\n")
        sys.stdout.flush()
    elif mode == "human":
        ev = event.get("event")
        if ev == "start":
            total = event.get("total", 0)
            sys.stderr.write(f"… start: {total} item(s)\n")
        elif ev == "item_done":
            done = event.get("done", 0)
            total = event.get("total", 1)
            pct = (done / total * 100) if total else 0
            sys.stderr.write(f"\r… {done}/{total}  ({pct:5.1f}%)")
            sys.stderr.flush()
        elif ev == "done":
            elapsed = event.get("elapsed_sec", 0)
            sys.stderr.write(f"\n✓ done in {elapsed:.1f}s\n")
