# CURRENT_STATE — fidelity rebuild active

Historical `v1.0.0` is preserved unchanged. Development continues on
`gpt/fidelity-rebuild` through draft PR #1.

## Current source state

### Core/runtime foundations retained

- SQLite authoritative state + append-only events
- task lease/CAS + AgentLoop acceptance boundary
- workspace/path/role permissions, including red-team isolation
- Windows process/cancellation foundation
- five provider protocol adapters
- DAG utilities
- Issue Ledger + guards
- XeLaTeX / MATLAB / Python tooling

### Fidelity rebuild implemented in source

- canonical S0→S6 / G0→G5 topology
- clean-room system prompts for all 17 registered roles
- S1 route scout + real prototype execution + evidence-based tournament plan
- S2 DAG layers + solver + frozen-input red-team recomputation + compare/arbitration + bounded rework/escalation/degraded-release carriers
- S3 plot runtime → figure review loop + G3
- S4 narrative/draft/chapter-review/blind-reader/integrator/abstract swarm + G4
- bounded S5 review arena with page-image judge input, Issue Ledger, targeted calc/figure/text repair and resumable round snapshots
- S5a abstract restatement gate
- S5b page-image beautification routing + page guard
- G5 publication gate + stale-value checks + final defect verification
- S6 page review / final fixes / harvest / retrospective + run metrics
- authoritative `PaperFoundryEngine` sequencing S0→S6 with stage checkpoints
- node-level reuse/retry for deterministic role legs
- interrupted-task fail-closed recovery
- cooperative pause/resume/cancel semantics
- Desktop-facing `RunController`
- persisted run history and restart recovery controls
- provider model/reasoning/max-output/timeout binding
- Windows Credential Manager abstraction; SQLite stores only `api_key_ref`
- provider-profile CRUD/factory API with secret-safe UI projection
- authenticated loopback Python sidecar
- Tauri lifecycle management and authenticated request proxy
- React project/import, Provider Settings, Run Dashboard, run history/control and artifact/image/PDF viewer
- synthetic full-chain test using real S0→S6 stage modules, real Python tool execution and final delivery PDF carrier
- GitHub Actions CI covering Python on Linux/Windows plus Windows frontend/Cargo checks

## Evidence already present

- `tests/e2e/test_actual_full_chain.py` drives the actual stage modules through S0→S6 with a scripted mock LLM, real filesystem/Python tools and a synthetic compile/render hook, and requires the complete canonical checkpoint set plus `交付/论文.pdf`.
- node/round resume primitives are in source for S0/S1/S5/S5a/S5b/G5/S6; interrupted active tasks fail closed before resume.
- sidecar tests cover bearer authentication, secret boundaries, provider profiles, graceful shutdown and persisted-run recovery controls.
- Desktop source is no longer a skeleton: it can create/open projects, import files, configure/test providers, start/pause/resume/cancel runs, reopen persisted runs, inspect dashboards and preview artifacts.

## Still not product-complete

The repository must **not** be described as final v1.0 product-complete yet.

Remaining high-priority work:

1. Obtain a clean CI run at the current branch head. Earlier runs exposed Python lint/import defects and an invalid Windows ICO; fixes have been committed but the replacement head still needs CI proof.
2. Add a true mid-stage crash/restart E2E using real stage implementations, not only unit/control-flow recovery tests.
3. Re-audit S1/S2/S5 against the pinned upstream snapshot for behavioral details that remain simplified (parallel wave scheduling, arbitration/escalation depth, full 18-step review semantics).
4. Finish failure injection across provider 429/network/auth, tool timeout, XeLaTeX/MATLAB absence/failure, corrupted carriers, stale values, hard crash and restart.
5. Package the Python sidecar for distribution and prove the installed Windows application can launch it without a developer Python environment.
6. Build an installer and perform an installed-app smoke test on Windows.
7. Real-provider smoke testing remains unverified until a credential is supplied through the product UI.
8. Refresh `docs/spec/FIDELITY_MATRIX.md` from actual source/tests; its historical NOT IMPLEMENTED rows are stale and must not be used as current completion evidence.

## Evidence discipline

- Historical `v1.0.0` and its “197 passed” result remain historical evidence only.
- Source presence is not sufficient for MATCH: CI/tests/mechanical checks must support fidelity claims.
- Synthetic mock-provider E2E proves orchestration/tool/product wiring, not real-provider compatibility or model quality.
- Windows packaging/installer claims remain unverified until an installed artifact is exercised.

See:

- `docs/reviews/2026-09-24-fidelity-audit.md`
- `docs/spec/SOURCE_MAP.md`
- `docs/spec/FIDELITY_MATRIX.md`
- draft PR #1
