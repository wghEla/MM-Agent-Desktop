# Fidelity Re-audit — 2026-09-25

Branch: `gpt/fidelity-rebuild`  
PR: #1  
Historical baseline: `main` @ `db9881c` / preserved `v1.0.0` tag  
Reference: pinned `qybaihe/MM-Final-Skill` snapshot recorded by the project

## Executive finding

The 2026-09-24 audit is no longer an accurate description of this branch.

The rebuild now contains an authoritative S0→S6 engine, G0→G5 gates, executable
17-role paper-foundry behavior, real prototype/red-team/figure/paper/review/finalization
stages, a desktop control plane, crash-safe durable state, and a self-contained Windows
distribution path.

CI #174 is the first end-to-end release proof. Follow-up source hardening is additionally green in CI #208 at the Python layer (Linux 272 passed / 31 skipped; Windows 302 passed / 1 skipped; Ruff clean):

- Linux: **262 passed / 31 skipped**, Ruff clean.
- Windows: **292 passed / 1 skipped**, Ruff clean.
- PyInstaller sidecar build + executable smoke: PASS.
- managed Python 3.11 scientific runtime build + package import smoke: PASS.
- React build + Tauri Release + NSIS: PASS.
- silent NSIS install: PASS.
- installed `runtime/python.exe` present: PASS.
- with developer Python removed from PATH and no external `MMAGENT_PYTHON`,
  installed `mmagent-desktop.exe --startup-smoke` starts the bundled sidecar,
  passes authenticated readiness, and exits 0: PASS.
- retained installer Actions artifact ZIP: **153,590,163 bytes**.

The correct current label is therefore:

**feature-complete distributable beta / fidelity-hardening in progress**

This is materially stronger than “core implemented”: the Windows application is now
mechanically buildable, installable and self-starting without a developer Python.

## Previous P0 findings

| 2026-09-24 gap | Current status |
|---|---|
| complete S0→S6 orchestrator missing | CLOSED |
| S3 missing | CLOSED |
| S4 missing | CLOSED |
| G3/G4/G5 missing | CLOSED |
| S5a/S5b missing | CLOSED |
| S6 missing | CLOSED |
| desktop-to-Python runtime bridge missing | CLOSED |
| synthetic full application-domain E2E missing | CLOSED |
| bundled Windows sidecar/runtime path missing | CLOSED |
| installer / installed-app startup proof missing | CLOSED by CI #174 |

There are currently **no known source-structure P0 gaps** equivalent to those in the
2026-09-24 audit.

## Strongest evidence

### 1. Actual-stage full-chain E2E

`tests/e2e/test_actual_full_chain.py` executes the real stage modules S0→S6 with:

- real workspace/state/event machinery;
- real filesystem and Python tools;
- scripted mock LLM only at the provider boundary;
- canonical stage checkpoints;
- final `交付/论文.pdf`.

### 2. Real mid-stage crash recovery

A second E2E leaves an S1 task and invocation active, constructs a fresh Engine/Provider,
and requires:

- orphan task/invocation fail-closed recovery;
- sealed-node reuse rather than repeat model spend;
- explicit retry of the interrupted node;
- final S0→S6 completion and PDF delivery.

### 3. Review-loop hardening

Current S4/S5 review loops now have:

- a shared persistent best-retention implementation; 
- S4 chapter review compares the prior visible snapshot to the current paper and rolls back a worse version;
- adaptive bounded waves for S4 chapter/blind review, abstract candidates and S5 independent review lanes;

Current S5 additionally has:

- post-rework durable round checkpoints;
- Issue Ledger generation-CAS verdicts and receipt idempotency;
- R45 channel-aware abstention merge:
  judge-only unverifiable negatives abstain rather than veto;
- persistent pre-review TeX snapshots;
- paired relative judgment best-retention;
- 0.5 score-noise fallback;
- actual rollback to the prior snapshot;
- rolled-back repair receipts reopened instead of remaining falsely resolved.

The pinned `5f507e0b` reference contains `审稿达标=8.6` and
`审稿平台期=0.15` as configuration values but does not read them in S5.
Its current S5 exits on blocking-ledger convergence, round cap, or budget; score is
diagnostic. The rebuild intentionally follows that observed behavior rather than
inventing an inactive threshold exit.

### 4. Runtime safety and budgets

- one workspace owner via `run.lock`;
- task lease/CAS;
- process-tree cancellation;
- pause/resume/cancel;
- durable MAX_LEGS;
- active-time MAX_HOURS excluding PAUSED intervals;
- crash recovery closes orphan RUNNING invocations transactionally;
- malformed/stale receipts and verdict generations fail closed.

### 5. Desktop and distribution

- bearer-authenticated loopback FastAPI sidecar;
- Tauri authenticated request proxy and lifecycle ownership;
- Windows Credential Manager secret boundary;
- Provider Settings, project/import, run history/control, Dashboard, artifact/image/PDF views;
- PyInstaller frozen sidecar;
- embedded managed Python 3.11 scientific runtime;
- NSIS installer;
- installed-release startup smoke without developer Python.

## Remaining P1 fidelity / release-confidence work

### 1. Remaining timeout / recycle parity

Adaptive concurrency and retry semantics are now mechanically closed:

- default wave concurrency = 4;
- provider 429 returns the task to durable QUEUED state;
- the next retry/wave reduces concurrency by 1 down to floor 2;
- failed/rate-limited jobs get one retry;
- concurrency reduction is persisted as events and survives resume;
- S1 prototype authoring, S2 escalation variants, S3 plot/review batches, S4 review/abstract waves and S5 review lanes use it;
- direct standalone role legs use the same one-job-wave wrapper, while an active outer-wave context suppresses nested retry.

The pinned 5f507e0b S2 driver contains a stale source comment saying same-layer modeling is parallel, but its executable loop is sequential per question. The rebuild now matches that mechanical behavior and adds durable per-question S2 checkpoints: a completed PASS is reused only after G2 carrier revalidation, while a missing degraded-release carrier invalidates the checkpoint and reruns the question.

The remaining resilience gap is full timeout/dead-process recycle parity, especially whole-process-tree timeout handling for external XeLaTeX/MATLAB executions, plus narrower repair-lane details.

### 2. Failure injection

Already covered: 429 retry, Python tool timeout/tree kill, cancellation, orphan recovery,
missing compiler executable, corrupt PDF, stale values and several state/adversarial cases.

Still worth closing:

- XeLaTeX timeout and nonzero compile failure;
- MATLAB timeout/nonzero failure;
- provider auth failure/network timeout;
- additional corrupt-carrier cases.

### 3. Producer/consumer contract audit

Artifact/schema enforcement exists, but the entire stage graph has not yet been
mechanically checked for:

`consumer required fields ⊆ producer guaranteed fields`.

### 4. Real-provider smoke

This remains deliberately **unverified**. Offline protocol tests and mock-provider E2E
are not substitutes for one real end-to-end configured endpoint. No claim of
real-provider-tested should be made until a credential is supplied through the product
boundary and a real run is exercised.

## Product assessment

The branch is now a functioning, installable Windows paper-foundry client rather than a
runtime skeleton. It is suitable for continued beta/hardening work.

It should remain a draft PR until:

1. the remaining high-value fidelity deviations (especially timeout/dead-process recycle parity and narrower repair/gate parity) are closed or explicitly accepted;
2. installed scientific-runtime relocation smoke is green on the final head;
3. failure-injection coverage is considered sufficient for release;
4. producer/consumer contracts are mechanically audited or explicitly accepted;
5. real-provider smoke status is explicit and truthful.

The historical `v1.0.0` tag must remain untouched.
