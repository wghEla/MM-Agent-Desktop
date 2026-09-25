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
- S2 DAG layers + pinned per-question sequential layer execution + durable per-question completion checkpoints/resume validation + solver + frozen hashed red-team input package + independent recomputation + compare/arbitration + bounded rework/escalation/degraded-release carriers
- S3 plot runtime → figure review loop + G3
- S4 narrative/draft/chapter-review/blind-reader/integrator/abstract swarm + G4, with persistent paired-review best-version rollback shared with S5
- bounded S5 review arena with page-image judge input, Issue Ledger, channel-aware R45 abstention merge, targeted calc/figure/text repair, persistent best-version snapshots/0.5-noise-band rollback, adaptive four-lane review waves, and resumable round-complete snapshots
- S5a abstract restatement gate
- S5b page-image beautification routing + page guard
- G5 publication gate + stale-value checks + final defect verification
- S6 page review / final fixes / harvest / retrospective + run metrics
- authoritative `PaperFoundryEngine` sequencing S0→S6 with stage checkpoints
- node-level reuse/retry for deterministic role legs
- interrupted-task fail-closed recovery that also closes orphaned RUNNING invocations
- cooperative pause/resume/cancel semantics
- cancellation-aware paper compilation: S4–S6 compile calls run off the sidecar event loop and pass the run CancellationToken into the managed XeLaTeX Job Object path
- shared Windows ProcessManager in the Desktop sidecar for managed Python/XeLaTeX lifecycle; MATLAB helper uses the same process-tree backend; external LaTeX/MATLAB environments are allowlisted so provider/cloud secrets are not inherited
- per-leg adaptive-wave deadlines measured from concurrency-slot acquisition, with awaited timeout cancellation before retry and peer cleanup on programming/runtime exceptions (R60 no-double-writer invariant)
- durable MAX_LEGS / active-time MAX_HOURS enforcement at executable-leg and pipeline boundaries
- durable adaptive wave scheduler: default concurrency 4, 429-triggered decrement to floor 2, one retry, and persisted concurrency state across resume; wired into S1 prototype authoring, S2 escalation variants, S3 plot/review batches, S4 chapter/blind + abstract swarm, and S5 independent review lanes; direct standalone role legs are wrapped as one-job waves, while an outer-wave context suppresses nested retry
- Desktop-facing `RunController`
- persisted run history and restart recovery controls
- provider model/reasoning/max-output/timeout binding
- Windows Credential Manager abstraction; SQLite stores only `api_key_ref`
- provider-profile CRUD/factory API with secret-safe UI projection
- authenticated loopback Python sidecar
- Tauri lifecycle management and authenticated request proxy
- PyInstaller frozen sidecar build using Tauri `externalBin` naming
- Release builds use the bundled sidecar plus an embedded managed Python 3.11 scientific runtime; debug builds may use managed Python for development
- React project/import, Provider Settings, Run Dashboard, run history/control and artifact/image/PDF viewer
- synthetic full-chain test using real S0→S6 stage modules, real Python tool execution and final delivery PDF carrier
- real mid-S1 crash/restart E2E: orphan active invocation → fail-closed recovery → sealed-node reuse → retry → final delivery PDF
- structured failure handling/tests for 429, Python/XeLaTeX/MATLAB timeout paths, managed-process recycle, missing compiler executable, external-tool environment secret boundaries and corrupt PDF carriers
- mechanical cross-stage carrier ownership registry plus consumer-facing Pydantic success-gate schemas for S3 figure reviews, S4 requirement/review/abstract carriers, S5 review envelopes, S5b/S6 page reviews and G5 publication verdicts
- GitHub Actions CI covering Python on Linux/Windows and Windows desktop/bundled-sidecar build
- NSIS release installer production, silent-install verification, installed-app startup smoke and artifact retention

## Evidence already present

