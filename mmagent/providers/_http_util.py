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


def openai_style_model_ids(payload: object) -> set[str]:
    """Extract model ids from the common {"data":[{"id": ...}]} shape."""
    if not isinstance(payload, dict):
        return set()
    rows = payload.get("data")
    if not isinstance(rows, list):
        return set()
    return {
        value
        for row in rows
        if isinstance(row, dict)
        for value in [row.get("id")]
        if isinstance(value, str) and value
    }


def gemini_model_ids(payload: object) -> set[str]:
    """Extract generateContent-capable Gemini model ids without the models/ prefix."""
    if not isinstance(payload, dict):
        return set()
    rows = payload.get("models")
    if not isinstance(rows, list):
        return set()
    values: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        methods = row.get("supportedGenerationMethods")
        if isinstance(methods, list) and "generateContent" not in methods:
            continue
        name = row.get("name")
        if isinstance(name, str) and name:
            values.add(name.removeprefix("models/"))
    return values


def configured_model_detail(
    configured: str | None,
    available: set[str],
    *,
    endpoint_label: str,
) -> dict[str, object]:
    """Turn a successful model-list response into a configured-model verdict."""
    model = (configured or "").strip()
    if not model:
        return {"ok": True, "detail": f"{endpoint_label}; 未配置模型，未校验 Model ID"}
    if model in available:
        return {"ok": True, "detail": f"{endpoint_label}; 已确认模型 {model}"}
    if available:
        return {
            "ok": False,
            "detail": f"{endpoint_label}; 配置模型不存在或当前账户不可用: {model}",
        }
    return {
        "ok": False,
        "detail": f"{endpoint_label}; 未能从响应识别模型，无法确认 {model}",
    }
