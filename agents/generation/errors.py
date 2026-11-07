"""错误码与异常（对齐 API v1.0 §1.3）。

原则：模块内部只抛 AppError 子类，HTTP 层统一包成
{"code": ..., "msg": ..., "data": null, "trace_id": ...}，且 HTTP 状态恒为 200。
"""

from __future__ import annotations

from enum import IntEnum


class ErrorCode(IntEnum):
    OK = 0

    # 1xxx 参数/资源层，不可重试
    MISSING_PARAM = 1001
    INVALID_PARAM = 1002
    NOT_FOUND = 1003
    FILE_TOO_LARGE = 1004
    UNAUTHORIZED = 1005
    UNSUPPORTED_FILE = 1006

    # 2xxx 系统层，可重试
    MODEL_FAILED = 2001
    TIMEOUT = 2002
    RATE_LIMITED = 2003
    UNAVAILABLE = 2004

    # 3xxx 业务结论 / 阶段失败
    OCR_EMPTY = 3001
    ASR_SILENT = 3002
    OUT_OF_SCOPE = 3003
    SAFETY_BLOCKED = 3004
    JOB_NOT_FOUND = 3005
    JOB_TERMINAL = 3006
    VIDEO_FAILED = 3007
    TTS_FAILED = 3008

    UNEXPECTED = 9001


#: §1.13 重试白名单：仅这些码可重试
RETRYABLE: frozenset[ErrorCode] = frozenset(
    {
        ErrorCode.MODEL_FAILED,
        ErrorCode.TIMEOUT,
        ErrorCode.RATE_LIMITED,
        ErrorCode.UNAVAILABLE,
        ErrorCode.VIDEO_FAILED,
        ErrorCode.TTS_FAILED,
    }
)


class AppError(Exception):
    """带契约错误码的异常。msg 会原样进响应体，所以必须是给人看的中文短句。"""

    def __init__(self, code: ErrorCode, msg: str, *, detail: str | None = None):
        super().__init__(msg)
        self.code = code
        self.msg = msg
        self.detail = detail

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE

    def envelope(self, trace_id: str) -> dict:
        return {"code": int(self.code), "msg": self.msg, "data": None, "trace_id": trace_id}

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"AppError(code={int(self.code)}, msg={self.msg!r}, detail={self.detail!r})"


class StoryError(AppError):
    """故事生成失败（对应页面 failed，任务按聚合规则处理）。"""

    def __init__(
        self,
        msg: str = "故事生成失败",
        code: ErrorCode = ErrorCode.MODEL_FAILED,
        detail: str | None = None,
    ):
        super().__init__(code, msg, detail=detail)


class StoryInputError(StoryError):
    """OCR 与 VLM 都没有可用输入：按业务结论处理，不重试。"""

    def __init__(self, msg: str = "没有识别到可用的文字或画面", detail: str | None = None):
        super().__init__(msg, code=ErrorCode.OCR_EMPTY, detail=detail)


class TTSUnavailable(AppError):
    """TTS 服务/引擎不可用（2004）。"""

    def __init__(self, msg: str = "TTS 服务不可用", detail: str | None = None):
        super().__init__(ErrorCode.UNAVAILABLE, msg, detail=detail)


class TTSFailed(AppError):
    """合成执行失败（3008，可重试）。"""

    def __init__(self, msg: str = "语音合成失败", detail: str | None = None):
        super().__init__(ErrorCode.TTS_FAILED, msg, detail=detail)


class VideoError(AppError):
    """视频合成失败（3007，可重试）。"""

    def __init__(self, msg: str = "视频生成失败", detail: str | None = None):
        super().__init__(ErrorCode.VIDEO_FAILED, msg, detail=detail)


class ContractError(AppError):
    """产物不满足 Schema —— 属于我们自己的 bug，不当作业务错误重试。"""

    def __init__(self, msg: str, detail: str | None = None):
        super().__init__(ErrorCode.UNEXPECTED, msg, detail=detail)
