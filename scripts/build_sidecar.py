"""Build the Python sidecar in Tauri externalBin naming convention."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts" / "sidecar_entry.py"
TAURI_BIN = ROOT / "apps" / "desktop" / "src-tauri" / "binaries"
NAME = "mmagent-sidecar"


def _target_triple() -> str:
    configured = os.environ.get("TAURI_ENV_TARGET_TRIPLE")
    if configured:
        return configured.strip()
    try:
        return subprocess.check_output(
            ["rustc", "--print", "host-tuple"],
            text=True,
            cwd=ROOT,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as err:
        verbose = subprocess.check_output(["rustc", "-Vv"], text=True, cwd=ROOT)
        for line in verbose.splitlines():
            if line.startswith("host: "):
                return line.split(":", 1)[1].strip()
        raise RuntimeError("unable to determine Rust host target triple") from err


def build_sidecar() -> Path:
    triple = _target_triple()
    extension = ".exe" if "windows" in triple else ""
    TAURI_BIN.mkdir(parents=True, exist_ok=True)
    destination = TAURI_BIN / f"{NAME}-{triple}{extension}"

    with tempfile.TemporaryDirectory(prefix="mmagent-sidecar-") as raw:
        temp = Path(raw)
        dist = temp / "dist"
        work = temp / "work"
        spec = temp / "spec"
        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            NAME,
            "--distpath",
            str(dist),
            "--workpath",
            str(work),
            "--specpath",
            str(spec),
            str(ENTRY),
        ]
        subprocess.run(command, cwd=ROOT, check=True)
        produced = dist / f"{NAME}{extension}"
        if not produced.is_file():
            raise FileNotFoundError(f"PyInstaller output missing: {produced}")
        shutil.copy2(produced, destination)

    print(destination)
    return destination


if __name__ == "__main__":
    build_sidecar()
