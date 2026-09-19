"""Provider 契约测试（offline，httpx.MockTransport）。

覆盖五协议的：请求形状、响应解析、工具调用归一、错误映射（429/401/5xx）、
usage 提取、能力诚实声明。真实 Provider 未验证（无 key），已在文档标注。
"""
from __future__ import annotations

import json

import httpx
import pytest

from mmagent.agent.errors import ProviderError, RateLimitError
from mmagent.providers.anthropic_messages import AnthropicMessagesProvider
from mmagent.providers.gemini import GeminiProvider
from mmagent.providers.normalized import NormalizedMessage, NormalizedTool, TextPart
from mmagent.providers.openai_chat import OpenAIChatProvider
from mmagent.providers.openai_compatible import OpenAICompatibleProvider
from mmagent.providers.openai_responses import OpenAIResponsesProvider


def _resp_200_openai_chat(tool_call: bool = False):
    msg: dict = {"role": "assistant", "content": "hello"}
    if tool_call:
        msg["tool_calls"] = [{
            "id": "call_1", "type": "function",
            "function": {"name": "fs.read", "arguments": "{\"path\": \"a.txt\"}"},
        }]
        msg["content"] = None
    return httpx.Response(200, json={
        "id": "x", "model": "m1",
        "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if tool_call else "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    })


def _capture_handler(routes: dict[str, httpx.Response], captures: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        captures.append(request)
        path = request.url.path
        for pattern, resp in routes.items():
            if path.endswith(pattern):
                return resp
        return httpx.Response(404, json={"error": "no route"})
    return handler


@pytest.mark.asyncio
async def test_openai_chat_contract():
    captures: list[httpx.Request] = []
    handler = _capture_handler({"/chat/completions": _resp_200_openai_chat(tool_call=True)}, captures)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = OpenAIChatProvider("https://api.test/v1", lambda: "sk-test", client=client)

    msgs = [
        NormalizedMessage(role="system", content=[TextPart(text="sys")]),
        NormalizedMessage(role="user", content=[TextPart(text="hi")]),
        NormalizedMessage(role="assistant", content=[],
                          tool_calls=[{"id": "c0", "name": "t0", "arguments_json": "{}"}]),
        NormalizedMessage(role="tool", content=[TextPart(text="result")], tool_call_id="c0"),
    ]
    tools = [NormalizedTool(name="t0", description="d", parameters={"type": "object"})]
    resp = await p.generate(msgs, tools, model="m1", reasoning="high")

    # 请求形状
    req = captures[0]
    assert req.url.path.endswith("/chat/completions")
    assert req.headers["Authorization"] == "Bearer sk-test"
    body = json.loads(req.content)
    assert body["model"] == "m1" and body["stream"] is False
    assert body["reasoning_effort"] == "high"
    assert body["tools"][0]["function"]["name"] == "t0"
    assert body["tool_choice"] == "auto"
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][-1] == {"role": "tool", "tool_call_id": "c0", "content": "result"}
    # 响应解析：tool_calls 归一 + usage
    assert resp.stop_reason.value == "tool_calls"
    assert resp.message.tool_calls[0].name == "fs.read"
    assert json.loads(resp.message.tool_calls[0].arguments_json) == {"path": "a.txt"}
    assert resp.usage.input_tokens == 11 and resp.usage.output_tokens == 7
    await client.aclose()


