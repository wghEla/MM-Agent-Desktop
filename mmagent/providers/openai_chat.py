"""OpenAI Chat Completions 协议适配器（v0.3.0）。

请求形状（offline contract-tested，无真实 key 时标注 unverified-real）：
- POST {base_url}/chat/completions
- messages: system/user/assistant/tool；assistant.tool_calls + role=tool 消息回填
- tools: [{type: function, function: {name, description, parameters}}]
- tool_choice: auto（有工具时）
- reasoning 档位：以 reasoning_effort 传递（支持的模型族）；不支持时省略字段（不伪装）
错误归一：401→auth / 429→rate_limit(+Retry-After) / 5xx→server / 网络→network。
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from mmagent.agent.errors import (
    ErrorKind,
    ProviderError,
    RateLimitError,
)
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


def build_chat_payload(
    messages: list[NormalizedMessage],
    tools: list[NormalizedTool],
    *,
    model: str,
    reasoning: str | None,
    max_output_tokens: int | None,
    stream: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [_msg_to_chat(m) for m in messages],
        "stream": stream,
    }
    if max_output_tokens is not None:
        payload["max_tokens"] = max_output_tokens
    if tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]
        payload["tool_choice"] = "auto"
    if reasoning is not None:
        # 推理档位：仅当模型族支持时传递（能力声明由 CapabilitySet 负责）
        payload["reasoning_effort"] = reasoning
    return payload


def _msg_to_chat(m: NormalizedMessage) -> dict[str, Any]:
    text = "".join(p.text for p in m.content if isinstance(p, TextPart))
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": text}
    out: dict[str, Any] = {"role": m.role, "content": text}
    if m.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments_json},
            }
            for tc in m.tool_calls
        ]
    return out


def parse_chat_response(data: dict[str, Any], protocol: str = "openai_chat") -> NormalizedResponse:
    choices = data.get("choices") or []
    if not choices:
        raise ProviderError("chat.completions 响应缺少 choices", kind=ErrorKind.PROVIDER_BAD_REQUEST)
    ch = choices[0]
    msg = ch.get("message") or {}
    tool_calls = [
        NormalizedToolCall(id=tc.get("id", ""), name=tc.get("function", {}).get("name", ""),
                           arguments_json=tc.get("function", {}).get("arguments") or "{}")
        for tc in (msg.get("tool_calls") or [])
    ]
    finish = ch.get("finish_reason")
    stop = {
        "tool_calls": StopReason.TOOL_CALLS,
        "length": StopReason.MAX_TOKENS,
        "stop": StopReason.END_TURN,
    }.get(finish, StopReason.END_TURN)
    usage_d = data.get("usage") or {}
    content = [TextPart(text=msg.get("content") or "")]
    return NormalizedResponse(
        message=NormalizedMessage(role="assistant", content=content, tool_calls=tool_calls),
        stop_reason=stop,
        usage=Usage(
            input_tokens=int(usage_d.get("prompt_tokens") or 0),
            output_tokens=int(usage_d.get("completion_tokens") or 0),
        ),
        model=data.get("model") or "",
        provider_protocol=protocol,
        raw=data,
    )


class OpenAIChatProvider(BaseProvider):
    """OpenAI Chat Completions 兼容适配器（也是 openai_compatible 的基类）。

    api_key 通过 credential provider 回调获取（v0.3：注入函数；v0.3+ Credential Manager）。
    """

    protocol = "openai_chat"

    def __init__(
        self,
        base_url: str,
        api_key_getter,
        *,
        client: httpx.AsyncClient | None = None,
        extra_headers: dict[str, str] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._key_getter = api_key_getter
        self._client = client or httpx.AsyncClient(timeout=600.0)
        self._extra_headers = extra_headers or {}

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            protocol=self.protocol,
            tool_calling=True,
            image_input=True,
            streaming=False,  # v0.3.x：SSE 流式解析落地后启用
            reasoning_levels=frozenset({"low", "medium", "high"}),
            max_output_tokens_limit=None,
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key_getter()}", **self._extra_headers}

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
        payload = build_chat_payload(messages, tools, model=model, reasoning=reasoning,
                                     max_output_tokens=max_output_tokens, stream=False)
        url = f"{self.base_url}/chat/completions"
        t0 = time.monotonic()
        try:
            resp = await self._client.post(url, json=payload, headers=self._headers(), timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise ProviderError(f"chat 超时: {e}", kind=ErrorKind.PROVIDER_NETWORK, retryable=True) from e
        except httpx.HTTPError as e:
            raise ProviderError(f"chat 网络错误: {e}", kind=ErrorKind.PROVIDER_NETWORK, retryable=True) from e
        elapsed = time.monotonic() - t0
        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            raise RateLimitError(
                f"429 rate limited（elapsed={elapsed:.1f}s）",
                retry_after_s=float(retry_after) if retry_after else None,
            )
        if resp.status_code in (401, 403):
            raise ProviderError(f"鉴权失败 {resp.status_code}", kind=ErrorKind.PROVIDER_AUTH)
        if resp.status_code >= 500:
            raise ProviderError(f"服务端错误 {resp.status_code}", kind=ErrorKind.PROVIDER_SERVER, retryable=True)
        if resp.status_code >= 400:
            raise ProviderError(f"请求错误 {resp.status_code}: {resp.text[:300]}",
                                kind=ErrorKind.PROVIDER_BAD_REQUEST)
        return parse_chat_response(resp.json(), self.protocol)

    async def test_connection(self) -> dict:
        # 无 key/模型列表端点依赖：以最小 models 请求探测（兼容 OpenAI 语义）
        try:
            resp = await self._client.get(f"{self.base_url}/models", headers=self._headers(), timeout=15.0)
            return {"ok": resp.status_code == 200, "detail": f"models 端点 {resp.status_code}"}
        except httpx.HTTPError as e:
            return {"ok": False, "detail": str(e)[:200]}
