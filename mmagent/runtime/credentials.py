"""Credential storage abstraction.

Production Windows builds use Credential Manager.  SQLite stores only the
opaque reference returned by this layer; secrets never enter project.db.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol


class CredentialStore(Protocol):
    def set(self, ref: str, secret: str) -> None: ...
    def get(self, ref: str) -> str: ...
    def delete(self, ref: str) -> None: ...


@dataclass
class MemoryCredentialStore:
    """Test-only credential store."""

    values: dict[str, str] = field(default_factory=dict)

    def set(self, ref: str, secret: str) -> None:
        self.values[ref] = secret

    def get(self, ref: str) -> str:
        try:
            return self.values[ref]
        except KeyError as exc:
            raise KeyError(f"credential not found: {ref}") from exc

    def delete(self, ref: str) -> None:
        self.values.pop(ref, None)


class WindowsCredentialStore:
    PREFIX = "MM-Agent-Desktop"

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows Credential Manager 只在 Windows 可用")
        try:
            import win32cred  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("pywin32/win32cred 不可用") from exc

    def _target(self, ref: str) -> str:
        value = ref.strip().replace("\\", "/")
        if not value:
            raise ValueError("credential ref must be non-empty")
        return f"{self.PREFIX}/{value}"

    def set(self, ref: str, secret: str) -> None:
        if not secret:
            raise ValueError("secret must be non-empty")
        import win32cred

        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": self._target(ref),
                "CredentialBlob": secret.encode("utf-8"),
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                "UserName": "MM-Agent Desktop",
                "Comment": "MM-Agent Desktop provider credential",
            },
            0,
        )

    def get(self, ref: str) -> str:
        import win32cred

        try:
            item = win32cred.CredRead(
                self._target(ref), win32cred.CRED_TYPE_GENERIC, 0
            )
        except Exception as exc:
            raise KeyError(f"credential not found: {ref}") from exc
        blob = item.get("CredentialBlob", b"")
        if isinstance(blob, bytes):
            return blob.decode("utf-8")
        return str(blob)

    def delete(self, ref: str) -> None:
        import win32cred

        try:
            win32cred.CredDelete(
                self._target(ref), win32cred.CRED_TYPE_GENERIC, 0
            )
        except Exception:
            # Deleting an already-missing secret is idempotent for cleanup paths.
            pass
