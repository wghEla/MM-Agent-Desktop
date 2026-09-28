"""OpenAI-Compatible 协议适配器（第三方 OpenAI 兼容渠道）。

与 openai_chat 的差异：base_url/路径/额外头可配置（如 /v1/hf-inference、
one-api/new-api 聚合渠道、vLLM/Ollama 等）。默认复用 OpenAI Chat 的
payload/解析逻辑；子类只覆盖 protocol 名与可选头。
"""
from __future__ import annotations

import httpx

from mmagent.agent.errors import ErrorKind, ProviderError, RateLimitError
from mmagent.providers import redact_secret
from mmagent.providers._http_util import parse_retry_after
from mmagent.providers.base import BaseProvider
from mmagent.providers.capabilities import CapabilitySet
from mmagent.providers.normalized import (
    NormalizedMessage,
    NormalizedResponse,
    NormalizedTool,
    TextPart,
)
from mmagent.providers.openai_chat import (
    build_chat_payload,
    parse_chat_response,
)


class OpenAICompatibleProvider(BaseProvider):
    """通用 OpenAI 兼容协议适配器。

    - completions_path：默认 /chat/completions，可按渠道覆盖；
    - supports_models_endpoint：部分聚合渠道没有 /models；
    - 鉴权头样式可选 bearer / x-api-key。
    """

    protocol = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        api_key_getter,
        *,
        completions_path: str = "/chat/completions",
        models_path: str | None = "/models",
        auth_style: str = "bearer",  # bearer | x-api-key | none
        client: httpx.AsyncClient | None = None,
        extra_headers: dict[str, str] | None = None,
        image_input: bool = False,
        reasoning_effort: bool = False,
        test_model: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.completions_path = completions_path
        self.models_path = (
            None
            if models_path is None or not str(models_path).strip()
            else (
                str(models_path).strip()
                if str(models_path).strip().startswith("/")
                else "/" + str(models_path).strip()
            )
        )
        self.auth_style = auth_style
        self._key_getter = api_key_getter
        self._client = client or httpx.AsyncClient(timeout=600.0)
        self._extra_headers = extra_headers or {}
        self._image_input = bool(image_input)
        self._reasoning_effort = bool(reasoning_effort)
        self._test_model = (test_model or "").strip()

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            protocol=self.protocol,
            tool_calling=True,
            image_input=self._image_input,  # 默认保守关闭；profile 可显式声明
            streaming=False,    # v0.3.x 引入流式后按渠道探测
            reasoning_levels=(
                frozenset({"low", "medium", "high"})
                if self._reasoning_effort
                else frozenset()
            ),
        )

    def _headers(self) -> dict[str, str]:
        headers = dict(self._extra_headers)
        key = self._key_getter()
        if key:
            if self.auth_style == "bearer":
                headers["Authorization"] = f"Bearer {key}"
            elif self.auth_style == "x-api-key":
                headers["x-api-key"] = key
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
        payload = build_chat_payload(
            messages,
            tools,
            model=model,
            reasoning=reasoning if self._reasoning_effort else None,
            max_output_tokens=max_output_tokens,
            stream=False,
        )
        url = f"{self.base_url}{self.completions_path}"
        try:
            resp = await self._client.post(url, json=payload, headers=self._headers(), timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise ProviderError(f"completions 超时: {e}", kind=ErrorKind.PROVIDER_NETWORK, retryable=True) from e
        except httpx.HTTPError as e:
            raise ProviderError(f"completions 网络错误: {e}", kind=ErrorKind.PROVIDER_NETWORK, retryable=True) from e
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
        return parse_chat_response(resp.json(), self.protocol)

    async def test_connection(self) -> dict:
        if self.models_path is None:
            models_detail = "models 端点已禁用"
        else:
            try:
                resp = await self._client.get(
                    f"{self.base_url}{self.models_path}",
                    headers=self._headers(),
                    timeout=15.0,
                )
                if resp.status_code == 200:
                    return {
                        "ok": True,
                        "detail": f"models 端点 200 ({self.models_path})",
                    }
                models_detail = (
                    f"models 端点 {resp.status_code} ({self.models_path})"
                )
            except httpx.HTTPError as exc:
                models_detail = f"models 探测失败: {str(exc)[:120]}"

        # Many otherwise valid OpenAI-compatible relays do not implement
        # /models.  Fall back to the actual configured chat path/model rather
        # than reporting a false negative.  This is a real, minimal API call.
        if not self._test_model:
            return {
                "ok": False,
                "detail": f"{models_detail}; 未配置 test_model，无法执行 chat fallback",
            }
        try:
            await self.generate(
                [
                    NormalizedMessage(
                        role="user",
                        content=[TextPart(text="Reply with OK.")],
                    )
                ],
                [],
                model=self._test_model,
                reasoning=None,
                max_output_tokens=1,
                timeout_s=15.0,
            )
            return {
                "ok": True,
                "detail": f"{models_detail}; chat fallback 成功",
            }
        except ProviderError as exc:
            return {
                "ok": False,
                "detail": f"{models_detail}; chat fallback 失败: {str(exc)[:160]}",
            }
        except httpx.HTTPError as exc:
            return {
                "ok": False,
                "detail": f"{models_detail}; chat fallback 网络失败: {str(exc)[:160]}",
            }
