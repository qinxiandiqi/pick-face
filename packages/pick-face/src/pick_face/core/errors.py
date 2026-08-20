"""Exception hierarchy and exit code contract.

Reference:
- docs/03 §9 错误处理
- docs/09 §12 错误处理与可恢复性
- docs/11 §3.6 退出码契约扩展 (AC-9 增加退出码 2 用于商业 license 校验失败)
"""

from __future__ import annotations


class PickFaceError(Exception):
    """Base exception. exit_code is the CLI exit code when this escapes."""

    exit_code: int = 1

    def __init__(self, message: str = "", *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause


# -------------------- Config / input errors (exit 2) --------------------


class ConfigError(PickFaceError):
    """TOML schema validation failed or required field missing."""

    exit_code = 2


class CliArgError(PickFaceError):
    """CLI argument combination is invalid."""

    exit_code = 2


class SourceNotFoundError(PickFaceError):
    """A --src path does not exist or is not readable."""

    exit_code = 2


class OutputNotWritableError(PickFaceError):
    """--out path is not writable."""

    exit_code = 2


class CommercialLicenseError(PickFaceError):
    """AC-9: buffalo_* model used with accept_noncommercial_model_license=false.

    See docs/11 §3.2.
    """

    exit_code = 2


# -------------------- Model / runtime errors (exit 3) --------------------


class ModelLoadError(PickFaceError):
    """InsightFace model session failed to load (model missing/corrupt/EP fail)."""

    exit_code = 3


class ModelNotFoundError(ModelLoadError):
    """No model found in model_dir and no network to download."""

    exit_code = 3


# -------------------- Pipeline errors (exit 4) --------------------


class PipelineFailureError(PickFaceError):
    """Critical stage failure rate > 50% (detect/embed/cluster)."""

    exit_code = 4


# -------------------- Interruption (exit 5) --------------------


class InterruptedError(PickFaceError):
    """SIGINT / SIGTERM received mid-run. Re-running the same command resumes."""

    exit_code = 5


# -------------------- Image / pipeline (exit 1, recoverable) --------------------


class ImageDecodeError(PickFaceError):
    """Single image failed to decode. Caller may skip and continue."""

    exit_code = 1


class FaceError(PickFaceError):
    """Detection/embedding failed on a single image. Carries (path, stage, cause)."""

    exit_code = 1

    def __init__(
        self,
        message: str = "",
        *,
        path: str = "",
        stage: str = "",
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.path = path
        self.stage = stage


# -------------------- CLI exit code constants --------------------

EXIT_OK = 0
EXIT_CONFIG = 2  # config / cli args / commercial license
EXIT_MODEL = 3  # model unavailable
EXIT_PIPELINE = 4  # critical stage failure
EXIT_INTERRUPTED = 5  # SIGINT/SIGTERM partial
