"""Build the self-contained Windows Python 3.11 scientific runtime.

The frozen API sidecar is not a general-purpose Python interpreter. User/model
scripts therefore execute with this separately bundled managed runtime.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "apps" / "desktop" / "src-tauri" / "resources" / "runtime"
PYTHON_VERSION = os.environ.get("MMAGENT_RUNTIME_PYTHON_VERSION", "3.11.9")
PYTHON_TAG = "311"

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


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MM-Agent-Desktop managed runtime builder"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.write_bytes(response.read())


def _configure_embedded_python(runtime: Path) -> None:
    pth = runtime / f"python{PYTHON_TAG}._pth"
    if not pth.is_file():
        raise FileNotFoundError(f"embedded Python path file missing: {pth}")
    lines = [line.rstrip() for line in pth.read_text(encoding="utf-8").splitlines()]
    if "Lib/site-packages" not in lines:
        lines.append("Lib/site-packages")
    lines = ["import site" if line.strip() == "#import site" else line for line in lines]
    if "import site" not in lines:
        lines.append("import site")
    pth.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_runtime() -> Path:
    if os.name != "nt":
        raise SystemExit("managed runtime build is Windows-only")

    shutil.rmtree(RUNTIME, ignore_errors=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)

    archive_url = (
        f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
        f"python-{PYTHON_VERSION}-embed-amd64.zip"
    )
    with tempfile.TemporaryDirectory(prefix="mmagent-python-runtime-") as raw:
        archive = Path(raw) / "python-embed.zip"
        _download(archive_url, archive)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(RUNTIME)

    _configure_embedded_python(RUNTIME)
    site_packages = RUNTIME / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-compile",
            "--only-binary=:all:",
            "--target",
            str(site_packages),
            *SCIENTIFIC_PACKAGES,
        ],
        cwd=ROOT,
        check=True,
    )

    python = RUNTIME / "python.exe"
    smoke = (
        "import numpy,pandas,scipy,matplotlib,sklearn,sympy,statsmodels,"
        "openpyxl,xlrd,docx,pypdf,fitz,PIL,networkx,pydantic;"
        "print('managed-runtime-ok')"
    )
    subprocess.run([str(python), "-X", "utf8", "-c", smoke], cwd=ROOT, check=True)

    manifest = {
        "python_version": PYTHON_VERSION,
        "architecture": "amd64",
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
