from __future__ import annotations

from mmagent.api.providers import (
    build_provider,
    create_provider_profile,
    delete_provider_profile,
    public_profile,
)
from mmagent.api.projects import create_project
from mmagent.providers.base import ModelBoundProvider
from mmagent.runtime.credentials import MemoryCredentialStore


def test_provider_profile_keeps_secret_out_of_sqlite_and_ui(tmp_path) -> None:
    handle = create_project(tmp_path / "proj", name="providers", profile="标准")
    store = MemoryCredentialStore()
    secret = "sk-test-super-secret-value"

    profile = create_provider_profile(
        handle.workspace.db,
        store,
        name="Primary",
        protocol="openai_chat",
        base_url="https://example.invalid/v1",
        model="gpt-example",
        api_key=secret,
        reasoning="high",
        max_output_tokens=12000,
        timeout_s=420,
    )

    row = handle.workspace.db.query_one(
        "SELECT api_key_ref, extra_json FROM providers WHERE id = ?",
        (profile.provider_id,),
    )
    assert row["api_key_ref"] == profile.api_key_ref
    assert secret not in row["api_key_ref"]
    assert secret not in row["extra_json"]

    public = public_profile(profile)
    assert public["has_api_key"] is True
    assert secret not in repr(public)
    assert store.get(profile.api_key_ref) == secret

    provider = build_provider(
        handle.workspace.db, store, profile.model_profile_id
    )
    assert isinstance(provider, ModelBoundProvider)
    assert provider.resolve_model("mock") == "gpt-example"
    assert provider.resolve_reasoning("medium") == "high"
    assert provider.max_output_tokens == 12000
    assert provider.timeout_s == 420.0

    handle.workspace.db.close()


def test_delete_last_model_profile_deletes_credential(tmp_path) -> None:
    handle = create_project(tmp_path / "proj", name="providers-delete", profile="标准")
    store = MemoryCredentialStore()
    profile = create_provider_profile(
        handle.workspace.db,
        store,
        name="Primary",
        protocol="openai_compatible",
        base_url="https://example.invalid/v1",
        model="model-x",
        api_key="test-key",
        extra={"auth_style": "bearer"},
    )
    ref = profile.api_key_ref
    assert ref is not None and store.get(ref) == "test-key"

    delete_provider_profile(handle.workspace.db, store, profile.model_profile_id)
    assert handle.workspace.db.query_one(
        "SELECT id FROM providers WHERE id = ?", (profile.provider_id,)
    ) is None
    assert ref not in store.values
    handle.workspace.db.close()
