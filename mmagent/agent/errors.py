"""typed errors — 全部可归类的失败从这里出发。

设计原则（总方案 §34）：LLM 输出不可信；失败必须区分
FAILED / BLOCKED / CANCELLED / SUCCEEDED / DEFERRED，
错误类型是 Runtime 判定的依据，不是给模型的提示。
"""
from __future__ import annotations

import enum


class ErrorKind(enum.StrEnum):
    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    PROVIDER_AUTH = "provider_auth"
    PROVIDER_SERVER = "provider_server"
    PROVIDER_NETWORK = "provider_network"
    PROVIDER_BAD_REQUEST = "provider_bad_request"
    PROVIDER_CANCELLED = "provider_cancelled"
    PERMISSION_DENIED = "permission_denied"
    PATH_ESCAPE = "path_escape"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_FAILED = "tool_failed"
    ARTIFACT_INVALID = "artifact_invalid"
    ARTIFACT_MISSING = "artifact_missing"
    STATE_TRANSITION = "state_transition"
    BUDGET_EXHAUSTED = "budget_exhausted"
    RUN_LOCKED = "run_locked"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


class MMAgentError(Exception):
    """所有 mmagent 异常的基类。kind 决定 Runtime 的处置（重试/熔断/取消）。"""

    kind: ErrorKind = ErrorKind.INTERNAL
    retryable: bool = False

    def __init__(self, message: str = "", *, detail: dict | None = None):
        super().__init__(message)
        self.detail = detail or {}


class ProviderError(MMAgentError):
    def __init__(
        self,
        message: str,
        *,
        kind: ErrorKind = ErrorKind.PROVIDER_SERVER,
        retryable: bool = False,
        retry_after_s: float | None = None,
        detail: dict | None = None,
    ):
        super().__init__(message, detail=detail)
        self.kind = kind
        self.retryable = retryable
        self.retry_after_s = retry_after_s


class RateLimitError(ProviderError):
    """429 类：不是任务失败，Runtime 应降并发并按 retry_after 重试。"""

    def __init__(self, message: str = "rate limited", *, retry_after_s: float | None = None):
        super().__init__(message, kind=ErrorKind.PROVIDER_RATE_LIMIT, retryable=True, retry_after_s=retry_after_s)


class PermissionDenied(MMAgentError):
    kind = ErrorKind.PERMISSION_DENIED


class PathEscape(PermissionDenied):
    kind = ErrorKind.PATH_ESCAPE


class ToolTimeout(MMAgentError):
    kind = ErrorKind.TOOL_TIMEOUT


class ArtifactInvalid(MMAgentError):
    kind = ErrorKind.ARTIFACT_INVALID


class ArtifactMissing(MMAgentError):
    kind = ErrorKind.ARTIFACT_MISSING


class BudgetExhausted(MMAgentError):
    kind = ErrorKind.BUDGET_EXHAUSTED


class RunLocked(MMAgentError):
    kind = ErrorKind.RUN_LOCKED


class TaskCancelled(MMAgentError):
    kind = ErrorKind.CANCELLED


class TaskNotRunnable(MMAgentError):
    """任务当前状态不允许启动执行（终态/暂停态不得被隐式复活，外审 P1-2）。"""

    kind = ErrorKind.STATE_TRANSITION


class AttemptsExhausted(MMAgentError):
    kind = ErrorKind.BUDGET_EXHAUSTED


class TaskLeaseHeld(MMAgentError):
    """任务执行租约被其他持有者占用（外审 P1-1）。"""

    kind = ErrorKind.STATE_TRANSITION
