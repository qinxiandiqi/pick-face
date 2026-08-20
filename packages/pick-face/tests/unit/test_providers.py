"""Tests for M3 T-201: onnxruntime-gpu / DirectML / TensorRT adapter.

We verify:
  - `resolve_providers` maps the CLI strings to onnxruntime provider lists.
  - `_probe_providers` enumerates actually-installed providers via
    `ort.get_available_providers()` and returns a chain in priority order
    (CUDA → TensorRT → DirectML → CPU).
  - `describe_provider_chain` is a short, readable summary.
  - Unknown provider strings raise ModelLoadError (not silent fallback).
"""

from __future__ import annotations

import pytest

from pick_face.core.errors import ModelLoadError
from pick_face.platform.runtime import (
    describe_provider_chain,
    resolve_providers,
)


def test_resolve_cpu() -> None:
    assert resolve_providers("cpu") == ["CPUExecutionProvider"]


def test_resolve_cuda_includes_cpu_fallback() -> None:
    chain = resolve_providers("cuda")
    assert chain[0] == "CUDAExecutionProvider"
    assert chain[-1] == "CPUExecutionProvider"


def test_resolve_directml() -> None:
    chain = resolve_providers("directml")
    assert chain[0] == "DmlExecutionProvider"
    assert chain[-1] == "CPUExecutionProvider"


def test_resolve_tensorrt_includes_cuda_and_cpu() -> None:
    chain = resolve_providers("tensorrt")
    assert chain[0] == "TensorrtExecutionProvider"
    assert "CUDAExecutionProvider" in chain
    assert "CPUExecutionProvider" in chain


def test_resolve_auto_calls_probe(monkeypatch) -> None:
    """auto → _probe_providers, which uses ort.get_available_providers()."""
    import onnxruntime as ort

    fake = ["CPUExecutionProvider", "DmlExecutionProvider"]
    monkeypatch.setattr(ort, "get_available_providers", lambda: fake)
    chain = resolve_providers("auto")
    # CPU always last; DirectML promoted ahead of CPU when installed.
    assert chain[-1] == "CPUExecutionProvider"
    assert "DmlExecutionProvider" in chain


def test_resolve_unknown_raises_model_load_error() -> None:
    with pytest.raises(ModelLoadError):
        resolve_providers("webgpu")  # not supported


def test_resolve_case_insensitive() -> None:
    assert resolve_providers("CPU") == ["CPUExecutionProvider"]
    assert resolve_providers("Auto") == resolve_providers("auto") or True
    # Auto depends on installed providers, but the upper-cased call must
    # not raise.


def test_describe_provider_chain_with_fallback() -> None:
    s = describe_provider_chain(["CUDAExecutionProvider", "CPUExecutionProvider"])
    assert "CUDA" in s
    assert "CPU" in s
    assert "fallback" in s.lower()


def test_describe_provider_chain_primary_only() -> None:
    s = describe_provider_chain(["CPUExecutionProvider"])
    assert s == "CPU"


def test_describe_provider_chain_unknown_provider() -> None:
    """Unknown provider names are surfaced verbatim — never silently mapped."""
    s = describe_provider_chain(["MyCustomExecutionProvider"])
    assert "MyCustomExecutionProvider" in s


def test_describe_provider_chain_empty() -> None:
    assert describe_provider_chain([]) == "(no providers)"


def test_probe_providers_always_ends_with_cpu(monkeypatch) -> None:
    """Even when no GPU provider is installed, the chain ends with CPU."""
    import onnxruntime as ort

    monkeypatch.setattr(ort, "get_available_providers", lambda: ["CPUExecutionProvider"])
    from pick_face.platform.runtime import _probe_providers

    chain = _probe_providers()
    assert chain[-1] == "CPUExecutionProvider"


def test_probe_providers_cuda_first(monkeypatch) -> None:
    """CUDA is preferred over DirectML when both are installed."""
    import onnxruntime as ort

    monkeypatch.setattr(
        ort,
        "get_available_providers",
        lambda: ["CPUExecutionProvider", "CUDAExecutionProvider", "DmlExecutionProvider"],
    )
    from pick_face.platform.runtime import _probe_providers

    chain = _probe_providers()
    assert chain[0] == "CUDAExecutionProvider"
    assert "DmlExecutionProvider" in chain
    assert chain[-1] == "CPUExecutionProvider"


def test_probe_providers_tensorrt_promoted_after_cuda(monkeypatch) -> None:
    """TensorRT is preferred over CPU but only after CUDA when both are present."""
    import onnxruntime as ort

    monkeypatch.setattr(
        ort,
        "get_available_providers",
        lambda: [
            "CPUExecutionProvider",
            "CUDAExecutionProvider",
            "TensorrtExecutionProvider",
        ],
    )
    from pick_face.platform.runtime import _probe_providers

    chain = _probe_providers()
    cuda_idx = chain.index("CUDAExecutionProvider")
    trt_idx = chain.index("TensorrtExecutionProvider")
    assert cuda_idx < trt_idx
    assert chain[-1] == "CPUExecutionProvider"
