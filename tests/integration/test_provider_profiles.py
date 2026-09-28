from __future__ import annotations

import pytest

from mmagent.api.projects import create_project
from mmagent.api.providers import (
    build_provider,
    create_provider_profile,
    delete_provider_profile,
    public_profile,
)
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


def test_openai_compatible_image_input_extra_round_trip(tmp_path) -> None:
    """R3-F6: extra.image_input on an openai_compatible profile must reach the
    adapter capabilities; explicit false and the default stay conservative."""
    handle = create_project(tmp_path / "proj-vision", name="providers-vision", profile="标准")
    store = MemoryCredentialStore()
    db = handle.workspace.db
    try:
        explicit_true = create_provider_profile(
            db, store,
            name="CompatVision",
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            model="vision-model",
            api_key="sk-vision",
            extra={"image_input": True},
        )
        provider = build_provider(db, store, explicit_true.model_profile_id)
        assert provider.capabilities().image_input is True

        explicit_false = create_provider_profile(
            db, store,
            name="CompatNoVision",
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            model="text-model",
            api_key="sk-text",
            extra={"image_input": False},
        )
        assert build_provider(
            db, store, explicit_false.model_profile_id
        ).capabilities().image_input is False

        default = create_provider_profile(
            db, store,
            name="CompatDefault",
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            model="default-model",
            api_key="sk-default",
        )
        assert build_provider(
            db, store, default.model_profile_id
        ).capabilities().image_input is False
    finally:
        db.close()


def test_provider_profile_rejects_secret_bearing_extra_headers(tmp_path) -> None:
    handle = create_project(
        tmp_path / "proj-secret-headers",
        name="providers-secret-headers",
        profile="标准",
    )
    store = MemoryCredentialStore()
    db = handle.workspace.db
    try:
        for header_name in (
            "Authorization",
            "authorization",
            "x-api-key",
            "API-Key",
            "Cookie",
            "Proxy-Authorization",
        ):
            with pytest.raises(ValueError, match="Credential Manager"):
                create_provider_profile(
                    db,
                    store,
                    name="Unsafe",
                    protocol="openai_compatible",
                    base_url="https://example.invalid/v1",
                    model="model-x",
                    extra={
                        "extra_headers": {
                            header_name: "secret-that-must-not-enter-sqlite",
                        }
                    },
                )

        rows = db.query("SELECT extra_json FROM providers")
        assert all(
            "secret-that-must-not-enter-sqlite" not in row["extra_json"]
            for row in rows
        )
    finally:
        db.close()


def test_provider_profile_allows_non_secret_custom_headers(tmp_path) -> None:
    handle = create_project(
        tmp_path / "proj-safe-headers",
        name="providers-safe-headers",
        profile="标准",
    )
    store = MemoryCredentialStore()
    db = handle.workspace.db
    try:
        profile = create_provider_profile(
            db,
            store,
            name="Safe",
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            model="model-x",
            extra={
                "extra_headers": {
                    "X-Client-Version": "mmagent-test",
                    "X-Organization": "test-org",
                }
            },
        )
        assert profile.extra["extra_headers"]["X-Client-Version"] == "mmagent-test"
    finally:
        db.close()


def test_provider_profile_update_rejects_secret_bearing_extra_headers(tmp_path) -> None:
    from mmagent.api.providers import update_provider_profile

    handle = create_project(
        tmp_path / "proj-update-secret-headers",
        name="providers-update-secret-headers",
        profile="标准",
    )
    store = MemoryCredentialStore()
    db = handle.workspace.db
    try:
        profile = create_provider_profile(
            db,
            store,
            name="Safe",
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            model="model-x",
        )
        with pytest.raises(ValueError, match="Credential Manager"):
            update_provider_profile(
                db,
                model_profile_id=profile.model_profile_id,
                name="Unsafe Update",
                protocol="openai_compatible",
                base_url="https://example.invalid/v1",
                model="model-x",
                extra={"extra_headers": {"x-api-key": "must-not-persist"}},
            )

        unchanged = handle.workspace.db.query_one(
            "SELECT name, extra_json FROM providers WHERE id = ?",
            (profile.provider_id,),
        )
        assert unchanged["name"] == "Safe"
        assert "must-not-persist" not in unchanged["extra_json"]
    finally:
        db.close()
