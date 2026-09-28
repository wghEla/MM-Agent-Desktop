# LOCAL_HANDOFF_REPORT

Last updated: 2026-09-28 after UI v2 Phase-2 local validation.

## Source of truth

| Item | Value |
|---|---|
| Repository | `wghEla/MM-Agent-Desktop` |
| Branch | `gpt/fidelity-rebuild` |
| Source HEAD under validation | `3d83004d43ae64dd30949d5ea5d1abfda0bc0d6d` (phase-2 source) |
| Final tested state | `3d83004` + phase-2 local fix commits (sidecar OSError→409/400 detail) |
| Verified regression | 466 passed / 0 failed; Ruff clean; frontend build green |
| Installed smoke | NSIS rebuilt/reinstalled; `--startup-smoke` exit 0; 0 orphan |
| UI v2 Phase 1 | PASS (`ffe1793` baseline) |
| UI v2 Phase 2 | PASS (this round) |
| Product release | not yet final GO |

## Gate status

| Gate | Status |
|---|---|
| Source / Pipeline | GO |
| Windows Package | PASS |
| Installed Cancellation | PASS |
| Installed Credential | PASS |
| Real Provider | CONDITIONAL PASS |
| UI v2 Phase 1 + native picker/recent workspace | PASS |
| UI v2 Phase 2 (tree/onboarding/dialogs) | PASS |

## UI v2 verified state

The installed Windows build was exercised through real Tauri UI interaction at multiple
window sizes / high DPI.

Verified:

- three-pane Workspace / Pipeline / Artifacts shell;
- S0-S6 / G0-G5 StageRail projected only from Dashboard/Runtime state;
- Provider Settings modal with presets, credential status, Test Connection and Advanced;
- native Tauri folder picker for workspace create/open;
- native multi-file picker for problem/data import;
- Recent Workspace bookmark persistence across application restart;
- run history and control gating;
- text / JSON / image / PDF artifact preview;
- Runtime fail-closed failure surfaced correctly in the UI.

Evidence:
- `docs/reviews/v1.0.0-rebuild-ui-v2-local-validation.md`
- `docs/runs/ui-v2/`

## UI v2 architecture boundary

UI remains a projection of the authenticated sidecar and SQLite runtime.

It does not own or infer:

- S0-S6 / G0-G5 truth;
- task status;
- ledger state;
- frozen truth;
- cancellation;
- credential truth.

Recent Workspace localStorage data is bookmark/presentation state only.

## Authentication boundary

Production credential path remains Windows Credential Manager.

UI must not implement:

- browser cookie import;
- session-token extraction;
- borrowed first-party OAuth clients;
- plaintext key persistence in SQLite/localStorage/logs.

Account login is only enabled in the future for providers with an explicit supported
third-party OAuth / device flow.

## Real Provider state

Installed product has already proven:

- credential write/restart/fresh-sidecar read;
- Test Connection;
- real generation;
- real tool calling;
- real S0 legs;
- Runtime fail-closed schema gate behavior.

The remaining Real Provider item is one ceremonial full-green G0 run using a stronger or
more stable model/provider. The prior Groq run was limited by model schema variance and
free-tier rate limiting; no open product defect is implicated.

## External-review cleanup after ffe1793

GPT external review found one reproducibility issue and one documentation-truth issue:

1. Tauri JS packages had caret ranges even though local validation proved release builds
   reject incompatible JS/Rust minor combinations. The verified JS minors are now pinned
   exactly in package.json/package-lock.json.
2. ZCode created a second `docs/LOCAL_HANDOFF_REPORT.md` while this root file already
   existed. This root file remains the canonical handoff; the duplicate is removed.

These cleanup edits are source-only until the next local `npm ci && npm run build`.

## Phase-2 source work after the verified ffe1793 baseline

Implemented on the current remote, but not yet locally validated:

- bounded authenticated Runtime-backed workspace file tree;
- workspace file preview through the existing Artifact dock;
- automatic file-tree/artifact refresh after imports and during active runs;
- first-run onboarding (工作区 → 模型 → 材料);
- dedicated native-picker create/open dialogs with in-dialog backend errors;
- remove-from-recent bookmark action that never deletes a workspace;
- focused sidecar integration test for tree/read scope and .mmagent denial;
- exact pinning of the Tauri JS minors already proven compatible with the release build.

Runtime/Gate/Credential semantics were not intentionally changed.

## Remaining product work

1. ZCode local validation of the current Phase-2 source HEAD.
2. UI v2 Phase 3:
   - provider preset/catalog polish;
   - model discovery / manual fallback;
   - capability-driven fields;
   - formal OAuth extension point (only where compliant).
3. One stronger-model / ZCode API real-provider green-G0 run.
4. CI acceptance decision.
5. Explicit acceptance or closure of remaining low-risk fidelity deviations.

Do not reopen broad Source/Pipeline fidelity review unless a concrete defect appears.

Do not merge `main`, tag a final release, force-push, or spend GitHub Actions quota without
explicit user direction.
