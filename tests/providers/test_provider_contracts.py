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
from mmagent.providers.normalized import ImagePart, NormalizedMessage, NormalizedTool, TextPart
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


# ==================== Round-1 外审修复的负向测试 ====================
def test_r1_capabilities_image_input_honest():
    """Native multimodal protocols advertise image input; generic compatible stays conservative."""
    for maker in (
        lambda: OpenAIChatProvider("u", lambda: "k"),
        lambda: OpenAIResponsesProvider("u", lambda: "k"),
        lambda: AnthropicMessagesProvider("u", lambda: "k"),
        lambda: GeminiProvider("u", lambda: "k"),
    ):
        assert maker().capabilities().image_input is True
    assert OpenAICompatibleProvider("u", lambda: "k").capabilities().image_input is False


def test_r1_anthropic_reasoning_honest():
    """thinking 预算映射未实现 → reasoning_levels 空集（不伪装）。"""
    p = AnthropicMessagesProvider("u", lambda: "k")
    assert p.capabilities().reasoning_levels == frozenset()


def test_r1_retry_after_http_date_and_malformed():
    import email.utils
    import time as _t

    from mmagent.providers._http_util import parse_retry_after

    # delta-seconds
    assert parse_retry_after("7") == 7.0
    # HTTP-date（合法）
    http_date = email.utils.formatdate(_t.time() + 30, usegmt=True)
    v = parse_retry_after(http_date)
    assert v is not None and 0 <= v <= 60
    # 畸形（HTTP-date 无效 / 乱码）→ None，绝不抛
    assert parse_retry_after("not-a-date") is None
    assert parse_retry_after("") is None
    assert parse_retry_after(None) is None


def test_r1_malformed_2xx_json_wrapped():
    """HTTP 200 但响应体非 JSON → ProviderError（协议错误），不抛裸 json 异常。"""
    import asyncio as aio

    from mmagent.agent.errors import ErrorKind
    from mmagent.providers.openai_chat import OpenAIChatProvider as P

    def handler(request):
        return httpx.Response(200, content=b"THIS IS NOT JSON")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = P("https://api.test/v1", lambda: "k", client=client)
    with pytest.raises(ProviderError) as ei:
        aio.run(p.generate([NormalizedMessage(role="user", content=[TextPart(text="x")])], [], model="m"))
    assert ei.value.kind == ErrorKind.PROVIDER_PROTOCOL
    aio.run(client.aclose())


def test_r1_unknown_stop_reason_fail_closed():
    """未知 finish_reason/stop_reason → ProviderError，不得默认 END_TURN。"""

    from mmagent.providers.anthropic_messages import parse_messages_response
    from mmagent.providers.gemini import parse_generate_response
    from mmagent.providers.openai_chat import parse_chat_response

    with pytest.raises(ProviderError):
        parse_chat_response({"choices": [{"message": {"role": "assistant", "content": "x"},
                                          "finish_reason": "mystery"}]})
    with pytest.raises(ProviderError):
        parse_messages_response({"content": [{"type": "text", "text": "x"}],
                                 "stop_reason": "martian_requirement"})
    with pytest.raises(ProviderError):
        parse_generate_response({"candidates": [{"content": {"parts": [{"text": "x"}]},
                                                 "finishReason": "MARTIAN"}]})


def test_r9_responses_continuation_items_prepended():
    """continuation_items 支持上一轮 output items 回传（reasoning 模型多步工具）。"""
    from mmagent.providers.openai_responses import build_responses_payload

    prior = [{"type": "reasoning", "summary": []}, {"type": "message", "id": "m1"}]
    payload = build_responses_payload(
        [NormalizedMessage(role="tool", content=[TextPart(text="res")], tool_call_id="fc1")],
        [], model="m", reasoning=None, max_output_tokens=None,
        continuation_items=prior,
    )
    assert payload["input"][0] == prior[0]
    assert payload["input"][1] == prior[1]
    assert payload["input"][-1]["type"] == "function_call_output"


