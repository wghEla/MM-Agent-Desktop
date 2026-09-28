# LOCAL_HANDOFF_REPORT

Last updated: 2026-09-28 after UI v2 local validation and GPT external review.

## Source of truth

| Item | Value |
|---|---|
| Repository | `wghEla/MM-Agent-Desktop` |
| Branch | `gpt/fidelity-rebuild` |
| Last fully locally verified HEAD | `ffe179354e80a98f9d3a074aeacfaf95712e552a` |
| Verified regression | 464 passed / 0 failed; Ruff clean; frontend build green |
| Installed smoke | NSIS rebuilt/reinstalled; `--startup-smoke` exit 0 |
| UI v2 local validation | PASS |
| Current remote | contains external-review dependency pin cleanup after the verified HEAD |
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

## Remaining product work

1. UI v2 Phase 2 remainder:
   - workspace file tree;
   - first-run onboarding;
   - project/open dialog polish.
2. UI v2 Phase 3:
   - provider preset/catalog polish;
   - capability-driven fields;
   - formal OAuth extension point (only where compliant).
3. One stronger-model / ZCode API real-provider green-G0 run.
4. CI acceptance decision.
5. Explicit acceptance or closure of remaining low-risk fidelity deviations.

Do not reopen broad Source/Pipeline fidelity review unless a concrete defect appears.

Do not merge `main`, tag a final release, force-push, or spend GitHub Actions quota without
explicit user direction.
