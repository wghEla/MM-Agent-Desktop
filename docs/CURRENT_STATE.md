# CURRENT_STATE — fidelity rebuild active

Historical `v1.0.0` is preserved unchanged. Development continues on
`gpt/fidelity-rebuild` through draft PR #1.

## Verified source state

### Core/runtime foundations retained

- SQLite authoritative state + append-only events
- task lease/CAS + AgentLoop acceptance boundary
- workspace/path/role permissions, including red-team isolation
- Windows process/cancellation foundation
- five provider protocol adapters
- DAG utilities
- Issue Ledger + core guards
- XeLaTeX / MATLAB tools

### Fidelity rebuild implemented in source

- canonical S0→S6 / G0→G5 topology
- clean-room system prompts for all 17 registered roles
- S3 plot → runtime execution → figure review loop + G3
- S4 narrative/draft/chapter-review/blind-reader/integrator/abstract swarm + G4
- bounded S5 review arena with role-scoped repair routes and ledger checkpoints
- S5a abstract restatement gate
- S5b page-image beautification routing + page guard
- G5 publication gate + stale-value checks + final defect verification
- S6 page review / final fixes / harvest / retrospective
- authoritative `PaperFoundryEngine` sequencing S0→S6 with stage checkpoints
- checkpoint-based resume + interrupted-task fail-closed recovery
- cooperative stage-boundary pause
- cancellation correctly closes runs as CANCELLED rather than FAILED
- Desktop-facing in-process `RunController`
- profile alias normalization (`standard`/标准 etc.)
- provider model binding so historical `model="mock"` task placeholders resolve to the configured real model
- provider reasoning / max-output / timeout binding
- Windows Credential Manager abstraction; SQLite stores only `api_key_ref`
- provider-profile CRUD/factory API with secret-safe UI projection
- GitHub Actions CI for Python (Linux/Windows) and Desktop build checking

## Still not complete

The project must **not** be described as product-complete yet.

Remaining high-priority work:

1. Full synthetic E2E through the real `PaperFoundryEngine`: import → S0…S6 → final PDF.
2. Prove pause/resume/crash recovery using the real stage implementations, not only orchestration fakes.
3. Close remaining S1/S2 fidelity gaps (true route tournament/prototypes, red-team compare/arbitration depth, escalation/degraded-release evidence).
4. Re-audit S5 against the upstream 18-step round semantics and G5 calc/figure/text rework paths.
5. Add sidecar transport API around the Python control plane.
6. Connect Tauri lifecycle to the managed Python sidecar.
7. Implement React pages: projects/import, Provider Settings, Run Dashboard, ledger, artifact/PDF viewer.
8. Package and launch-test the Windows application.
9. Run full failure injection: 429/provider/tool/XeLaTeX/MATLAB/corrupt artifact/stale value/crash/cancel.
10. Real-provider smoke test remains unverified until the user supplies a credential through the product UI.

## Evidence discipline

Historical “197 passed” refers only to the old covered surface and is not a full-product
acceptance signal. New fidelity work is gated by GitHub CI and new E2E evidence.

See:

- `docs/reviews/2026-09-24-fidelity-audit.md`
- `docs/spec/SOURCE_MAP.md`
- `docs/spec/FIDELITY_MATRIX.md`
- draft PR #1
