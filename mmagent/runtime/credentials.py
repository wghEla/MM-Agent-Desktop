"""Credential storage abstraction.

Production Windows builds use Credential Manager.  SQLite stores only the
opaque reference returned by this layer; secrets never enter project.db.

Error taxonomy (never mask an existing-but-unreadable credential as missing):
- CredentialNotFound: Windows reports the target does not exist;
- CredentialReadError: the target exists but read/decode failed — the original
  OS error and blob shape are carried in the message for diagnosis.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Protocol


class CredentialNotFound(KeyError):
    """Windows reports the credential target does not exist."""


class CredentialReadError(RuntimeError):
    """The credential target exists but reading/decoding it failed."""


class CredentialDeleteError(RuntimeError):
    """Windows could not delete a credential target for a non-NOT_FOUND reason."""


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
            raise CredentialNotFound(f"credential not found: {ref}") from exc

    def delete(self, ref: str) -> None:
        self.values.pop(ref, None)


def _decode_blob(blob: bytes | str, ref: str) -> str:
    """Decode a CredentialBlob without guessing wildly.

    pywin32 builds differ: current builds return the wide string written via
    CredWrite as raw UTF-16LE bytes; legacy builds return raw UTF-8 bytes.
    - Bytes containing NUL are certainly UTF-16LE (printable UTF-8 never has
      NUL, while ASCII secrets written as str always do);
    - otherwise try strict UTF-8 first (legacy write path), then strict
      UTF-16LE (non-ASCII str write without NUL bytes);
    - anything that still fails raises CredentialReadError explicitly — it must
      NOT surface as "credential not found".
    """
    if isinstance(blob, str):
        return blob
    if isinstance(blob, bytes):
        attempts = []
        if blob.count(0) > 0:
            attempts = [("utf-16-le", lambda: blob.decode("utf-16-le"))]
        else:
            attempts = [
                ("utf-8", lambda: blob.decode("utf-8")),
                ("utf-16-le", lambda: blob.decode("utf-16-le")),
            ]
        for _encoding, decode in attempts:
            try:
                return decode() if callable(decode) else decode
            except UnicodeDecodeError:
                continue
        digest = hashlib.sha256(blob).hexdigest()[:12]
        raise CredentialReadError(
            f"credential decode failed for {ref}: blob_len={len(blob)} "
            f"sha256_prefix={digest} (neither utf-8 nor utf-16-le)"
        )
    raise CredentialReadError(
        f"credential blob has unexpected shape for {ref}: {type(blob).__name__}"
    )


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

        # 当前 pywin32 的 CredWrite 将 CredentialBlob 按 Unicode 字符串封送；
        # 传 bytes 会抛 TypeError（Objects of type 'bytes' can not be converted
        # to Unicode）。写入 str 由 Windows 存为 UTF-16，CredRead 原样返回。
        blob = secret if isinstance(secret, str) else secret.decode("utf-8")
        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": self._target(ref),
                "CredentialBlob": blob,
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                "UserName": "MM-Agent Desktop",
                "Comment": "MM-Agent Desktop provider credential",
            },
            0,
        )

    def get(self, ref: str) -> str:
        import win32cred

        target = self._target(ref)
        try:
            item = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC, 0)
        except Exception as exc:
            winerror = getattr(exc, "winerror", None)
            # 1168 = ERROR_NOT_FOUND, 1169 = ERROR_NO_SUCH_LOGON_SESSION
            if winerror == 1168:
                raise CredentialNotFound(f"credential not found: {ref}") from exc
            raise CredentialReadError(
                f"credential read failed for {ref} (target={target!r}): "
                f"{type(exc).__name__} winerror={winerror} {exc}"
            ) from exc
        return _decode_blob(item.get("CredentialBlob", b""), ref)

    def delete(self, ref: str) -> None:
        import win32cred

        target = self._target(ref)
        try:
            win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC, 0)
        except Exception as exc:
            winerror = getattr(exc, "winerror", None)
            # Only an already-missing target is idempotent.  Any other OS error
            # must stop the caller before SQLite forgets the credential ref.
            if winerror == 1168:
                return
            raise CredentialDeleteError(
                f"credential delete failed for {ref} (target={target!r}): "
                f"{type(exc).__name__} winerror={winerror} {exc}"
            ) from exc

    def describe(self, ref: str) -> dict:
        """Non-secret diagnostic: does the target exist and what is its shape."""
        import win32cred

        target = self._target(ref)
        try:
            item = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC, 0)
        except Exception as exc:
            winerror = getattr(exc, "winerror", None)
            return {
                "ref": ref,
                "target_name": target,
                "found": False,
                "error_class": (
                    "NOT_FOUND" if winerror == 1168 else "READ_FAILED"
                ),
                "winerror": winerror,
                "error": f"{type(exc).__name__}: {exc}",
            }
        blob = item.get("CredentialBlob", b"")
        raw = blob.encode("utf-16-le") if isinstance(blob, str) else blob
        return {
            "ref": ref,
            "target_name": target,
            "found": True,
            "blob_len": len(raw),
            "sha256_prefix": hashlib.sha256(raw).hexdigest()[:12],
            "blob_kind": type(blob).__name__,
        }
