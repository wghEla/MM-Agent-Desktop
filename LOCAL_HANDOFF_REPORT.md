# LOCAL_HANDOFF_REPORT

Last updated: 2026-09-28 after UI v2 Phase-3 (Provider UX) Windows local validation.

## Source of truth

| Item | Value |
|---|---|
| Repository | `wghEla/MM-Agent-Desktop` |
| Branch | `gpt/fidelity-rebuild` |
| Last fully locally verified HEAD | tip of `gpt/fidelity-rebuild` after the Phase-3 validation commits (`644aae5` test alignment + docs/evidence; source baseline `feae95f`) — see `docs/CURRENT_STATE.md` |
| Verified regression at that HEAD | 526 passed / 0 failed; Ruff clean; frontend build green |
| Installed smoke at that HEAD | NSIS rebuilt/reinstalled; `--startup-smoke` exit 0; 0 orphan; installed fake-credential round-trip; CM test credentials cleaned |
| Current remote | updated by this round's push |
| Phase-3 evidence state | **LOCAL VALIDATION PASS** |
| Product release | not yet final GO (Phase 4 open) |

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
| UI v2 Phase 3 (Provider UX) | **PASS** |

## UI v2 Phase-3 local validation summary

Validated at source HEAD `feae95f` on a real Tauri dev runtime against a local scripted
relay (`127.0.0.1:28911`); only a fake `sk-fake-…-TESTONLY` marker key was ever used, and
all test credentials were removed from Credential Manager at the end of the round.

Verified: 7-preset Provider Catalog with Runtime capability pills; fixed-preset Base URL
lock (OpenAI) vs editable ZCode preset; Compatible auth_style=none keyless save (key+none
→ 400); GET-only model discovery with dedup + stable sort + manual fallback + custom
`models_path` round-trip; pre-save Test Connection via ephemeral `/providers/test-config`
(nothing persisted, 0 CM entries); single-flight probes (double-click under 2 s relay
delay ⇒ exactly one request); create → auto-select; credential bound to protocol+base_url
(400 on endpoint edits while keyed, allowed after clear); save/clear/replace key with no
secret echo in UI or SQLite; keyless→API-key Bearer/x-api-key chooser with the chosen
header actually transmitted; two-step delete with secret-first ordering (1168 idempotent,
others fail-closed); §29 model-existence FAIL verdict rendered in UI; error redaction
(`***REDACTED***`); unsafe Base URL / endpoint-path forms denied; OAuth fail-closed; visual
checklist at 1440×900 / 1280×800 / ≈1100×760 logical (200% scale).

Evidence:
- `docs/reviews/v1.0.0-rebuild-ui-v2-phase3-local-validation.md`
- `docs/runs/ui-v2-phase3/` (17 screenshots + EVIDENCE.md)

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

## UI v2 Phase-3 source handoff

Phase 2 is fully locally validated. Current unverified source work is Phase 3 only.

Implemented after the verified `3fbc6bc` baseline:

- provider catalog + capability metadata;
- model discovery/manual fallback;
- configured-model connection validation;
- pre-save Test Connection with ephemeral credentials only;
- Provider create/edit/delete;
- Credential Manager replace/clear;
- Compatible capability/auth/path configuration;
- endpoint/protocol credential scoping;
- transient/persisted URL/header/path validation;
- fail-closed credential deletion;
- OAuth extension registry contract with no advertised/registered OAuth provider.

Security invariants added in this round:

1. a saved API key cannot follow a Provider to a different protocol/Base URL;
2. `auth_style=none` cannot coexist with a saved/transient Compatible credential;
3. secret-bearing custom headers are rejected;
4. Base URLs cannot contain userinfo/query/fragment credentials;
5. Compatible endpoint paths must remain relative to the configured provider host;
6. Discover Models never performs a generation fallback;
7. pre-save Test Connection does not persist the profile/key;
8. Windows credential deletion errors other than NOT_FOUND fail closed before SQLite drops
   the reference.

OAuth remains a **non-operational extension point**. Do not show an account-login button
until a documented third-party flow is implemented under MM-Agent's own registered client.

## Remaining product work

1. ~~ZCode local Windows validation of UI v2 Phase 3 current HEAD~~ — done 2026-09-28 (PASS).
2. One stronger-model / ZCode API real-provider full-green G0 run.
3. CI acceptance decision.
4. Explicit acceptance or closure of remaining low-risk fidelity deviations.

Do not reopen broad Source/Pipeline fidelity review unless a concrete defect appears.

Do not merge `main`, tag a final release, force-push, or spend GitHub Actions quota without
explicit user direction.
