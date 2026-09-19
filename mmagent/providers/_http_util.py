"""Provider 共享 HTTP 工具（外审 v0.3.0 修复）。"""
from __future__ import annotations

import time


def parse_retry_after(value: str | None) -> float | None:
    """Retry-After 解析：delta-seconds 或 HTTP-date；畸形返回 None（绝不抛异常）。"""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        import email.utils as _eu

        dt = _eu.parsedate_to_datetime(value)
        if dt is not None:
            delta = dt.timestamp() - time.time()
            return max(0.0, delta)
    except Exception:
        pass
    return None


def safe_json(data: bytes | str, *, context: str, secrets: tuple[str, ...] = ()) -> dict:
    """2xx 响应体 JSON 解析；失败抛 ProviderError（协议错误，含脱敏片段）。"""
    import json

    from mmagent.agent.errors import ErrorKind, ProviderError

    try:
        parsed = json.loads(data if isinstance(data, (str, bytes)) else data.decode("utf-8"))
    except Exception as e:
        snippet = (data if isinstance(data, str) else data.decode("utf-8", errors="replace"))[:200]
        snippet = _redact_all(snippet, secrets)
        raise ProviderError(
            f"{context}: 响应不是合法 JSON: {e} 片段={snippet!r}",
            kind=ErrorKind.PROVIDER_PROTOCOL,
        ) from e
    if not isinstance(parsed, dict):
        raise ProviderError(
            f"{context}: 响应 JSON 顶层不是对象",
            kind=ErrorKind.PROVIDER_PROTOCOL,
        )
    return parsed


def redacted(text: str, secrets: tuple[str, ...]) -> str:
    return _redact_all(text, secrets)


def _redact_all(text: str, secrets: tuple[str, ...]) -> str:
    out = text
    for sec in secrets:
        if sec:
            out = out.replace(sec, "***REDACTED***")
    return out


# ProviderErrorKind 别名（避免循环导入的兼容出口）
