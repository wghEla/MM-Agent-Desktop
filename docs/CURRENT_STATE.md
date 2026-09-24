# CURRENT_STATE — fidelity rebuild in progress

- **Historical tag**: `v1.0.0` remains preserved at its original commit.
- **Development branch**: `gpt/fidelity-rebuild`.
- **Reason for rebuild**: the historical completion claim is not supported by the source tree or the fidelity matrix.
- **Audit baseline**: `docs/reviews/2026-09-24-fidelity-audit.md`.

## Verified implementation state

### Implemented foundations

- SQLite authoritative state + append-only events
- AgentLoop / tool-calling runtime
- workspace / path / permission controls
- provider abstraction
- Windows process/cancellation foundation
- 17-role metadata registry and red-team permission isolation
- DAG utilities
- S0/S1 implementation
- partial S2 implementation
- partial S5 review arena / Issue Ledger / guards
- XeLaTeX / MATLAB tools
- Python project/dashboard APIs
- Tauri 2 + React **skeleton**

### Not yet product-complete

The following must not be described as implemented until source + tests prove them:

- complete authoritative S0→S6 orchestrator
- S3
- G3
- S4
- G4
- S5a
- S5b
- G5
- S6
- complete 17-role clean-room prompts/contracts
- desktop ↔ Python sidecar/API bridge
- Provider Settings UI
- Run Dashboard UI
- Artifact/PDF viewer
- packaged Windows application
- real full-chain E2E producing the final PDF

## Current engineering target

1. Freeze canonical pipeline topology in code.
2. Add missing contract/gate boundaries.
3. Complete 17 role behaviors.
4. Fill S3/S4/S5a/S5b/G5/S6.
5. Add a single authoritative orchestrator with checkpoint/resume semantics.
6. Only then complete the desktop product layer.
7. Final acceptance requires a synthetic end-to-end project that reaches final PDF plus failure-injection recovery.

## Historical test count

The historical branch reported **197 passed + ruff clean**. This demonstrates stability of covered components only; the existing `tests/e2e/test_full_pipeline.py` covers S0→G0→S1→G1 rather than the complete product chain.

## Source of truth

Read in this order:

1. `00_MM_AGENT_MASTER_PLAN.md`
2. `docs/reviews/2026-09-24-fidelity-audit.md`
3. `docs/spec/SOURCE_SNAPSHOT.md`
4. `docs/spec/SOURCE_MAP.md`
5. `docs/spec/FIDELITY_MATRIX.md`
6. `docs/spec/KNOWN_DEVIATIONS.md`
