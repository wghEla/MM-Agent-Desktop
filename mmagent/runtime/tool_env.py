"""Sanitized environment builders for trusted external tools.

External compilers need a small subset of the host environment to locate
system DLLs, PATH helpers, temp/home directories and product-specific runtime
configuration. They do not need provider/API credentials inherited by the
sidecar process.
"""
from __future__ import annotations

import os
from collections.abc import Iterable

_BASE_KEYS = (
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "COMSPEC",
    "PATHEXT",
    "WINDIR",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "COMMONPROGRAMFILES",
    "APPDATA",
    "LOCALAPPDATA",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "TEMP",
    "TMP",
    "HOME",
    "USER",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    "PATH",
)

_TEX_KEYS = (
    "TEXMFHOME",
    "TEXMFVAR",
    "TEXMFCONFIG",
    "TEXMFCACHE",
    "TEXINPUTS",
    "BIBINPUTS",
    "BSTINPUTS",
    "MIKTEX_USERCONFIG",
    "MIKTEX_USERDATA",
    "MIKTEX_USERINSTALL",
)

_MATLAB_KEYS = (
    "MLM_LICENSE_FILE",
    "LM_LICENSE_FILE",
    "MATLAB_PREFDIR",
)


def sanitized_external_env(extra_keys: Iterable[str] = ()) -> dict[str, str]:
    """Return an allowlisted subprocess environment.

    extra_keys must contain only explicitly justified tool-runtime variables.
    Provider/cloud credentials are intentionally not inherited.
    """
    env: dict[str, str] = {}
    for key in (*_BASE_KEYS, *tuple(extra_keys)):
        value = os.environ.get(key)
        if value:
            env[key] = value
    env.setdefault("PATH", os.environ.get("PATH", os.defpath))
    return env


def latex_env() -> dict[str, str]:
    return sanitized_external_env(_TEX_KEYS)


def matlab_env() -> dict[str, str]:
    return sanitized_external_env(_MATLAB_KEYS)
