# LOCAL_HANDOFF_REPORT

Last updated: 2026-09-29 after final release-candidate source review.

## Source of truth

| Item | Value |
|---|---|
| Repository | `wghEla/MM-Agent-Desktop` |
| Branch | `gpt/fidelity-rebuild` |
| Last fully locally verified executable baseline | `6d5a1133e5eb81d054b0bf0d845e3695c60bfd76` |
| Baseline regression | 526 passed / 0 failed; Ruff clean; frontend build green |
| Baseline package | sidecar + Tauri/NSIS rebuilt; silent reinstall; startup smoke 0 |
| Baseline installed Provider smoke | fake credential restart/Test/Delete + CM cleanup PASS |
| Current remote state | docs release disposition + S0/G0 producer-contract hardening after `6d5a113` |
| Current remote verification | SOURCE-ONLY; final local regression/repackage required |
| Product release | final real-provider green-G0 gate open |

## Gate status

| Gate | Status |
|---|---|
| Source / Pipeline | GO — no known open P0/P1 |
| Windows Package | PASS at last tested baseline |
| Installed Cancellation | PASS |
| Installed Credential | PASS |
| UI v2 Phase 1 | PASS |
| UI v2 Phase 2 | PASS |
| UI v2 Phase 3 | PASS |
| UI v2 Phase 4 | PASS by evidence aggregation |
| CI acceptance | RESOLVED — ADR-0001 local Windows evidence substitute |
| Fidelity residual PARTIALs | ACCEPTED for v1.0.0; remain honestly PARTIAL |
| Real Provider | CONDITIONAL PASS; one stronger/stable simultaneous green G0 remains |
| Current exact HEAD regression/package | PENDING after S0 producer-contract hardening |

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

## Final release-candidate handoff

### Already closed

Do not repeat these gates unless the final current-head regression exposes a concrete
regression:

- UI v2 Phase 1–4;
- Windows package/install/startup;
- installed cancellation/process-tree cleanup;
- installed Credential Manager lifecycle;
- Provider catalog/model discovery/pre-save Test/endpoint binding/OAuth fail-closed;
- broad source/pipeline fidelity review;
- CI acceptance-rule debate;
- residual low-risk fidelity parity polishing.

### Current source-only delta

`mmagent/mm/pipeline/s0_s1.py` now projects the canonical Pydantic schemas for
`ProblemContract` and `DataArchive` into the Reader instruction, binds those schemas
to the Reader's expected artifacts, and supplies shared required top-level envelope-key
lists. `ExpectedArtifact.required_json_keys` enforces those keys before defaults can hide
omissions; G0 uses the same ProblemContract required-key constant.

Intent:

- canonical Chinese contract field names are visible before generation;
- `题目`/English synonym drift cannot seal S0.2 as SUCCEEDED;
- validation happens at artifact acceptance, before G0;
- G0 remains unchanged/fail-closed.

Distinguishing test added in `tests/pipeline/test_s0_s1.py`.

### Only remaining execution work

The next local round must:

1. pull the exact current HEAD;
2. run focused S0/G0 + provider tests;
3. run full pytest + Ruff + frontend build;
4. rebuild sidecar + Tauri/NSIS and reinstall the exact current HEAD;
5. run startup smoke;
6. user manually enters real ZCode/stronger-provider Base URL + API Key + exact Model ID
   through Provider Settings;
7. Test Connection;
8. run a minimal installed-product S0→G0 path;
9. require S0.2 + S0.3 + canonical contract/data archive + mechanically generated matrix +
   G0 PASS in the **same run**;
10. record provider/model host/model ID but never the credential;
11. secret scan;
12. clean normal exit / no orphan;
13. update final gate docs.

The credential must never be pasted into chat, committed, logged, screenshotted or written to
evidence.

### Final stop condition

If the current-head regression/package checks are green and the stronger/ZCode run records a
durable G0 PASS with no new P0/P1:

- Real Provider → PASS;
- release-candidate evidence is complete;
- perform one final GPT-5.6 Sol release review;
- then user may authorize the final `v1.0.0` tag / merge decision.

Do not run GitHub Actions solely for acceptance; ADR-0001 resolves that requirement.

Do not reopen accepted PARTIAL parity rows unless the final real-provider run exposes a
concrete defect.
