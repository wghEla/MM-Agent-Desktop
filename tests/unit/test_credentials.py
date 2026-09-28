"""Windows Credential Manager store round-trip (installed-gate defect fix)."""
from __future__ import annotations

import os

import pytest


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
