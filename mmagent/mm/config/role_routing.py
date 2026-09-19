"""role routing / model profiles 配置（总方案 §24）。

- provider：协议 + base_url + api_key 引用（绝不存明文）；
- model_profile：provider + model + reasoning/timeout/max_output；
- role_routing：role_id → model_profile_id（默认全角色同 profile）；
- 路由是纯配置数据，AgentLoop 通过 provider factory 拿到适配器实例。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderConfig:
    """一个 Provider 渠道配置（api_key 永不入库/入日志）。"""

    profile_id: str
    name: str
    protocol: str  # openai_chat | openai_responses | anthropic_messages | gemini | openai_compatible
    base_url: str
    api_key_ref: str = ""  # 凭据引用（Credential Manager 键名 / 环境变量名），非明文
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelProfile:
    """一个模型档位：具体 model + 推理档 + 超时。"""

    profile_id: str
    provider_id: str
    model: str
    reasoning: str | None = None
    max_output_tokens: int | None = None
    timeout_s: float = 600.0


@dataclass(frozen=True)
class RoleRouting:
    """role_id → model_profile_id。未配置的角色回落到 default_profile。"""

    default_profile: str
    role_map: dict[str, str] = field(default_factory=dict)

    def profile_for(self, role_id: str) -> str:
        return self.role_map.get(role_id, self.default_profile)


def validate_no_secret_in_errors(message: str, secrets: tuple[str, ...]) -> str:
    """错误消息统一出口：确保任何密钥值不出现在消息中。"""
    out = message
    for sec in secrets:
        if sec:
            out = out.replace(sec, "***REDACTED***")
    return out