def test_r1_provider_config_rejects_plaintext_key():
    from mmagent.mm.config.role_routing import ProviderConfig

    # 明文/裸名 ref 必须拒绝
    with pytest.raises(ValueError):
        ProviderConfig(profile_id="p", name="n", protocol="openai_chat",
                       base_url="https://x", api_key_ref="sk-literal-secret")
    with pytest.raises(ValueError):
        ProviderConfig(profile_id="p", name="n", protocol="openai_chat",
                       base_url="https://x", api_key_ref="BARE_NAME")
    # 合法引用
    pc = ProviderConfig(profile_id="p", name="n", protocol="openai_chat",
                        base_url="https://x", api_key_ref="ENV:KEY_X")
    assert pc.api_key_ref == "ENV:KEY_X"


# ==================== Round-2 P1 修复的集成测试 ====================
# generate() 级 429 集成：Retry-After 头的三种形态 + 缺失，经真实 generate() 路径
@pytest.mark.asyncio
@pytest.mark.parametrize("header_value,expect_s", [
    ("120", 120.0),          # delta-seconds
    (None, None),             # 无 header
    ("garbage", None),        # 畸形
])
async def test_r2_p1_generate_429_retry_after_wired(header_value, expect_s):
    """429 + Retry-After 各形态经 generate() 全路径 → RateLimitError 不裸抛。"""
    headers = {"retry-after": header_value} if header_value else {}
    def handler(request):
        return httpx.Response(429, headers=headers, json={"error": "slow"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = OpenAIChatProvider("https://api.test/v1", lambda: "k", client=client)
    with pytest.raises(RateLimitError) as ei:
        await p.generate([NormalizedMessage(role="user", content=[TextPart(text="x")])], [], model="m")
    assert ei.value.retry_after_s == expect_s
    assert ei.value.retryable
    await client.aclose()


@pytest.mark.asyncio
async def test_r2_p1_generate_429_http_date():
    """429 + HTTP-date → retry_after_s 合法非负秒数 → 不得 ValueError。"""
    import email.utils
    import time as _t

    def handler(request):
        http_date = email.utils.formatdate(_t.time() + 45, usegmt=True)
        return httpx.Response(429, headers={"retry-after": http_date}, json={"error": "slow"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = OpenAIChatProvider("https://api.test/v1", lambda: "k", client=client)
    with pytest.raises(RateLimitError) as ei:
        await p.generate([NormalizedMessage(role="user", content=[TextPart(text="x")])], [], model="m")
    assert ei.value.retry_after_s is not None
    assert 0 <= ei.value.retry_after_s <= 60
    await client.aclose()


def test_r2_p2_choices_missing_protocol_error():
    """choices 缺失 → PROVIDER_PROTOCOL（上游协议违规，非本地 bad request）。"""
    from mmagent.agent.errors import ErrorKind
    from mmagent.providers.openai_chat import parse_chat_response

    with pytest.raises(ProviderError) as ei:
        parse_chat_response({"id": "x", "choices": []})
    assert ei.value.kind == ErrorKind.PROVIDER_PROTOCOL



def test_native_multimodal_payload_shapes():
    from mmagent.providers.anthropic_messages import build_messages_payload
    from mmagent.providers.gemini import build_gemini_payload
    from mmagent.providers.openai_chat import build_chat_payload
    from mmagent.providers.openai_responses import build_responses_payload

    msg = NormalizedMessage(
        role="user",
        content=[
            TextPart(text="inspect"),
            ImagePart(b64="YWJj", media_type="image/png"),
        ],
    )

    chat = build_chat_payload(
        [msg], [], model="m", reasoning=None, max_output_tokens=None, stream=False
    )
    assert chat["messages"][0]["content"][1]["type"] == "image_url"
    assert chat["messages"][0]["content"][1]["image_url"]["url"].endswith("YWJj")

    responses = build_responses_payload(
        [msg], [], model="m", reasoning=None, max_output_tokens=None
    )
    assert responses["input"][0]["content"][1]["type"] == "input_image"

    anthropic = build_messages_payload(
        [msg], [], model="m", max_output_tokens=100, reasoning=None
    )
    image = anthropic["messages"][0]["content"][1]
    assert image["type"] == "image"
    assert image["source"]["data"] == "YWJj"

    gemini = build_gemini_payload(
        [msg], [], model="m", reasoning=None, max_output_tokens=None
    )
    inline = gemini["contents"][0]["parts"][1]["inlineData"]
    assert inline["mimeType"] == "image/png"
    assert inline["data"] == "YWJj"
