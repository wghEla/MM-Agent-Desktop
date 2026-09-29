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


@pytest.mark.parametrize(
    "base_url",
    [
        "https://user:password@example.invalid/v1",
        "https://example.invalid/v1?api_key=must-not-persist",
        "https://example.invalid/v1#token=must-not-persist",
        "file:///tmp/provider",
        "example.invalid/v1",
    ],
)
def test_provider_profile_rejects_unsafe_or_non_http_base_urls(
    tmp_path,
    base_url,
) -> None:
    handle = create_project(
        tmp_path / ("proj-url-" + str(abs(hash(base_url)))),
        name="providers-url-boundary",
        profile="标准",
    )
    store = MemoryCredentialStore()
    try:
        with pytest.raises(ValueError):
            create_provider_profile(
                handle.workspace.db,
                store,
                name="Unsafe URL",
                protocol="openai_compatible",
                base_url=base_url,
                model="model-x",
            )
        serialized = handle.workspace.db.path.read_bytes()
        assert b"must-not-persist" not in serialized
        assert b"password" not in serialized
    finally:
        handle.workspace.db.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("models_path", "https://other.invalid/models"),
        ("models_path", "//other.invalid/models"),
        ("models_path", "/models?token=must-not-persist"),
        ("completions_path", "https://other.invalid/chat"),
        ("completions_path", "/chat/completions#must-not-persist"),
        ("completions_path", ""),
    ],
)
def test_provider_profile_rejects_unsafe_compatible_endpoint_paths(
    tmp_path,
    field,
    value,
) -> None:
    handle = create_project(
        tmp_path / ("proj-path-" + field + "-" + str(abs(hash(value)))),
        name="providers-path-boundary",
        profile="标准",
    )
    store = MemoryCredentialStore()
    try:
        with pytest.raises(ValueError):
            create_provider_profile(
                handle.workspace.db,
                store,
                name="Unsafe Path",
                protocol="openai_compatible",
                base_url="https://example.invalid/v1",
                model="model-x",
                extra={field: value},
            )
        serialized = handle.workspace.db.path.read_bytes()
        assert b"must-not-persist" not in serialized
    finally:
        handle.workspace.db.close()


def test_provider_profile_normalizes_safe_compatible_endpoint_paths(tmp_path) -> None:
    handle = create_project(
        tmp_path / "proj-path-safe",
        name="providers-path-safe",
        profile="标准",
    )
    store = MemoryCredentialStore()
    try:
        profile = create_provider_profile(
            handle.workspace.db,
            store,
            name="Safe Paths",
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            model="model-x",
            extra={
                "models_path": "catalog/models",
                "completions_path": "chat/completions",
            },
        )
        assert profile.extra["models_path"] == "/catalog/models"
        assert profile.extra["completions_path"] == "/chat/completions"

        disabled = create_provider_profile(
            handle.workspace.db,
            store,
            name="No Models",
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            model="model-y",
            extra={"models_path": ""},
        )
        assert disabled.extra["models_path"] is None
    finally:
        handle.workspace.db.close()


def test_clear_provider_credential_deletes_secret_before_sqlite_ref(tmp_path) -> None:
    from mmagent.api.providers import clear_provider_credential

    handle = create_project(
        tmp_path / "proj-clear-order",
        name="providers-clear-order",
        profile="标准",
    )
    db = handle.workspace.db

    class ObservingStore(MemoryCredentialStore):
        def __init__(self):
            super().__init__()
            self.provider_id = ""
            self.saw_ref_during_delete = False

        def delete(self, ref: str) -> None:
            row = db.query_one(
                "SELECT api_key_ref FROM providers WHERE id = ?",
                (self.provider_id,),
            )
            self.saw_ref_during_delete = bool(row and row["api_key_ref"] == ref)
            super().delete(ref)

    store = ObservingStore()
    try:
        profile = create_provider_profile(
            db,
            store,
            name="Clear Order",
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            model="model-x",
            api_key="test-clear-order",
        )
        store.provider_id = profile.provider_id
        clear_provider_credential(db, store, profile.model_profile_id)
        assert store.saw_ref_during_delete is True
        row = db.query_one(
            "SELECT api_key_ref FROM providers WHERE id = ?",
            (profile.provider_id,),
        )
        assert row["api_key_ref"] is None
    finally:
        db.close()


def test_delete_last_provider_profile_deletes_secret_before_sqlite_rows(tmp_path) -> None:
    handle = create_project(
        tmp_path / "proj-delete-order",
        name="providers-delete-order",
        profile="标准",
    )
    db = handle.workspace.db

    class ObservingStore(MemoryCredentialStore):
        def __init__(self):
            super().__init__()
            self.provider_id = ""
            self.saw_provider_during_delete = False

        def delete(self, ref: str) -> None:
            row = db.query_one(
                "SELECT id, api_key_ref FROM providers WHERE id = ?",
                (self.provider_id,),
            )
            self.saw_provider_during_delete = bool(
                row and row["api_key_ref"] == ref
            )
            super().delete(ref)

    store = ObservingStore()
    try:
        profile = create_provider_profile(
            db,
            store,
            name="Delete Order",
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            model="model-x",
            api_key="test-delete-order",
        )
        store.provider_id = profile.provider_id
        delete_provider_profile(db, store, profile.model_profile_id)
        assert store.saw_provider_during_delete is True
        assert db.query_one(
            "SELECT id FROM providers WHERE id = ?",
            (profile.provider_id,),
        ) is None
    finally:
        db.close()


