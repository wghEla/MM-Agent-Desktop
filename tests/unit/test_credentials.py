"""Windows Credential Manager store round-trip (installed-gate defect fix)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

PROJECT_ROOT_FOR_TESTS = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.name != "nt", reason="Windows Credential Manager only")
def test_windows_credential_store_round_trip() -> None:
    """CredWrite must take a Unicode blob on current pywin32 (bytes raise
    TypeError), and get() must decode the UTF-16LE blob back to the secret."""
    from mmagent.runtime.credentials import WindowsCredentialStore

    store = WindowsCredentialStore()
    ref = "gate-test/round-trip"
    secret = "sk-fake-test-only-value"
    store.set(ref, secret)
    try:
        assert store.get(ref) == secret
    finally:
        store.delete(ref)
    with pytest.raises(KeyError):
        store.get(ref)


@pytest.mark.skipif(os.name != "nt", reason="Windows Credential Manager only")
def test_windows_credential_store_overwrite() -> None:
    """Re-setting the same ref must replace the stored secret."""
    from mmagent.runtime.credentials import WindowsCredentialStore

    store = WindowsCredentialStore()
    ref = "gate-test/overwrite"
    store.set(ref, "sk-first-fake")
    store.set(ref, "sk-second-fake")
    try:
        assert store.get(ref) == "sk-second-fake"
    finally:
        store.delete(ref)


@pytest.mark.skipif(os.name != "nt", reason="Windows Credential Manager only")
def test_windows_credential_store_rejects_empty_secret() -> None:
    from mmagent.runtime.credentials import WindowsCredentialStore

    store = WindowsCredentialStore()
    with pytest.raises(ValueError):
        store.set("gate-test/empty", "")


# ==================== cross-process + error taxonomy (installed-credential gate) ====================

def test_windows_credential_store_cross_process_round_trip() -> None:
    """set() in one process, get() in a DIFFERENT process — the exact defect
    seen in the frozen sidecar must stay fixed across process boundaries."""
    import subprocess
    import sys
    import uuid

    from mmagent.runtime.credentials import WindowsCredentialStore

    ref = f"gate-test/cross-process-{uuid.uuid4().hex[:8]}"
    secret = "sk-mmagent-installed-e2e-fake-only-20260928"
    setter = (
        "import sys;"
        f"sys.path.insert(0, {str(PROJECT_ROOT_FOR_TESTS)!r});"
        "from mmagent.runtime.credentials import WindowsCredentialStore;"
        f"WindowsCredentialStore().set({ref!r}, {secret!r})"
    )
    subprocess.run([sys.executable, "-c", setter], check=True, cwd=PROJECT_ROOT_FOR_TESTS)
    try:
        store = WindowsCredentialStore()
        assert store.get(ref) == secret
        desc = store.describe(ref)
        assert desc["found"] is True
        assert desc["blob_kind"] in ("bytes", "str")
        assert "sha256_prefix" in desc
    finally:
        WindowsCredentialStore().delete(ref)


def test_missing_credential_is_credential_not_found() -> None:
    """A missing target must surface as NOT_FOUND, distinct from read/decode
    failures — masking one as the other misleads real-provider debugging."""
    import uuid

    import pytest

    from mmagent.runtime.credentials import CredentialNotFound, WindowsCredentialStore

    store = WindowsCredentialStore()
    with pytest.raises(CredentialNotFound):
        store.get(f"gate-test/definitely-missing-{uuid.uuid4().hex[:8]}")


def test_decode_failure_is_not_masked_as_not_found() -> None:
    """An existing blob that cannot be decoded raises CredentialReadError —
    never CredentialNotFound/KeyError('not found')."""
    import pytest

    from mmagent.runtime.credentials import CredentialReadError, _decode_blob

    with pytest.raises(CredentialReadError) as exc_info:
        _decode_blob(b"\xff\xfe\x00\x81\x81", "gate-test/corrupt")  # invalid utf-16-le
    assert "decode failed" in str(exc_info.value)
    assert "sha256_prefix" in str(exc_info.value)
    assert not isinstance(exc_info.value, KeyError)


def test_decode_blob_accepts_str_and_both_byte_encodings() -> None:
    from mmagent.runtime.credentials import _decode_blob

    assert _decode_blob("wide-string-key", "r") == "wide-string-key"
    assert _decode_blob(b"ascii-key", "r") == "ascii-key"
    assert _decode_blob("ascii-key".encode("utf-16-le"), "r") == "ascii-key"
    assert _decode_blob("密钥测试".encode("utf-16-le"), "r") == "密钥测试"