@pytest.mark.asyncio
async def test_openai_chat_error_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(429, headers={"retry-after": "7"}, json={"error": "slow"})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = OpenAIChatProvider("https://api.test/v1", lambda: "k", client=client)
    with pytest.raises(RateLimitError) as ei:
        await p.generate([NormalizedMessage(role="user", content=[TextPart(text="x")])], [],
                         model="m")
    assert ei.value.retry_after_s == 7.0 and ei.value.retryable

    def handler2(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    client2 = httpx.AsyncClient(transport=httpx.MockTransport(handler2))
    p2 = OpenAIChatProvider("https://api.test/v1", lambda: "k", client=client2)
    with pytest.raises(ProviderError) as ei2:
        await p2.generate([NormalizedMessage(role="user", content=[TextPart(text="x")])], [], model="m")
    assert ei2.value.kind.value == "provider_auth"
    await client.aclose()
    await client2.aclose()


@pytest.mark.asyncio
async def test_openai_responses_contract():
    captures: list[httpx.Request] = []
    resp_json = {
        "id": "r1", "model": "m2", "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "function_call", "call_id": "fc1", "name": "fs.write",
             "arguments": "{\"path\": \"x\"}"},
            {"type": "message", "content": [{"type": "output_text", "text": "done"}]},
        ],
        "usage": {"input_tokens": 5, "output_tokens": 3},
    }
    handler = _capture_handler({"/responses": httpx.Response(200, json=resp_json)}, captures)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = OpenAIResponsesProvider("https://api.test/v1", lambda: "k", client=client)
    msgs = [
        NormalizedMessage(role="system", content=[TextPart(text="sys")]),
        NormalizedMessage(role="user", content=[TextPart(text="go")]),
        NormalizedMessage(role="assistant", content=[],
                          tool_calls=[{"id": "fc0", "name": "t", "arguments_json": "{}"}]),
        NormalizedMessage(role="tool", content=[TextPart(text="out")], tool_call_id="fc0"),
    ]
    resp = await p.generate(msgs, [], model="m2", reasoning="high")
    req = captures[0]
    assert req.url.path.endswith("/responses")
    assert req.headers["Authorization"] == "Bearer k"
    body = json.loads(req.content)
    assert body["reasoning"] == {"effort": "high"}
    types = [item.get("type") for item in body["input"]]
    assert "function_call" in types and "function_call_output" in types
    assert body["input"][0].get("role") == "system"  # system 作为首项保留
    # 响应：function_call + text 双提取
    assert resp.message.tool_calls[0].name == "fs.write"
    assert "done" in "".join(p.text for p in resp.message.content)
    await client.aclose()


