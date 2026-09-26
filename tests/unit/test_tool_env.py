"""tool_env.py 安全边界测试：外部工具不得继承 provider/cloud secrets。"""
from __future__ import annotations

import pytest

from mmagent.runtime.tool_env import latex_env, matlab_env, sanitized_external_env

_SECRET_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "MMAGENT_SIDECAR_TOKEN",
    "GEMINI_API_KEY",
    "DATABASE_URL",
    "GITHUB_TOKEN",
)


@pytest.fixture(autouse=True)
def _inject_secrets(monkeypatch):
    """注入假 secret 到 os.environ 以测试 allowlist 过滤。"""
    for key in _SECRET_VARS:
        monkeypatch.setenv(key, f"test-secret-{key.lower()}")


class TestSanitizedExternalEnv:
    def test_secrets_excluded(self):
        env = sanitized_external_env()
        for key in _SECRET_VARS:
            assert key not in env, f"{key} 泄漏到外部工具环境"

    def test_base_vars_included(self, monkeypatch):
        monkeypatch.setenv("SYSTEMROOT", "C:\\Windows")
        monkeypatch.setenv("PATH", "C:\\bin")
        env = sanitized_external_env()
        assert env["SYSTEMROOT"] == "C:\\Windows"
        assert env["PATH"] == "C:\\bin"

    def test_extra_keys_included(self, monkeypatch):
        monkeypatch.setenv("MY_TOOL_VAR", "value")
        env = sanitized_external_env(("MY_TOOL_VAR",))
        assert env["MY_TOOL_VAR"] == "value"

    def test_extra_keys_explicit_mechanism(self, monkeypatch):
        """extra_keys 是显式机制：传入才包含，不传入不包含。"""
        # 不传 extra_keys → 不包含
        env = sanitized_external_env()
        assert "MY_TOOL_VAR" not in env
        # 传入 extra_keys → 包含（这是调用者的显式决定）
        monkeypatch.setenv("MY_TOOL_VAR", "value")
        env2 = sanitized_external_env(("MY_TOOL_VAR",))
        assert env2["MY_TOOL_VAR"] == "value"


class TestLatexEnv:
    def test_no_secrets(self):
        env = latex_env()
        for key in _SECRET_VARS:
            assert key not in env

    def test_tex_vars_pass_through(self, monkeypatch):
        monkeypatch.setenv("TEXMFHOME", "D:/texmf")
        env = latex_env()
        assert env.get("TEXMFHOME") == "D:/texmf"

    def test_no_matlab_vars(self, monkeypatch):
        monkeypatch.setenv("MLM_LICENSE_FILE", "D:/license.dat")
        env = latex_env()
        assert "MLM_LICENSE_FILE" not in env


class TestMatlabEnv:
    def test_no_secrets(self):
        env = matlab_env()
        for key in _SECRET_VARS:
            assert key not in env

    def test_matlab_license_vars_pass(self, monkeypatch):
        monkeypatch.setenv("MLM_LICENSE_FILE", "D:/license.dat")
        env = matlab_env()
        assert env.get("MLM_LICENSE_FILE") == "D:/license.dat"

    def test_no_tex_vars(self, monkeypatch):
        monkeypatch.setenv("TEXMFHOME", "D:/texmf")
        env = matlab_env()
        assert "TEXMFHOME" not in env
