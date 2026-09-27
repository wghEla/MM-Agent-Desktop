# CURRENT_STATE — fidelity rebuild on gpt/fidelity-rebuild

Branch: `gpt/fidelity-rebuild`
HEAD: Round-2 P1 closure implementation (see "External source review Round 2 — closure" below)
Tests: **locally verified: 416 passed / 0 failed + Ruff clean** (full suite, this HEAD)

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


## External source review Round 2 — 2026-09-27

Review:
`docs/reviews/v1.0.0-rebuild-external-review-round2.md`

Verdict: **HOLD**.

Round-1 P1 status after source audit:
- P1-1 Ledger identity: CLOSED on the 408-test baseline.
- P1-2 G5 closure: OPEN — Engine wiring exists, but G5 repair does not transition/durably persist Issue Ledger state.
- P1-3 S5 fuse escalation: OPEN — role leg exists, but no required receipt/verdict; final-round fuse processing is still skipped.
- P1-4 degraded-release contract: reviewer source-patched S2/G5 to the unified carrier; review-level runtime producer still missing.
- P1-5 S6 TOCTOU: reviewer source-patched final-revision mechanical G5 recheck; unique terminal current-PDF defect review still missing.
- P1-6 fidelity evidence inflation: OPEN — several tests still prove manually-created events/source presence instead of production behavior.

Round 2 reviewer patches are source-only and must be locally regression-tested before any of the above source patches are called closed.


## External source review Round 2 — closure — 2026-09-27

All Round-2 reviewer patches were locally regression-tested (full suite green),
then each OPEN P1 was closed with production-path implementations and real
`run_s5()` / `run_g5_rework()` / `run_s6()` behavior tests:

- **P1-2 G5 authoritative closure — CLOSED.** `run_g5_rework` now requires
  repair receipts from figure (`审稿/回执_G5R{n}_图问{q}.json`) and text
  (`审稿/回执_G5R{n}_文.json`) legs, injects them via `收回执` (待复核),
  applies per-issue hunter verdicts with generation CAS via `收裁定`
  (已消解/未消解), upserts exact degraded-release records for calc items
  (preserving S2 question entries), durably writes the ledger carrier back
  every round, and restores disclosed-degraded items to 搁置 after the
  bounded extra chances (items without a record stay active → fail-closed).
  Tests: `test_s5_finalize.py::test_g5_rework_figure_receipt_then_verdict_resolves_issue`,
  `::test_g5_rework_calc_upsert_preserves_s2_entries`,
  `::test_g5_rework_stale_verdict_generation_is_rejected`.
- **P1-3 S5 fuse escalation — CLOSED.** Escalation runs a real role leg with
  a required receipt (`审稿/回执_升格_{id}_g{gen}.json`), status-gated
  `s5.escalation_started/succeeded/failed` events, runtime-owned `收回执`,
  once-per-(issue,generation) via event query, post-fuse convergence
  re-check, and final-round fuse processing. Also fixed a latent
  `len(bool)` crash in the `checkpoint.s5_escalation_extension` event.
  Tests: `test_s5_review.py::test_s5_escalation_runs_real_leg_then_degrades_after_exhaustion`,
  `::test_s5_escalation_leg_without_receipt_fails_and_degrades_later`.
- **P1-4 degraded-release producer — CLOSED.** When an escalation for
  (issue, generation) already ran and the issue is still a fuse candidate,
  the Runtime registers an exact degraded-release record
  (`upsert_degraded_review_issue`, preserving S2 namespace) and shelves the
  issue with `s5.degraded_release_registered`. G5's re-shelve closure then
  honors the disclosed record at the publication gate.
- **P1-5 S6 terminal review — CLOSED.** After S6's own fixes and final
  compile, S6 reruns mechanical G5 and adds a fresh terminal current-PDF
  defect review (unique `S6:出版终审` node + `审稿/S6终审复核.json`;
  `defect_hunter` write scope extended). Harvest happens only after both
  pass. Test: `test_s6_finalize.py::test_s6_terminal_defect_review_gates_harvest`.
- **P1-6 evidence inflation — CLOSED for the flagged items.** The manual
  event-append escalation tests were deleted and replaced by the real-path
  tests above; `TestG5Rework` import/no-op tests superseded by behavioral
  G5 rework tests. A17/A20/B7/A21 matrix evidence updated accordingly.

Next: round-3 external review with the regenerated packet.
