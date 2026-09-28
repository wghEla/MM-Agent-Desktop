"""Build the self-contained Windows Python 3.11 scientific runtime.

The API sidecar is frozen with PyInstaller, but model-authored scripts require a
real interpreter.  We therefore package a relocatable uv-managed CPython 3.11
distribution plus the modeling scientific stack as a Tauri resource.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "apps" / "desktop" / "src-tauri" / "resources" / "runtime"

SCIENTIFIC_PACKAGES = (
    "numpy",
    "pandas",
    "scipy",
    "matplotlib",
    "scikit-learn",
    "sympy",
    "statsmodels",
    "openpyxl",
    "xlrd",
    "python-docx",
    "pypdf",
    "PyMuPDF",
    "Pillow",
    "networkx",
    "pydantic",
)


def _uv() -> str:
    executable = shutil.which("uv")
    if executable is None:
        raise RuntimeError("uv executable not found; install the package build extra")
    return executable


def _python_root(python: Path, install_root: Path) -> Path:
    """Find the relocatable distribution root that owns python.exe + Lib/."""
    current = python.parent
    install_root = install_root.resolve()
    while True:
        if (current / "Lib").is_dir() and (current / "python.exe").is_file():
            return current
        if current == install_root or install_root not in current.parents:
            break
        current = current.parent
    raise RuntimeError(f"unable to locate relocatable Python root for {python}")


def build_runtime() -> Path:
    if os.name != "nt":
        raise SystemExit("managed runtime build is Windows-only")

    uv = _uv()
    shutil.rmtree(RUNTIME, ignore_errors=True)
    RUNTIME.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="mmagent-managed-python-") as raw:
        install_root = Path(raw) / "python"
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)
        env.update(
            {
                "UV_PYTHON_INSTALL_DIR": str(install_root),
                "UV_PYTHON_PREFERENCE": "only-managed",
                "UV_PYTHON_NO_REGISTRY": "1",
                "UV_NO_PROJECT": "1",
                # Never make the packaged runtime depend on uv's package cache.
                "UV_LINK_MODE": "copy",
            }
        )

        subprocess.run(
            [
                uv,
                "python",
                "install",
                "3.11",
                "--install-dir",
                str(install_root),
                "--no-registry",
            ],
            cwd=ROOT,
            env=env,
            check=True,
        )
        candidates = sorted(
            install_root.glob("cpython-3.11*/python.exe"),
            reverse=True,
        )
        if candidates:
            source_python = candidates[0].resolve()
        else:
            resolved = subprocess.check_output(
                [uv, "python", "find", "3.11", "--no-project"],
                cwd=ROOT,
                env=env,
                text=True,
            ).strip()
            source_python = Path(resolved).resolve()
        source_root = _python_root(source_python, install_root)

        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(source_python),
                "--no-build",
                "--break-system-packages",
                "--link-mode",
                "copy",
                *SCIENTIFIC_PACKAGES,
            ],
            cwd=ROOT,
            env=env,
            check=True,
        )

        shutil.copytree(source_root, RUNTIME)

    python = RUNTIME / "python.exe"
    version = subprocess.check_output(
        [str(python), "--version"], cwd=ROOT, text=True
    ).strip()
    if not version.startswith("Python 3.11."):
        raise RuntimeError(f"unexpected managed runtime version: {version}")

    smoke = (
        "import numpy,pandas,scipy,matplotlib,sklearn,sympy,statsmodels,"
        "openpyxl,xlrd,docx,pypdf,fitz,PIL,networkx,pydantic;"
        "print('managed-runtime-ok')"
    )
    subprocess.run([str(python), "-X", "utf8", "-c", smoke], cwd=ROOT, check=True)

    manifest = {
        "python_version": version.removeprefix("Python "),
        "provider": "uv/python-build-standalone",
        "architecture": "x86_64-windows",
        "packages": list(SCIENTIFIC_PACKAGES),
    }
    (RUNTIME / "MMAGENT_RUNTIME.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(python)
    return python


if __name__ == "__main__":
    build_runtime()
