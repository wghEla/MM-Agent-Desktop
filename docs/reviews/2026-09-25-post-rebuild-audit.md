# Fidelity Re-audit — 2026-09-25

Branch: `gpt/fidelity-rebuild`  
PR: #1  
Historical baseline: `main` @ `db9881c` / preserved `v1.0.0` tag  
Reference: pinned `qybaihe/MM-Final-Skill` snapshot recorded by the project

## Executive finding

The 2026-09-24 audit is no longer an accurate description of this branch.

The rebuild has crossed the structural/product boundary that was missing yesterday:
the repository now contains an authoritative S0→S6 engine, G0→G5 gates, executable
role legs, real prototype/red-team/figure/paper/review/finalization stages, a desktop
control plane, a managed sidecar path, full-chain synthetic E2E, and durable resume
semantics.

That does **not** make the product final. The remaining gaps are now narrower and
mostly concern release proof, real-provider proof, and several high-fidelity upstream
behaviors rather than missing core stages.

## P0 status from the previous audit

| Previous P0 gap | 2026-09-25 status |
|---|---|
| complete S0→S6 orchestrator missing | CLOSED in source + E2E |
| S3 missing | CLOSED |
| S4 missing | CLOSED |
| G3/G4/G5 missing | CLOSED |
| S5a/S5b missing | CLOSED |
| S6 missing | CLOSED |
| desktop-to-Python runtime bridge missing | CLOSED in source/integration tests |
| full application-domain E2E to final PDF missing | CLOSED for synthetic runtime chain; installed desktop E2E still open |

## Strongest evidence now present

1. **Actual-stage full-chain E2E**
   - `tests/e2e/test_actual_full_chain.py`
   - real stage modules S0→S6
   - real filesystem/Python tools
   - final `交付/论文.pdf`
   - canonical stage checkpoint set required

2. **Real mid-stage recovery E2E**
   - S0 + early S1 legs execute and seal normally
   - an S1 node is left with an active lease + RUNNING invocation
   - a fresh Engine/Provider instance resumes the same durable run
   - orphan invocation is failed closed
   - already sealed nodes emit `pipeline.node_reused`
   - interrupted node retries with incremented attempt
   - execution still reaches final delivery PDF

3. **S5 durable round resume**
   - only post-rework `checkpoint.s5_round_complete` events are resume boundaries
   - review-only observation events cannot be mistaken for durable completion
   - Issue Ledger snapshots preserve generation/state across resume

4. **Run budgets**
   - profile MAX_LEGS enforced using durable task count
   - MAX_HOURS enforced using accumulated RUNNING intervals
   - PAUSED time excluded
   - checks occur before executable role legs and at pipeline boundaries

5. **Desktop/runtime bridge**
   - bearer-authenticated loopback FastAPI sidecar
   - Tauri authenticated request proxy
   - create/open/import/provider/run/dashboard/artifact APIs
   - run history + detached RUNNING/PAUSED recovery controls
   - graceful shutdown before forced termination fallback
   - Windows Credential Manager boundary for API secrets

6. **Distribution path**
   - PyInstaller one-file sidecar builder
   - Tauri `externalBin` integration
   - release code path uses bundled sidecar instead of system Python
   - Windows CI has exercised frozen-sidecar creation and direct executable smoke
   - NSIS installer production is now configured as a CI gate

## Remaining P0 release blockers

These are release blockers for calling the desktop product complete; they are not
missing-domain-stage blockers.

1. **Current-head CI must be green.**
   The latest hardening/packaging commits must pass Python Linux, Python Windows,
   frozen-sidecar build, frontend build, Rust check and NSIS bundle creation together.

2. **Installed-app launch proof is still missing.**
   A generated installer must be installed in a clean Windows environment and the
   installed application must prove it can start the bundled sidecar without a
   developer Python installation.

3. **Real-provider smoke is still missing.**
   Offline protocol tests and mock-provider E2E are not evidence that a real configured
   OpenAI/Anthropic/Gemini/compatible endpoint works end-to-end.

## Remaining P1 fidelity gaps

1. **Parallel wave scheduling / adaptive concurrency**
   - DAG layers exist, but most role execution remains sequential.
   - typed 429 handling returns the task to QUEUED.
   - upstream-style dynamic concurrency reduction (default 4 → floor 2) is not yet reproduced.

2. **S5 scoring / plateau / best-retention parity**
   - review arena, targeted repair, Issue Ledger, fuse/escalation carriers and publication gate exist.
   - the pinned reference's exact 8.6 target / 0.15 plateau / rollback-best semantics are not yet fully reproduced.

3. **Best-retention / rollback package**
   - no sufficient evidence yet for the full upstream best-version retention and 0.5 noise-band behavior.

4. **Additional failure injection**
   - 429, Python timeout, cancellation, orphan recovery and several corrupt-state cases are covered.
   - XeLaTeX/MATLAB timeout/failure, provider auth/network failures and more corrupt-carrier paths should still be closed.

5. **Producer/consumer contract audit**
   - artifact/schema enforcement exists.
   - exhaustive consumer-required fields ⊆ producer-guaranteed fields has not been mechanically proven for every stage boundary.

## Product assessment

The branch is no longer a “kernel with a fake v1.0 label.” It is now a functioning
paper-foundry reimplementation with a real desktop control plane and distribution path.

The correct current label is:

**feature-complete core / release-hardening in progress**

It should remain a draft PR until the release blockers above are closed.

## Merge rule

Do not merge solely because the test count is high. Merge readiness requires:

- current-head CI green on Linux + Windows;
- NSIS bundle successfully produced;
- installed Windows app launches bundled sidecar without developer Python;
- remaining intentional fidelity deviations are documented;
- real-provider smoke status is explicit and truthful.
