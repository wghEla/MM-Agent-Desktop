"""Anthropic Messages 协议适配器（v0.3.0）。

请求形状：
- POST {base_url}/v1/messages
- headers: x-api-key + anthropic-version
- system 单独字段；messages 只含 user/assistant
- 工具：assistant content 的 tool_use 块 + role=user 的 tool_result 块
- thinking：预算制（budget_tokens），与低/中/高 effort 的映射由角色路由层决定
"""
from __future__ import annotations

from typing import Any

import httpx

from mmagent.agent.errors import ErrorKind, ProviderError, RateLimitError
from mmagent.providers._http_util import parse_retry_after
from mmagent.providers.base import BaseProvider
from mmagent.providers.capabilities import CapabilitySet
from mmagent.providers.normalized import (
    NormalizedMessage,
    NormalizedResponse,
    NormalizedTool,
    NormalizedToolCall,
    StopReason,
    TextPart,
    Usage,
)

# anthropic-version：当前官方稳定版；可按渠道覆盖（构造参数 api_version）
_ANTHROPIC_VERSION = "2023-06-01"


def build_messages_payload(
    messages: list[NormalizedMessage],
    tools: list[NormalizedTool],
    *,
    model: str,
    max_output_tokens: int | None,
) -> dict[str, Any]:
    system_text = ""
    api_messages: list[dict[str, Any]] = []
    for m in messages:
        text = "".join(p.text for p in m.content if isinstance(p, TextPart))
        if m.role == "system":
            system_text = (system_text + "\n" + text).strip()
            continue
        if m.role == "tool":
            api_messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id,
                    "content": text,
                }],
            })
            continue
        if m.role == "assistant" and m.tool_calls:
            content: list[dict[str, Any]] = []
            if text:
                content.append({"type": "text", "text": text})
            for tc in m.tool_calls:
                import json

                args = json.loads(tc.arguments_json) if tc.arguments_json else {}
                content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": args})
            api_messages.append({"role": "assistant", "content": content})
            continue
        api_messages.append({"role": "user" if m.role == "user" else "assistant",
                             "content": [{"type": "text", "text": text}]})
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_output_tokens or 8192,
        "messages": api_messages,
    }
    if system_text:
        payload["system"] = system_text
    if tools:
        payload["tools"] = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]
    return payload


def parse_messages_response(data: dict[str, Any], protocol: str = "anthropic_messages") -> NormalizedResponse:
    content = data.get("content") or []
    text_parts: list[str] = []
    tool_calls: list[NormalizedToolCall] = []
    for block in content:
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text") or "")
        elif btype == "tool_use":
            import json

            tool_calls.append(NormalizedToolCall(
                id=block.get("id") or "",
                name=block.get("name") or "",
                arguments_json=json.dumps(block.get("input") or {}, ensure_ascii=False),
            ))
    known = {
        "end_turn": StopReason.END_TURN,
        "stop_sequence": StopReason.END_TURN,
        "tool_use": StopReason.TOOL_CALLS,
        "max_tokens": StopReason.MAX_TOKENS,
        "pause_turn": StopReason.END_TURN,
        "refusal": StopReason.END_TURN,
    }
    if data.get("stop_reason") not in known:
        raise ProviderError(
            f"messages 未知 stop_reason: {data.get('stop_reason')!r}",
            kind=ErrorKind.PROVIDER_PROTOCOL,
        )
    stop = known[data["stop_reason"]]
    usage_d = data.get("usage") or {}
    return NormalizedResponse(
        message=NormalizedMessage(role="assistant", content=[TextPart(text="".join(text_parts))],
                                  tool_calls=tool_calls),
        stop_reason=stop,
        usage=Usage(
            input_tokens=int(usage_d.get("input_tokens") or 0),
            output_tokens=int(usage_d.get("output_tokens") or 0),
        ),
        model=data.get("model") or "",
        provider_protocol=protocol,
        raw=data,
    )


class AnthropicMessagesProvider(BaseProvider):
    protocol = "anthropic_messages"

    def __init__(self, base_url: str, api_key_getter, *, client: httpx.AsyncClient | None = None,
                 api_version: str = _ANTHROPIC_VERSION):
        self.base_url = base_url.rstrip("/")
        self._key_getter = api_key_getter
        self._client = client or httpx.AsyncClient(timeout=600.0)
        self._api_version = api_version

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            protocol=self.protocol,
            tool_calling=True,
            image_input=False,  # 图片输入未实现（v0.4）
            streaming=False,  # v0.3.x：SSE 流式解析落地后启用
            reasoning_levels=frozenset(),  # thinking 预算映射未实现（v0.4；诚实声明空集）
        )

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._key_getter(),
            "anthropic-version": self._api_version,
        }

    async def generate(
        self,
        messages: list[NormalizedMessage],
        tools: list[NormalizedTool],
        *,
        model: str,
        reasoning: str | None = None,
        max_output_tokens: int | None = None,
        timeout_s: float = 300.0,
    ) -> NormalizedResponse:
        payload = build_messages_payload(messages, tools, model=model, max_output_tokens=max_output_tokens)
        url = f"{self.base_url}/v1/messages"
        try:
            resp = await self._client.post(url, json=payload, headers=self._headers(), timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise ProviderError(f"messages 超时: {e}", kind=ErrorKind.PROVIDER_NETWORK, retryable=True) from e
        except httpx.HTTPError as e:
            raise ProviderError(f"messages 网络错误: {e}", kind=ErrorKind.PROVIDER_NETWORK, retryable=True) from e
        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            raise RateLimitError("429 rate limited", retry_after_s=parse_retry_after(retry_after))
        if resp.status_code in (401, 403):
            raise ProviderError(f"鉴权失败 {resp.status_code}", kind=ErrorKind.PROVIDER_AUTH)
        if resp.status_code >= 500:
            raise ProviderError(f"服务端错误 {resp.status_code}", kind=ErrorKind.PROVIDER_SERVER, retryable=True)
        if resp.status_code >= 400:
            raise ProviderError(f"请求错误 {resp.status_code}: {resp.text[:300]}",
                                kind=ErrorKind.PROVIDER_BAD_REQUEST)
        return parse_messages_response(resp.json(), self.protocol)

    async def test_connection(self) -> dict:
        # Anthropic 无 models 列表端点：以 1-token 消息探测
        try:
            resp = await self._client.post(
                f"{self.base_url}/v1/messages",
                json={"model": "claude-3-5-haiku-20241022", "max_tokens": 1,
                      "messages": [{"role": "user", "content": "ping"}]},
                headers=self._headers(), timeout=20.0,
            )
            # 4xx（除 401/403/429/429 类）也算连通（端点可达、鉴权语义可辨）
            ok = resp.status_code == 200
            return {"ok": ok, "detail": f"messages 探测 {resp.status_code}"}
        except httpx.HTTPError as e:
            return {"ok": False, "detail": str(e)[:200]}