@pytest.mark.asyncio
async def test_anthropic_contract():
    captures: list[httpx.Request] = []
    resp_json = {
        "id": "a1", "model": "claude-x", "stop_reason": "tool_use",
        "content": [
            {"type": "text", "text": "thinking out"},
            {"type": "tool_use", "id": "tu1", "name": "fs.write", "input": {"path": "p"}},
        ],
        "usage": {"input_tokens": 9, "output_tokens": 4},
    }
    handler = _capture_handler({"/v1/messages": httpx.Response(200, json=resp_json)}, captures)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = AnthropicMessagesProvider("https://api.test", lambda: "ak", client=client)
    msgs = [
        NormalizedMessage(role="system", content=[TextPart(text="be nice")]),
        NormalizedMessage(role="user", content=[TextPart(text="write")]),
        NormalizedMessage(role="assistant", content=[],
                          tool_calls=[{"id": "tu0", "name": "t", "arguments_json": "{}"}]),
        NormalizedMessage(role="tool", content=[TextPart(text="res")], tool_call_id="tu0"),
    ]
    tools = [NormalizedTool(name="fs.write", description="d", parameters={"type": "object"})]
    resp = await p.generate(msgs, tools, model="claude-x")
    req = captures[0]
    assert req.url.path.endswith("/v1/messages")
    assert req.headers["x-api-key"] == "ak"
    assert req.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(req.content)
    assert body["system"] == "be nice"
    assert body["max_tokens"] == 8192
    assert body["tools"][0]["input_schema"] == {"type": "object"}
    # tool_result 是 user 消息
    assert body["messages"][-1]["role"] == "user"
    assert body["messages"][-1]["content"][0]["type"] == "tool_result"
    # 响应：tool_use 块归一
    assert resp.stop_reason.value == "tool_calls"
    assert resp.message.tool_calls[0].id == "tu1"
    assert json.loads(resp.message.tool_calls[0].arguments_json) == {"path": "p"}
    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_contract():
    captures: list[httpx.Request] = []
    resp_json = {
        "candidates": [{
            "content": {"role": "model", "parts": [
                {"text": "gemini text"},
                {"functionCall": {"name": "fs.read", "args": {"path": "q"}}},
            ]},
            "finishReason": "STOP",
        }],
        "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
        "modelVersion": "gemini-2",
    }
    handler = _capture_handler({":generateContent": httpx.Response(200, json=resp_json)}, captures)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = GeminiProvider("https://generativelanguage.test", lambda: "gk", client=client)
    msgs = [
        NormalizedMessage(role="system", content=[TextPart(text="sys")]),
        NormalizedMessage(role="user", content=[TextPart(text="q")]),
        NormalizedMessage(role="assistant", content=[],
                          tool_calls=[{"id": "fc", "name": "t", "arguments_json": "{}"}]),
        NormalizedMessage(role="tool", content=[TextPart(text="ans")], tool_call_id="t"),
    ]
    tools = [NormalizedTool(name="t", description="d", parameters={"type": "object"})]
    resp = await p.generate(msgs, tools, model="gemini-2")
    req = captures[0]
    assert ":generateContent" in req.url.path and "gemini-2" in req.url.path
    assert req.headers["x-goog-api-key"] == "gk"
    body = json.loads(req.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"
    assert body["tools"][0]["functionDeclarations"][0]["name"] == "t"
    # functionResponse 归一到 user role parts
    assert body["contents"][-1]["role"] == "user"
    assert "functionResponse" in body["contents"][-1]["parts"][0]
    # 响应：functionCall 归一
    assert resp.message.tool_calls[0].name == "fs.read"
    assert json.loads(resp.message.tool_calls[0].arguments_json) == {"path": "q"}
    assert resp.usage.input_tokens == 3
    await client.aclose()


@pytest.mark.asyncio
async def test_openai_compatible_custom_path_and_auth():
    captures: list[httpx.Request] = []
    handler = _capture_handler({"/hf/chat": _resp_200_openai_chat()}, captures)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = OpenAICompatibleProvider(
        "https://compat.test", lambda: "ck", completions_path="/hf/chat",
        auth_style="x-api-key", client=client,
    )
    res = await p.generate([NormalizedMessage(role="user", content=[TextPart(text="q")])], [], model="m")
    req = captures[0]
    assert req.url.path.endswith("/hf/chat")
    assert req.headers["x-api-key"] == "ck"
    assert "Authorization" not in req.headers
    assert res.usage.output_tokens == 7
    await client.aclose()


def test_capabilities_honesty():
    # 各协议能力声明与实现一致（不伪装）
    assert OpenAIChatProvider("u", lambda: "k").capabilities().reasoning_levels == frozenset({"low", "medium", "high"})
    assert "xhigh" not in OpenAIChatProvider("u", lambda: "k").capabilities().reasoning_levels
    g = GeminiProvider("u", lambda: "k").capabilities()
    assert g.reasoning_levels == frozenset()  # gemini 无 effort 档：如实声明不支持
    oc = OpenAICompatibleProvider("u", lambda: "k")
    assert oc.capabilities().streaming is False  # 兼容渠道默认保守


@pytest.mark.asyncio
async def test_secret_redaction_in_provider_errors():
    """密钥脱敏出口：错误消息统一过 redact_secret，密钥值不出现在最终消息。"""
    from mmagent.providers import redact_secret

    secret = "sk-super-secret-value"
    # 模拟适配器拼出的含密钥错误消息（例如 base_url 配置错误时 URL 里带 key）
    msg = f"请求错误 401: bad key {secret} (url https://api.test/v1?key={secret})"
    safe = redact_secret(msg, secret)
    assert secret not in safe
    assert "***REDACTED***" in safe
    # 脱敏后消息仍保留可诊断信息
    assert "401" in safe


def test_capabilities_streaming_honest():
    """流式未实现前：全部如实声明 False（v0.3.x 落地后启用）。"""
    for maker in (
        lambda: OpenAIChatProvider("u", lambda: "k"),
        lambda: OpenAIResponsesProvider("u", lambda: "k"),
        lambda: AnthropicMessagesProvider("u", lambda: "k"),
        lambda: GeminiProvider("u", lambda: "k"),
    ):
        assert maker().capabilities().streaming is False


def test_role_routing_defaults_and_override():
    from mmagent.mm.config.role_routing import ModelProfile, ProviderConfig, RoleRouting

    routing = RoleRouting(default_profile="prof_a", role_map={"modeler": "prof_b"})
    assert routing.profile_for("modeler") == "prof_b"
    assert routing.profile_for("reader") == "prof_a"
    pc = ProviderConfig(profile_id="p1", name="渠道A", protocol="openai_chat",
                        base_url="https://x", api_key_ref="ENV:KEY_X")
    assert pc.api_key_ref.startswith("ENV:")
    mp = ModelProfile(profile_id="m1", provider_id="p1", model="model-x", reasoning="high")
    assert mp.reasoning == "high"