- `tests/e2e/test_actual_full_chain.py` drives the actual stage modules through S0→S6 with a scripted mock LLM, real filesystem/Python tools and synthetic compile/render hooks, and requires the complete canonical checkpoint set plus `交付/论文.pdf`.
- the same E2E module contains a real mid-S1 recovery case using a fresh Engine/Provider instance and verifies `pipeline.node_reused`, orphan invocation closure, explicit retry and final delivery.
- `tests/unit/test_budget.py` verifies active runtime excludes pauses and that leg/hour ceilings fail closed.
- S5 resume uses only post-rework `checkpoint.s5_round_complete` snapshots; review-only observations are not treated as durable resume boundaries.
- sidecar tests cover bearer authentication, secret boundaries, provider profiles, graceful shutdown and persisted-run recovery controls.
- The latest **executed** source jobs before the current GitHub Actions provisioning failure are CI #227: Linux 287 passed / 31 skipped and Windows 317 passed / 1 skipped, with Ruff clean on both. These jobs predate the newest wave-timeout and field-schema commits, so they are not evidence for the current HEAD.
- CI #231 was triggered on a later head and failed twice before runner startup: all three jobs returned `steps=null` and `logs_url=null` within seconds. That is an external Actions/runner-provisioning failure, not a code-test result. Current-head claims therefore remain conservative until runners execute again.
- CI #174 remains the last completed installed-release proof.
- CI #174 built the managed scientific runtime and PyInstaller sidecar, produced an NSIS installer, silently installed it, verified the installed `runtime/python.exe`, removed developer-Python PATH/override state, and launched the installed app through `--startup-smoke` successfully.
- the retained Windows installer artifact is `mmagent-desktop-windows-nsis`; the Actions ZIP is 153,590,163 bytes (~153.6 MB decimal).
- Desktop source can create/open projects, import files, configure/test providers, start/pause/resume/cancel runs, reopen persisted runs, inspect dashboards and preview artifacts.

## Still not product-complete

The repository must **not** be described as final v1.0 product-complete yet.

Remaining high-priority work:

1. Recover **current-head executable evidence** once GitHub Actions runners are available again: Linux/Windows Python gates plus NSIS install/startup smoke. The newest wave-timeout, cancellation, environment-boundary and artifact-schema changes must not be promoted to MATCH on source presence alone.
2. Continue the narrower repair-lane / G4–G5 fidelity audit and add installed-product cancellation-during-live-tool failure proof.
3. Extend field-level contracts to the remaining lower-risk carriers/repair receipts; cross-stage ownership and the highest-risk downstream-consumed JSON carriers are already mechanically enforced.
4. Finish run-level provider network/auth propagation failure injection and tighten any broader-than-necessary shared-carrier write scopes.
5. Real-provider smoke testing remains unverified until a credential is supplied through the product UI.

## Evidence discipline

- Historical `v1.0.0` and its “197 passed” result remain historical evidence only.
- Source presence is not sufficient for MATCH: CI/tests/mechanical checks must support fidelity claims. Zero-step Actions provisioning failures are recorded as infrastructure blockers, not converted into either pass or fail evidence for the code.
- Synthetic mock-provider E2E proves orchestration/tool/product wiring, not real-provider compatibility or model quality.
- MockProvider-backed multi-leg wave tests are intentionally serialized because the mock is one linear scripted-turn cursor; real HTTP providers use the bounded concurrent scheduler. Scheduler concurrency/429 behavior is separately tested with real async jobs plus direct-role and outer-wave RateLimitError→QUEUED→retry paths.
- The pinned 5f507e0b S2 source contains a stale comment claiming same-layer modeling parallelism, but its executable loop processes each question pipeline sequentially. Fidelity follows the executable behavior, not the stale comment.
- CI #174 proves installer bundling and installed-app startup without developer Python; model-quality and real-provider behavior remain separate claims.
- Real-provider compatibility must remain explicitly unverified until exercised with a real configured provider.

See:

- `docs/reviews/2026-09-24-fidelity-audit.md` (historical audit)
- `docs/spec/SOURCE_MAP.md`
- `docs/spec/FIDELITY_MATRIX.md`
- draft PR #1
