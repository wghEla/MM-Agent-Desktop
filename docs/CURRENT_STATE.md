# CURRENT_STATE — fidelity rebuild on gpt/fidelity-rebuild

Branch: `gpt/fidelity-rebuild`
HEAD: `08f9900b8861b754df5c53a6ca4e124e78a0ffb0`
Tests: **last verified: 394 passed / 0 failed + Ruff clean at `e80856e`; current HEAD source-only patches are UNVERIFIED**

## Version tags (historical, unchanged)

v0.1.0 → v0.2.0 → v0.3.0 → v0.4.0 → v0.5.0 → v0.6.0 → v0.8.0 → v1.0.0

## Current work

Fidelity rebuild continues on `gpt/fidelity-rebuild`.
FIDELITY_MATRIX has been updated to reflect current state.

### Recently completed

- G5 rework loop with R49 figure route, R50 calc shelve, R51 compile-before-recheck, R52 page guard
- G4 abstract-1-page check (aux abstract:end label)
- S6 retrospective/feedback schemas (RetrospectiveReport/RunMetrics)
- Provider failure propagation tests (auth/network/429/5xx at AgentLoop level)
- Tool environment security boundary tests (secrets excluded from xelatex/matlab)
- Repair receipt schemas (S5/S5b/G5/S6)
- Issue Ledger with generation CAS + receipt_id idempotency + state transition table
- PyInstaller sidecar build verified
- React frontend build verified (vite 157KB)

### Remaining PARTIAL items

- A6: Red-team recompute protocol parity
- A7: Terminology vs numeric disagreement edge cases
- A8: Arbitration depth/archive parity
- A11: Escalation swarm full evidence parity
- A15: S4 editorial-guard ordering parity
- A17: S5 repair-lane order parity
- A19: S5a/S5b cosmetic-loop parity
- B7: Hard/correctness escalation parity
- B9: Complete appendix/title rules
- B11: Per-file fingerprint parity
- B12: Full calc→figure→text propagation proof
- B14: Full durable invalidation-and-rerun proof
- C1-C17: Per-role schema parity
- D5: Full beauty threshold convergence proof
- D8-D10: Full behavioral parity for all three profiles

### Blocked

- MSVC Build Tools (needs UAC elevation, user must approve)
- Real-provider smoke (needs API key from user)


## External source review — 2026-09-27

GPT-5.6 Sol source review: **HOLD (P0=0, P1=6, P2=5)**.

Review file:
`docs/reviews/v1.0.0-rebuild-external-review-round1.md`

Reviewer source patches after the 394-test baseline:
- strict generation/receipt identity and generation-local attempt semantics;
- deterministic runtime-owned S5 repair receipt identity/routing;
- fail-closed G5 ledger restore;
- S6 delivery now includes ledger/review evidence;
- A1/A17/A20/B7 downgraded to PARTIAL pending real closure.

No tests were run after these review patches because execution quota was unavailable.
Do not report current HEAD as regression-verified until local focused + full regression is run.
