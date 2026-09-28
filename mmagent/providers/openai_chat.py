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
from mmagent.providers import redact_secret
from mmagent.providers._http_util import (
    configured_model_detail,
    openai_style_model_ids,
    parse_retry_after,
)
from mmagent.providers.base import BaseProvider
from mmagent.providers.capabilities import CapabilitySet
from mmagent.providers.normalized import (
    ImagePart,
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

    images = [p for p in m.content if isinstance(p, ImagePart)]
    if images:
        content: str | list[dict[str, Any]] = []
        if text:
            content.append({"type": "text", "text": text})
        for image in images:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{image.media_type};base64,{image.b64}",
                },
            })
    else:
        content = text
    out: dict[str, Any] = {"role": m.role, "content": content}
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
        raise ProviderError("chat.completions 响应缺少 choices", kind=ErrorKind.PROVIDER_PROTOCOL)
    ch = choices[0]
    msg = ch.get("message") or {}
    tool_calls = [
        NormalizedToolCall(id=tc.get("id", ""), name=tc.get("function", {}).get("name", ""),
                           arguments_json=tc.get("function", {}).get("arguments") or "{}")
        for tc in (msg.get("tool_calls") or [])
    ]
    finish = ch.get("finish_reason")
    known = {
        "tool_calls": StopReason.TOOL_CALLS,
        "length": StopReason.MAX_TOKENS,
        "stop": StopReason.END_TURN,
        "function_call": StopReason.TOOL_CALLS,
    }
    if finish not in known:
        # 未知 finish_reason 不得默认 END_TURN（外审 round1 K3 fail-open）
        raise ProviderError(
            f"chat 未知 finish_reason: {finish!r}",
            kind=ErrorKind.PROVIDER_PROTOCOL,
        )
    stop = known[finish]
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
        test_model: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._key = api_key_getter()  # 初始化时取一次（脱敏 + 头部共用）
        self._key_getter = lambda: self._key
        self._client = client or httpx.AsyncClient(timeout=600.0)
        self._extra_headers = extra_headers or {}
        # Test Connection 的 /models 404 回退用：用 profile 配置的真实模型探测
        self._test_model = test_model

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
        # keyless profiles (e.g. local relays) must not send an empty
        # Authorization value — httpx rejects it outright.
        key = self._key_getter()
        headers = dict(self._extra_headers)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

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
                retry_after_s=parse_retry_after(retry_after),
            )
        if resp.status_code in (401, 403):
            raise ProviderError(f"鉴权失败 {resp.status_code}", kind=ErrorKind.PROVIDER_AUTH)
        if resp.status_code >= 500:
            raise ProviderError(f"服务端错误 {resp.status_code}", kind=ErrorKind.PROVIDER_SERVER, retryable=True)
        if resp.status_code >= 400:
            detail = redact_secret(resp.text[:300], self._key)
            raise ProviderError(f"请求错误 {resp.status_code}: {detail}",
                                kind=ErrorKind.PROVIDER_BAD_REQUEST)
        try:
            data = resp.json()
        except Exception as e:
            raise ProviderError(f"chat 响应不是合法 JSON: {e}",
                                kind=ErrorKind.PROVIDER_PROTOCOL) from e
        return parse_chat_response(data, self.protocol)

    async def test_connection(self) -> dict:
        # 无 key/模型列表端点依赖：以最小 models 请求探测（兼容 OpenAI 语义）
        try:
            resp = await self._client.get(f"{self.base_url}/models", headers=self._headers(), timeout=15.0)
            if resp.status_code == 200:
                try:
                    available = openai_style_model_ids(resp.json())
                except Exception:
                    available = set()
                return configured_model_detail(
                    self._test_model,
                    available,
                    endpoint_label="models 端点 200",
                )
            models_detail = f"models 端点 {resp.status_code}"
        except httpx.HTTPError as e:
            models_detail = f"models 探测失败: {str(e)[:120]}"

        # 许多真实 OpenAI 兼容中转（one-api/new-api/部分 vLLM/Ollama 网关）
        # 没有 /models 端点但 chat 可用。回退到用配置的模型做一次真实最小
        # chat 请求（max_tokens=1），避免把可用渠道误报为不可用。这是真实
        # API 调用，可能消耗极少量 token——与 openai_compatible 的行为一致。
        try:
            await self.generate(
                [NormalizedMessage(role="user", content=[TextPart(text="Reply with OK.")])],
                [],
                model=self._test_model or "default",
                reasoning=None,
                max_output_tokens=1,
                timeout_s=15.0,
            )
            return {"ok": True, "detail": f"{models_detail}; chat fallback 成功"}
        except httpx.HTTPError as e:
            return {"ok": False, "detail": f"{models_detail}; chat fallback 网络失败: {str(e)[:160]}"}
        except Exception as e:
            return {"ok": False, "detail": f"{models_detail}; chat fallback 失败: {str(e)[:160]}"}
