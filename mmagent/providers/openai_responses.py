"""OpenAI Responses 协议适配器（v0.3.0）。

请求形状：
- POST {base_url}/responses
- input: [{role, content:[{type: output_text/input_text}]}]；function_call / function_call_output
- tools: [{type: function, name, description, parameters}]
- reasoning: {effort: low|medium|high|xhigh}
"""
from __future__ import annotations

from typing import Any

import httpx

from mmagent.agent.errors import ErrorKind, ProviderError, RateLimitError
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


def build_responses_payload(
    messages: list[NormalizedMessage],
    tools: list[NormalizedTool],
    *,
    model: str,
    reasoning: str | None,
    max_output_tokens: int | None,
    continuation_items: list[dict] | None = None,
) -> dict[str, Any]:
    input_items: list[dict[str, Any]] = []
    for m in messages:
        text = "".join(p.text for p in m.content if isinstance(p, TextPart))
        if m.role == "system":
            input_items.append({"role": "system", "content": [{"type": "input_text", "text": text}]})
        elif m.role == "user":
            content: list[dict[str, Any]] = []
            if text:
                content.append({"type": "input_text", "text": text})
            for image in m.content:
                if isinstance(image, ImagePart):
                    content.append({
                        "type": "input_image",
                        "image_url": f"data:{image.media_type};base64,{image.b64}",
                    })
            input_items.append({"role": "user", "content": content})
        elif m.role == "tool":
            input_items.append({
                "type": "function_call_output",
                "call_id": m.tool_call_id,
                "output": text,
            })
        else:  # assistant
            if m.tool_calls:
                for tc in m.tool_calls:
                    input_items.append({
                        "type": "function_call",
                        "call_id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments_json,
                    })
            if text:
                input_items.append({"role": "assistant", "content": [{"type": "output_text", "text": text}]})
    if continuation_items:
        # OpenAI 手工状态管理建议：把上一轮 output items（含 reasoning items）
        # 一并回传，避免 reasoning model 多步工具调用的上下文丢失（round9 P1-4）。
        input_items = list(continuation_items) + input_items
    payload: dict[str, Any] = {"model": model, "input": input_items}
    if tools:
        payload["tools"] = [
            {"type": "function", "name": t.name, "description": t.description, "parameters": t.parameters}
            for t in tools
        ]
        payload["tool_choice"] = "auto"
    if reasoning is not None:
        payload["reasoning"] = {"effort": reasoning}
    if max_output_tokens is not None:
        payload["max_output_tokens"] = max_output_tokens
    return payload


def parse_responses_response(data: dict[str, Any], protocol: str = "openai_responses") -> NormalizedResponse:
    """从 output 数组提取 message 与 function_call 项。"""
    output = data.get("output") or []
    text_parts: list[str] = []
    tool_calls: list[NormalizedToolCall] = []
    for item in output:
        itype = item.get("type")
        if itype == "message":
            for c in item.get("content") or []:
                if c.get("type") in ("output_text", "text"):
                    text_parts.append(c.get("text") or "")
        elif itype == "function_call":
            tool_calls.append(
                NormalizedToolCall(id=item.get("call_id") or item.get("id") or "",
                                   name=item.get("name") or "",
                                   arguments_json=item.get("arguments") or "{}")
            )
    usage_d = data.get("usage") or {}
    status = data.get("status")
    if status not in ("completed", "incomplete"):
        raise ProviderError(
            f"responses 未知 status: {status!r}",
            kind=ErrorKind.PROVIDER_PROTOCOL,
        )
    stop = StopReason.MAX_TOKENS if status == "incomplete" else StopReason.END_TURN
    if tool_calls:
        stop = StopReason.TOOL_CALLS
    usage = Usage(
        input_tokens=int(usage_d.get("input_tokens") or 0),
        output_tokens=int(usage_d.get("output_tokens") or 0),
    )
    return NormalizedResponse(
        message=NormalizedMessage(role="assistant", content=[TextPart(text="".join(text_parts))],
                                  tool_calls=tool_calls),
        stop_reason=stop,
        usage=usage,
        model=data.get("model") or "",
        provider_protocol=protocol,
        raw=data,
    )


class OpenAIResponsesProvider(BaseProvider):
    protocol = "openai_responses"

    def __init__(
        self,
        base_url: str,
        api_key_getter,
        *,
        client: httpx.AsyncClient | None = None,
        test_model: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._key_getter = api_key_getter
        self._client = client or httpx.AsyncClient(timeout=600.0)
        self._test_model = (test_model or "").strip()

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            protocol=self.protocol,
            tool_calling=True,
            image_input=True,
            streaming=False,  # v0.3.x：SSE 流式解析落地后启用
            reasoning_levels=frozenset({"minimal", "low", "medium", "high"}),
        )

    def _headers(self) -> dict[str, str]:
        # keyless profiles must not send an empty Authorization value.
        key = self._key_getter()
        return {"Authorization": f"Bearer {key}"} if key else {}

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
        payload = build_responses_payload(messages, tools, model=model, reasoning=reasoning,
                                          max_output_tokens=max_output_tokens)
        url = f"{self.base_url}/responses"
        try:
            resp = await self._client.post(url, json=payload, headers=self._headers(), timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise ProviderError(f"responses 超时: {e}", kind=ErrorKind.PROVIDER_NETWORK, retryable=True) from e
        except httpx.HTTPError as e:
            raise ProviderError(f"responses 网络错误: {e}", kind=ErrorKind.PROVIDER_NETWORK, retryable=True) from e
        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            raise RateLimitError("429 rate limited", retry_after_s=parse_retry_after(retry_after))
        if resp.status_code in (401, 403):
            raise ProviderError(f"鉴权失败 {resp.status_code}", kind=ErrorKind.PROVIDER_AUTH)
        if resp.status_code >= 500:
            raise ProviderError(f"服务端错误 {resp.status_code}", kind=ErrorKind.PROVIDER_SERVER, retryable=True)
        if resp.status_code >= 400:
            detail = redact_secret(resp.text[:300], self._key_getter())
            raise ProviderError(
                f"请求错误 {resp.status_code}: {detail}",
                kind=ErrorKind.PROVIDER_BAD_REQUEST,
            )
        return parse_responses_response(resp.json(), self.protocol)

    async def test_connection(self) -> dict:
        try:
            resp = await self._client.get(
                f"{self.base_url}/models",
                headers=self._headers(),
                timeout=15.0,
            )
            if resp.status_code != 200:
                return {
                    "ok": False,
                    "detail": f"models 端点 {resp.status_code}",
                }
            try:
                available = openai_style_model_ids(resp.json())
            except Exception:
                available = set()
            return configured_model_detail(
                self._test_model,
                available,
                endpoint_label="models 端点 200",
            )
        except httpx.HTTPError as e:
            return {"ok": False, "detail": str(e)[:200]}
