# Fidelity Audit — 2026-09-24

Baseline branch: `main` @ `db9881c308ece5e8ab2f77f2a16711478547304c`  
Reference target: `qybaihe/MM-Final-Skill`, project-pinned snapshot `5f507e0b`  
Audit branch: `gpt/fidelity-rebuild`

## Executive finding

The repository contains a substantial runtime/kernel foundation, but the current `v1.0.0` completion claim is not supported by the implementation state.

The core product target remains a high-fidelity independent desktop reimplementation of MM-Final-Skill paper-foundry, not a generic multi-agent runtime.

## Evidence-backed contradictions

1. `docs/CURRENT_STATE.md` says:
   - “MM-Final-Skill 客户端化复现完成”
   - “S0-S6 流水线”
   - “G0-G5 门检”

2. The source tree currently contains only:
   - pipeline: `s0_s1.py`, `s2_model.py`, `s5_review.py`
   - gates: `g0.py`, `g2.py`
   - contracts: S0 and S2 contracts only

3. `docs/spec/FIDELITY_MATRIX.md` still marks the majority of A/B/C/D mechanisms as `NOT IMPLEMENTED`, including S3, S4, G3, G4, S5a, S5b, G5 and S6.

4. `mmagent/mm/roles/prompts.py` contains complete clean-room prompts for only:
   - reader
   - answer_predictor
   - planner

   The registry has 17 role metadata entries, but that is not equivalent to 17 implemented role behaviors.

5. `tests/e2e/test_full_pipeline.py` is named “full pipeline” but explicitly tests only:
   `S0 → G0 → S1 → G1`.

6. Desktop is still a shell:
   - `apps/desktop/src/App.tsx`: title + placeholder comment
   - `apps/desktop/src-tauri/src/main.rs`: bare Tauri builder
   - no Python sidecar lifecycle
   - no IPC/HTTP bridge
   - no Provider Settings / Run Dashboard / Artifact Viewer / PDF preview

## What is genuinely implemented

The following are real engineering assets and should be preserved:

- SQLite authoritative state and append-only events
- task/run state machine
- workspace/path/permission boundary
- Windows process management / cancellation foundation
- provider abstraction and normalization
- tool-calling AgentLoop
- role registry and red-team permission isolation
- DAG utilities
- S0/S1 implementation
- partial S2 / red-team / escalation implementation
- partial S5 review arena and Issue Ledger
- change/structure/page guard foundations
- XeLaTeX / MATLAB tooling
- project/dashboard Python APIs
- mock-provider test harness

## Critical fidelity gaps

### P0 — product-definition gaps

- No complete S0→S6 orchestrator.
- S3 missing.
- S4 missing.
- G3/G4/G5 missing.
- S5a/S5b missing.
- S6 missing.
- No real desktop-to-Python runtime bridge.
- No complete application E2E from project creation/import through final PDF.

### P1 — behavioral fidelity gaps

- 17 role prompts/contracts are not implemented as executable role packages.
- S1 “战略锦标赛” is materially simplified.
- S2 red-team independent recomputation/arbitration/repair/escalation behavior is incomplete.
- S5 loop contains placeholders, including escalation/fuse behavior.
- Full stale-value / change-manifest propagation is incomplete.
- G2 semantics need parity review against the pinned reference.
- Runtime pause/resume/checkpoint behavior is not yet equivalent to paper-foundry boundary semantics.
- Provider real-world integration remains unverified.

### P1 — evidence/test gaps

- “197 passed” is not evidence of full product coverage.
- Existing E2E does not exercise S2–S6.
- No synthetic end-to-end run produces a final PDF through the intended full chain.
- No desktop E2E.
- No packaged Windows install/launch verification.

## Implementation strategy

Do not rewrite the stable kernel.

### Phase F1 — Fidelity core
1. Freeze a machine-readable stage/node graph for S0–S6 and G0–G5.
2. Implement missing contracts first.
3. Implement missing 14 role prompts/role packages.
4. Implement S3 + G3.
5. Implement S4 + G4.
6. complete S5/S5a/S5b + G5.
7. implement S6 + retrospective/run metrics.
8. add one authoritative orchestrator with checkpoint/resume semantics.

### Phase F2 — Desktop bridge
Use:
`React → Tauri 2 → managed Python sidecar/API → existing mmagent runtime`

The Python core remains the business-state authority. Rust should not duplicate pipeline logic.

### Phase F3 — Product E2E / hardening
A synthetic project must prove:

`create project → import problem → configure mock provider → start → S0…S6 → compile PDF → inspect artifacts → crash/recover → resume → final delivery`

Then add failure injection for:
- 429
- provider timeout/failure
- tool timeout
- XeLaTeX missing/failure
- MATLAB missing/failure
- corrupted artifacts
- stale values
- crash during tool execution
- cancel / pause / resume

## Versioning correction

Do not move or rewrite the existing `v1.0.0` tag. Preserve it as historical evidence.

Future work should proceed from a new development line. The old tag should be documented as a premature release rather than silently retagged.

## First engineering target

The first code change after this audit should be the fidelity skeleton:
- canonical stage graph
- missing contract boundaries
- missing gate interfaces
- role prompt registry completeness test

Only after the domain pipeline is structurally complete should the desktop UI be treated as product-complete.
