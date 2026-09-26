# LOCAL_VALIDATION_REPORT

> Date: 2026-09-19
> Branch: `gpt/fidelity-rebuild`
> HEAD SHA: `8e9efd214c943b91dcf5a6a7a8e3c279bb403a9a`
> Working tree: clean (after ruff --fix + lint fixes)

## A. Environment

| Item | Version |
|---|---|
| OS | Windows 11 (10.0.26200 x64) |
| Python | 3.11.9 (.venv managed by uv) |
| Node/npm | v24.18.0 / 11.16.0 |
| Rust | 1.98.1 (D:/dev/rust/cargo) |
| Tauri | 2.x (dependencies declared, not yet built) |
| XeLaTeX | TeX Live 2026 (`D:/Apps/texlive/texlive/2026/bin/windows/xelatex.exe`) |
| MATLAB | R2026a (`D:/Apps/Matlab/bin/matlab.exe`) |

## B. Test Results

| Command | Result | Passed | Failed | Skipped | Duration |
|---|---|---|---|---|---|
| `uv run ruff check .` | exit 0 | — | — | — | <1s |
| `uv run pytest -q` | exit 0 | 342 | 0 | 0 | 85s |

### Test breakdown

- unit: 33 files, all passed
- contracts: 4 files, all passed
- integration: 5 files, all passed
- orchestration: wave timeout tests, all passed
- pipeline: G0/G1/S0/S1/S2/G2/RedTeam/S5, all passed
- ledger: issue_ledger 10 items, all passed
- provider_mocks: 13 items (openai_chat/responses/anthropic/gemini/compatible), all passed
- e2e: actual full chain S0→S6, mid-S1 crash/restart, 429 retry — all passed

### Lint fixes made

| File | Fix |
|---|---|
| `mmagent/orchestration/wave.py` | B023: bind `pass_no=pass_no` in `invoke()` default arg |
| `scripts/build_sidecar.py` | B904: add `from err` to re-raise |
| `scripts/sidecar_entry.py` | I001: sort import block |

### Test data fixes made

| File | Fix |
|---|---|
| `tests/pipeline/test_s5_finalize.py` | Add required `分数` field to S5a verdict mock |
| `tests/e2e/test_actual_full_chain.py` | Add required `分数` field to S5a verdict mock |

These fixes do not change product logic — they align test data with the
`AbstractRestatementVerdict` Pydantic schema (`分数` is required, ge=0, le=10).

## C. Windows Release

### PyInstaller sidecar
- Command: `uv run python scripts/build_sidecar.py`
- Result: **SUCCESS** → `apps/desktop/src-tauri/binaries/mmagent-sidecar-x86_64-pc-windows-msvc.exe`
- PyInstaller onefile mode, includes FastAPI + uvicorn + PyMuPDF + mmagent

### React frontend
- Command: `npm install && npm run build` (in apps/desktop/)
- Result: **SUCCESS** → `apps/desktop/dist/` (157KB gzip 50KB)
- Vite 5.4.21, 30 modules transformed

### Tauri binary
- Command: `cargo build --release` (in apps/desktop/src-tauri/)
- Result: **BLOCKED** — MSVC Build Tools not installed
- Error: `link.exe` resolves to Git Bash's POSIX `link`, not MSVC linker
- Fix needed: Install `Microsoft.VisualStudio.2022.BuildTools` with `VCTools` workload
  (requires admin elevation / UAC approval — winget install fails with 1602)

### NSIS installer
- Not yet attempted (depends on Tauri binary)

### Installed startup smoke
- Not yet attempted (depends on installer)

## D. Baseline notes

- HEAD matches expected `8e9efd2...`
- 342 tests green on Windows 11 / Python 3.11.9
- ruff clean
- No P0 blockers found in this validation pass