def test_compatible_profile_rejects_saved_key_with_no_auth_style(tmp_path) -> None:
    from mmagent.api.providers import (
        set_provider_credential,
        update_provider_profile,
    )

    handle = create_project(
        tmp_path / "proj-auth-binding",
        name="providers-auth-binding",
        profile="标准",
    )
    store = MemoryCredentialStore()
    db = handle.workspace.db
    try:
        with pytest.raises(ValueError, match="credential requires"):
            create_provider_profile(
                db,
                store,
                name="Contradictory",
                protocol="openai_compatible",
                base_url="https://example.invalid/v1",
                model="model-x",
                api_key="test-key",
                extra={"auth_style": "none"},
            )

        profile = create_provider_profile(
            db,
            store,
            name="Keyless",
            protocol="openai_compatible",
            base_url="https://example.invalid/v1",
            model="model-x",
            extra={"auth_style": "none"},
        )
        with pytest.raises(ValueError, match="credential requires"):
            set_provider_credential(
                db,
                store,
                profile.model_profile_id,
                "test-late-key",
            )

        updated = update_provider_profile(
            db,
            model_profile_id=profile.model_profile_id,
            name=profile.name,
            protocol=profile.protocol,
            base_url=profile.base_url,
            model=profile.model,
            extra={"auth_style": "bearer"},
        )
        set_provider_credential(
            db,
            store,
            updated.model_profile_id,
            "test-late-key",
        )
        with pytest.raises(ValueError, match="credential requires"):
            update_provider_profile(
                db,
                model_profile_id=updated.model_profile_id,
                name=updated.name,
                protocol=updated.protocol,
                base_url=updated.base_url,
                model=updated.model,
                extra={"auth_style": "none"},
            )
    finally:
        db.close()


def test_provider_profile_requires_credential_clear_before_endpoint_or_protocol_change(
    tmp_path,
) -> None:
    from mmagent.api.providers import (
        clear_provider_credential,
        update_provider_profile,
    )

    handle = create_project(
        tmp_path / "proj-credential-scope",
        name="providers-credential-scope",
        profile="标准",
    )
    store = MemoryCredentialStore()
    db = handle.workspace.db
    try:
        profile = create_provider_profile(
            db,
            store,
            name="Scoped",
            protocol="openai_compatible",
            base_url="https://relay-one.invalid/v1",
            model="model-a",
            api_key="test-scoped-secret",
            extra={"auth_style": "bearer"},
        )
        ref = profile.api_key_ref
        assert ref is not None
        assert store.get(ref) == "test-scoped-secret"

        with pytest.raises(ValueError, match="clear the saved credential"):
            update_provider_profile(
                db,
                model_profile_id=profile.model_profile_id,
                name="Scoped",
                protocol="openai_compatible",
                base_url="https://relay-two.invalid/v1",
                model="model-a",
                extra={"auth_style": "bearer"},
            )

        with pytest.raises(ValueError, match="clear the saved credential"):
            update_provider_profile(
                db,
                model_profile_id=profile.model_profile_id,
                name="Scoped",
                protocol="openai_chat",
                base_url="https://relay-one.invalid/v1",
                model="model-a",
            )

        unchanged = handle.workspace.db.query_one(
            "SELECT protocol, base_url, api_key_ref FROM providers WHERE id = ?",
            (profile.provider_id,),
        )
        assert unchanged["protocol"] == "openai_compatible"
        assert unchanged["base_url"] == "https://relay-one.invalid/v1"
        assert unchanged["api_key_ref"] == ref
        assert store.get(ref) == "test-scoped-secret"

        clear_provider_credential(db, store, profile.model_profile_id)
        updated = update_provider_profile(
            db,
            model_profile_id=profile.model_profile_id,
            name="Scoped",
            protocol="openai_compatible",
            base_url="https://relay-two.invalid/v1",
            model="model-b",
            extra={"auth_style": "bearer"},
        )
        assert updated.base_url == "https://relay-two.invalid/v1"
        assert updated.api_key_ref is None
    finally:
        db.close()


def test_provider_profile_accepts_https_and_local_http_base_urls(tmp_path) -> None:
    store = MemoryCredentialStore()

    first = create_project(
        tmp_path / "proj-url-https",
        name="providers-url-https",
        profile="标准",
    )
    try:
        profile = create_provider_profile(
            first.workspace.db,
            store,
            name="HTTPS",
            protocol="openai_compatible",
            base_url="https://example.invalid/v1/",
            model="model-x",
        )
        assert profile.base_url == "https://example.invalid/v1"
    finally:
        first.workspace.db.close()

    second = create_project(
        tmp_path / "proj-url-local",
        name="providers-url-local",
        profile="标准",
    )
    try:
        profile = create_provider_profile(
            second.workspace.db,
            store,
            name="Local",
            protocol="openai_compatible",
            base_url="http://127.0.0.1:8080/v1",
            model="model-x",
        )
        assert profile.base_url == "http://127.0.0.1:8080/v1"
    finally:
        second.workspace.db.close()
