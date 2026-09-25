"""Gemini generateContent 协议适配器（v0.3.0）。

请求形状：
- POST {base_url}/v1beta/models/{model}:generateContent（x-goog-api-key 头）
- contents: [{role: user|model, parts: [{text}]}]；functionCall / functionResponse parts
- tools: [{functionDeclarations: [{name, description, parameters}]}]
- systemInstruction 单独字段
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from mmagent.agent.errors import ErrorKind, ProviderError, RateLimitError
from mmagent.providers._http_util import parse_retry_after
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


def build_generate_payload(
    messages: list[NormalizedMessage],
    tools: list[NormalizedTool],
    *,
    system_text: str | None = None,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    contents: list[dict[str, Any]] = []
    system_parts: list[str] = []
    for m in messages:
        text = "".join(p.text for p in m.content if isinstance(p, TextPart))
        if m.role == "system":
            system_parts.append(text)
            continue
        if m.role == "tool":
            contents.append({
                "role": "user",
                "parts": [{"functionResponse": {"name": m.name or "", "response": {"result": text}}}],
            })
            continue
        role = "model" if m.role == "assistant" else "user"
        parts: list[dict[str, Any]] = []
        if text:
            parts.append({"text": text})
        if m.role == "user":
            for image in m.content:
                if isinstance(image, ImagePart):
                    parts.append({
                        "inlineData": {
                            "mimeType": image.media_type,
                            "data": image.b64,
                        }
                    })
        if m.role == "assistant" and m.tool_calls:
            import json

            for tc in m.tool_calls:
                parts.append({"functionCall": {
                    "name": tc.name,
                    "args": json.loads(tc.arguments_json) if tc.arguments_json else {},
                }})
        contents.append({"role": role, "parts": parts})
    payload: dict[str, Any] = {"contents": contents}
    if system_parts or system_text:
        payload["systemInstruction"] = {"parts": [{"text": "\n".join(filter(None, [system_text or "", *system_parts]))}]}
    if max_output_tokens is not None:
        # round9：max_output_tokens 必须真实映射 generationConfig（不得静默丢弃）
        payload["generationConfig"] = {"maxOutputTokens": max_output_tokens}
    if tools:
        payload["tools"] = [{
            "functionDeclarations": [
                {"name": t.name, "description": t.description, "parameters": t.parameters}
                for t in tools
            ]
        }]
    return payload


def parse_generate_response(data: dict[str, Any], protocol: str = "gemini") -> NormalizedResponse:
    candidates = data.get("candidates") or []
    if not candidates:
        block = data.get("promptFeedback", {}).get("blockReason")
        raise ProviderError(
            f"generateContent 无 candidates（block={block}）",
            kind=ErrorKind.PROVIDER_BAD_REQUEST,
        )
    cand = candidates[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text_parts: list[str] = []
    tool_calls: list[NormalizedToolCall] = []
    for part in parts:
        if "text" in part:
            text_parts.append(part["text"])
        elif "functionCall" in part:
            fc = part["functionCall"]
            # 优先官方 id 字段；legacy 无 id 时以 name 兜底（functionResponse 按 name 回填）
            tool_calls.append(NormalizedToolCall(
                id=fc.get("id") or fc.get("name") or "",
                name=fc.get("name") or "",
                arguments_json=json.dumps(fc.get("args") or {}, ensure_ascii=False),
            ))
    finish = cand.get("finishReason")
    known = {
        "STOP": StopReason.END_TURN,
        "MAX_TOKENS": StopReason.MAX_TOKENS,
        "SAFETY": StopReason.END_TURN,
        "RECITATION": StopReason.END_TURN,
    }
    if finish not in known:
        raise ProviderError(
            f"generateContent 未知 finishReason: {finish!r}",
            kind=ErrorKind.PROVIDER_PROTOCOL,
        )
    stop = known[finish]
    usage_d = data.get("usageMetadata") or {}
    return NormalizedResponse(
        message=NormalizedMessage(role="assistant", content=[TextPart(text="".join(text_parts))],
                                  tool_calls=tool_calls),
        stop_reason=stop,
        usage=Usage(
            input_tokens=int(usage_d.get("promptTokenCount") or 0),
            output_tokens=int(usage_d.get("candidatesTokenCount") or 0),
        ),
        model=data.get("modelVersion") or "",
        provider_protocol=protocol,
        raw=data,
    )


class GeminiProvider(BaseProvider):
    protocol = "gemini"

    def __init__(self, base_url: str, api_key_getter, *, client: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self._key_getter = api_key_getter
        self._client = client or httpx.AsyncClient(timeout=600.0)

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            protocol=self.protocol,
            tool_calling=True,
            image_input=True,
            streaming=False,  # v0.3.x：SSE 流式解析落地后启用
            reasoning_levels=frozenset(),
        )

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._key_getter()}

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
        system_text = ""
        if messages and messages[0].role == "system":
            system_text = messages[0].text
            messages = messages[1:]
        payload = build_generate_payload(messages, tools, system_text=system_text or None,
                                         max_output_tokens=max_output_tokens)
        url = f"{self.base_url}/v1beta/models/{model}:generateContent"
        try:
            resp = await self._client.post(url, json=payload, headers=self._headers(), timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise ProviderError(f"generateContent 超时: {e}", kind=ErrorKind.PROVIDER_NETWORK, retryable=True) from e
        except httpx.HTTPError as e:
            raise ProviderError(f"generateContent 网络错误: {e}", kind=ErrorKind.PROVIDER_NETWORK, retryable=True) from e
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
        return parse_generate_response(resp.json(), self.protocol)

    async def test_connection(self) -> dict:
        try:
            resp = await self._client.get(
                f"{self.base_url}/v1beta/models", headers=self._headers(), timeout=15.0,
            )
            return {"ok": resp.status_code == 200, "detail": f"models 端点 {resp.status_code}"}
        except httpx.HTTPError as e:
            return {"ok": False, "detail": str(e)[:200]}
