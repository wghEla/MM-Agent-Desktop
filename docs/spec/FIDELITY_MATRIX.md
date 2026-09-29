# FIDELITY_MATRIX — MM-Final-Skill 复现保真矩阵

> Reference: pinned `qybaihe/MM-Final-Skill` snapshot recorded in `SOURCE_SNAPSHOT.md`.
>
> Status meanings:
> - **MATCH**: the mechanically observable behavior is implemented and has focused test evidence.
> - **PARTIAL**: meaningful implementation exists, but one or more upstream semantics or acceptance proofs remain incomplete.
> - **NOT IMPLEMENTED**: no sufficient implementation evidence.
> - **DEVIATION**: intentionally replaced by a different mechanism; see `KNOWN_DEVIATIONS.md`.
>
> This matrix is intentionally conservative. Source presence alone is not enough for MATCH.

## A. Stages and gates

| # | Mechanism | Status | Current evidence / remaining gap |
|---|---|---|---|
| A1 | S0 problem digestion / contract / prediction / trace matrix | PARTIAL | Reader→prediction→mechanical matrix→G0 is implemented, but explicit upstream seed/health-check decomposition is not present/proven. The added fidelity test exercises `check_g0`, not `run_s0`, so it is not sufficient MATCH evidence. |
| A2 | G0 contract gate | MATCH | `gates/g0.py`, `test_g0_gate.py` |
| A3 | S1 strategic tournament with real prototypes | PARTIAL | `s1_tournament.py`, adaptive bounded prototype-authoring wave + real prototype execution + `test_s1_tournament.py`; exact upstream route scoring/selection parity remains under audit |
| A4 | G1 route/plan/prototype evidence gate | MATCH | G1 profile semantics + `test_g1_profile_semantics.py` |
| A5 | S2 dependency DAG layered execution | MATCH | `run_s2` follows the pinned 5f507e0b executable behavior: topological layer barriers with per-question sequential execution inside each layer despite the upstream stale “并行” source comment. Durable `checkpoint.s2_question` events skip fully completed questions on resume, mechanically revalidate PASS carriers, and fail closed when a degraded-release carrier is missing; focused pipeline tests cover ordering, reuse and invalidation. |
| A6 | Red-team independent recomputation | PARTIAL | hard read isolation, independent `复算.py`, frozen hashed input packages and tests; exact upstream recompute protocol still under audit |
| A7 | Distinguish terminology vs numeric disagreement | MATCH | compare/G2 logic distinguishes 口径 vs 数值; RedTeamDiscrepancy.type field and G2 tolerance check in `test_s2_redteam.py` |
| A8 | Arbitration / interpretation responsibility assignment | PARTIAL | arbitration legs exist; depth and archive parity still under audit |
| A9 | Per-question G2 | MATCH | `gates/g2.py` with 5 mechanical checks (metrics/rt/arb/solver/experiment) + `TestG2GateModule` |
| A10 | Normal repair bounded to ≤2 | MATCH | bounded rework constant and S2 control flow |
| A11 | Escalation swarm (3 variants + adjudication + recheck) | PARTIAL | executable 3-variant escalation path exists and variant authoring uses the adaptive wave scheduler; full evidence parity pending |
| A12 | Degraded release with unresolved evidence | MATCH | Full chain verified locally at the 451-test run: S5 Runtime-owned producer (`upsert_degraded_review_issue` after escalation exhaustion, `s5.degraded_release_registered` — `test_s5_escalation_runs_real_leg_then_degrades_after_exhaustion`); G5 exact `(id,generation)` consumption and fail-closed without prior approval (`test_g5_calc_blocker_without_prior_degraded_approval_fails_closed`); S6 Runtime-owned delivery disclosure `交付/交付报告.md` listing degraded questions, exact review `(id,generation)` entries, every non-已消解 ledger row and run metrics, generated mechanically (never by the model) — `test_s6_delivery_report_discloses_degraded_state` proves 审-9-01/generation=2/升级已耗尽 appears in the final delivery report; sync-failure blocks harvest (`test_s6_figure_sync_failure_blocks_harvest`). |
| A13 | S3 figure evidence + two-round figure review | MATCH | `s3_figures.py`, adaptive plotter/reviewer waves, plot runtime, `test_s3_figures.py` |
| A14 | G3 mechanical figure gate | MATCH | 16–22 figures, schematic/diversity/caption checks + `test_g3_gate.py` |
| A15 | S4 narrative → paper → chapter/blind review → integrate → abstract swarm | PARTIAL | full source path exists; chapter/blind and abstract candidates use bounded waves, and chapter review has persistent best-version rollback; exact upstream editorial-guard ordering/parity remains under audit |
| A16 | G4 paper gate | MATCH | compile/page/abstract-1-page/audit/src/trace/matrix checks exist + `test_g4_gate.py` + `TestG4AbstractPage` |
| A17 | S5 18-step review-round semantics | PARTIAL | Core review/rework/ledger/checkpoint loop implemented, including R45, rollback, final-round fuse processing and production-path escalation evidence. Round-4 moved bounded compile/fix before the durable round checkpoint and the change was locally regression-verified in the Round-4 closure (448 passed / 0 failed). Remaining gap: exact upstream 18-step evidence parity, not a known release-integrity defect. |
| A18 | Reviewer A/B + defect hunter + judge simulator + mechanical lane | MATCH | four independent role legs, page-image judge input, mechanical lane; pipeline tests |
| A19 | S5a abstract finalization / S5b beautification | PARTIAL | both implemented and tested; upstream cosmetic-loop parity still under audit |
| A20 | G5 publication gate | PARTIAL | `run_g5_rework` is a real Issue-Ledger closure with generation-CAS verdicts, exact degraded-release consumption and a figure transaction (Plotter → Runtime plot → guarded Writer sync → Runtime ledger receipt). Round-4 fixed the figure-to-Writer-only fallthrough bypass and requires Page Guard + Defect Hunter PASS before a rework round can end; these fixes were locally regression-verified (448 passed / 0 failed). Remaining gap: exact upstream R49–R52/multi-question parity audit. |
| A21 | S6 final page review / fixes / harvest / retrospective | PARTIAL | implemented with run metrics, retrospective schema (`s6_contracts.py`), resumable legs; S6 now reruns mechanical G5 plus a fresh terminal current-PDF defect review (unique `S6:出版终审` node + `审稿/S6终审复核.json`) after its own fixes, and harvest happens only after both pass (`test_s6_finalize.py::test_s6_terminal_defect_review_gates_harvest`); installed-product delivery proof pending |

## B. Loops, ledger, and guards

| # | Mechanism | Status | Evidence / gap |
|---|---|---|---|
| B1 | Issue Ledger five-state machine | MATCH | `issue_ledger.py`, `test_issue_ledger.py` |
| B2 | Issue identity merge / reopen / severity only rises | MATCH | location + similarity thresholds and generation tracking tested |
| B3 | Repair receipts / unknown-id ignore / attempt accounting | MATCH | receipt idempotency + generation CAS in ledger tests |
| B4 | Reviewer-only paired verdict / missed verdict reopens | MATCH | verdict generation CAS + fail-closed missed verdict behavior |
| B5 | R45 abstention-vote merge semantics | MATCH | only judge-simulator unverifiable negatives abstain; substantive unresolved votes veto, resolved votes otherwise resolve, and all-abstention cases fall through to missed-verdict reopen; focused tests cover all three cases |
| B6 | Convergence = no blocking active issues | MATCH | ledger convergence mechanically checks blocking severities |
| B7 | Fuse after ≥2 attempts | MATCH | Verified escalation at the 448-test local run (HEAD = Round-4 fixes): 算-class escalation now runs the full verified cascade (3 variants → 获胜变体 adjudication → Runtime promotion → red-team → G2 → downstream recompute → manifests → plots → guarded writer sync → ledger receipt); 文-class runs a guarded 0.70 repair; failed/missed-verdict escalations never authorize degradation; the final-round extension round is real and recoverable. Real-path tests: `test_round3_closures.py::test_s5_calc_escalation_promotes_winner_to_canonical_truth`, `test_s5_review.py::test_s5_escalation_*`, `test_s5_final_round_successful_escalation_gets_one_review_extension`. |
| B8 | Change Guard 0.45 / 0.70 | MATCH | `change_guard` is invoked by the shared `guarded_text_repair` primitive (normal 0.45, escalated 0.70) which is production-wired into S4 directed revision/integration, S5 normal text repair, S5 text escalation, S5 figure/calc dependent-text sync, S5b beauty repair, G5 text repair, G5 figure sync, S6 terminal repair, and compile repair. Distinguishing tests: `test_round3_closures.py::test_change_guard_reverts_broad_late_writer_rewrite` and `::test_escalated_change_guard_uses_070_limit` (same texts fail 0.45, pass 0.70). |
| B9 | Structure Guard | PARTIAL | Structure Guard is now enforced on all late writer paths via the shared guarded repair primitive (durable `.mmagent/guard_snapshots/` baseline, revert+receipt-cleanup on failed/reverted legs — `test_round3_closures.py::test_guard_snapshot_survives_resume_after_role_success`, `::test_reverted_guarded_repair_deletes_stale_receipt`), with R38③ appendix-list, R68⑤ body-graphics and R47 content-based code-chapter rules. Remaining gap (P2-1): master-plan core-structure-file and problem-chapter-count invariants are not yet explicit guard rules. |
| B10 | Page Guard | MATCH | +max(10%,2 pages) and sudden-drop guard implemented/tested |
| B11 | Integrator/frozen-fact guard | PARTIAL | editorial/frozen-input protections exist, but complete per-file fingerprint parity not proven |
| B12 | Version-change manifest / stale-value guard | PARTIAL | stale-value scan exists and is wired into G5; full calc→figure→text propagation proof pending |
| B13 | Best-retention / rollback package / 0.5 noise band | MATCH | shared retention runtime persists pre-review TeX snapshots for S4/S5; relative verdict wins, 0.5 score drop is the fallback, prior files are restored, and S4/S5 integration tests prove rollback behavior |
| B14 | Cascade recomputation / downstream invalidation | MATCH | At HEAD `f17d248` (locally verified): S2 replays checkpoint + invalidation events in event-id order, so `pipeline.s2_downstream_invalidated` is a durable tombstone that survives crash/restart; S5 calc cascade emits the same tombstones. Real-path tests: `test_s2_pipeline.py::test_s2_resume_replays_downstream_invalidation_tombstone`, `::test_s2_reexecuted_upstream_cascade_invalidates_downstream_checkpoints`, and `test_round3_closures.py::test_s5_calc_repair_runs_solver_redteam_g2_and_downstream`. |

## C. Roles and legs

| # | Mechanism | Status | Evidence / gap |
|---|---|---|---|
| C1–C17 | 17 paper-foundry roles | PARTIAL | all 17 have registry metadata, clean-room prompts, permissions/reasoning routing and tests; not represented as upstream-style independent `role.yaml` packages and per-role schema parity is incomplete |
| C18 | Role reasoning tiers | MATCH | `ROLE_REASONING_TIERS`, role tests |
| C19 | Red-team hard isolation | MATCH | permission layer denies solver/interpreter scopes; integration tests |
| C20 | Leg success cannot be self-declared by model | MATCH | expected-artifact verification + sealing + transactional success boundary; kernel acceptance tests |

## D. Profiles and thresholds

| # | Item | Upstream value | Status | Evidence / gap |
|---|---|---:|---|---|
| D1 | Red-team relative tolerance | 0.01 | MATCH | `Thresholds.red_team_relative_tolerance` + G2 logic/tests |
| D2 | Figure review rounds / threshold | 2 / 7.0 | MATCH | thresholds + S3 tests |
| D3 | Chapter review rounds / threshold | 2 / 7.0 | MATCH | thresholds + S4 tests |
| D4 | Review target / plateau | 8.6 / 0.15 | MATCH | constants are retained, and the pinned 5f507e0b driver never reads them; current upstream S5 exits on blocking-ledger convergence / round cap / budget, with score diagnostic only |
| D5 | Beauty threshold | 8.5 | PARTIAL | value present; full upstream use in convergence path not fully proven |
| D6 | Change guard / escalated guard | 0.45 / 0.70 | MATCH | thresholds + guard implementation/tests |
| D7 | Default concurrency / 429 floor | 4 / 2 | MATCH | durable adaptive wave scheduler starts at 4, persists 429-triggered decrements, floors at 2, retries failed/rate-limited jobs once, and has focused + real AgentLoop 429 tests |
| D8 | Deep profile | routes3 / abstract5 / review4 / beauty2 / 600 / 40h | PARTIAL | profile values + durable leg/hour budget enforcement match; full all-role high-effort semantics remain under audit |
| D9 | Standard profile | abstract3 / review3 / role tiers / 30h | PARTIAL | values/routing + durable active-time enforcement exist; remaining gap is upstream behavioral parity rather than missing budget guard |
| D10 | Quick profile | hard-question tournament / routes2 / review2 / beauty1 / 20h | PARTIAL | values exist; exact hard-question-only tournament behavior remains under audit |
| D11 | ≤20 pages / 16–22 figures / src≥0.6 / decimals≤4 | PARTIAL | thresholds and several gates/audit checks exist; complete combined publication proof pending |

## E. Runtime and resilience

| # | Mechanism | Status | Evidence / gap |
|---|---|---|---|
| E1 | One owner per workspace | MATCH | `run.lock` + PID liveness + tests |
| E2 | Node/stage/S2-question/S5-round resume; active residue fail-closed | MATCH | real mid-S1 orphan invocation recovery E2E proves fail-closed closure, sealed-node reuse, retry and completion to final PDF; S2 per-question checkpoints skip completed driver work only after carrier revalidation and invalidate broken degraded carriers; S5 round-complete snapshots are separately tested. |
| E3 | Pause / resume / cancel + process-tree cleanup | MATCH | Installed Cancellation Gate proves the packaged product can cancel a real long-running Runtime-owned Python parent+child Job Object tree through the authenticated product boundary, reach durable CANCELLED within 0.7 s, kill parent+child, freeze post-cancel writes, survive full app restart without auto-resume, leave 0 owned orphans, and successfully run new work afterwards. Report: `docs/reviews/v1.0.0-rebuild-installed-cancellation-gate.md`. |
| E4 | Layered timeout / recycle before reassignment | PARTIAL | Source now implements the pinned R60 invariant in the new runtime: each wave leg starts its deadline only after acquiring a concurrency slot; timeout cancellation is awaited before retry, preventing old/new double writers; programming exceptions cancel+await peer legs; default wave deadline is 1300s and S4/S5 review waves retain 3600s. Python/XeLaTeX share the Windows Job Object ProcessManager, MATLAB helper uses the same backend, and external-tool envs are allowlisted. Focused timeout/recycle tests exist, but latest-head CI has not executed because GitHub Actions jobs are currently failing before runner startup. |
| E5 | 429 handling and concurrency reduction | MATCH | typed `RateLimitError` → durable QUEUED is wired through adaptive 4→2 waves with one retry. Context-aware `run_role_leg` gives direct standalone legs the same one-job-wave retry semantics while an active outer wave owns retry/concurrency to prevent double retry; focused tests cover direct and nested/outer-wave paths. |
| E6 | MAX_LEGS / MAX_HOURS emergency budget guard | MATCH | durable task count + accumulated RUNNING intervals are checked before executable role legs and at pipeline boundaries; pause time is excluded; unit tests cover both ceilings |
| E7 | JSON repair loop | PARTIAL | tool-call malformed JSON recovery exists; full artifact-schema rewrite loop parity incomplete |
| E8 | Compile repair loop | MATCH | Bounded compile-repair protocol with stage-scoped node/receipt identity and guarded writer mutation (no cross-stage node collisions; repair legs run behind Change+Structure guards with durable snapshots). Wired into S4 final compile, S5b initial compile and G5 rework R51. Tests: `test_s5_finalize.py::test_compile_repair_*` (all pass at HEAD `f17d248`). |
| E9 | Run feedback ledger / metrics | MATCH | S6 event/task metrics → `审稿/回流账.json` + tests |
| E10 | Producer/consumer contract enforcement | PARTIAL | Cross-stage carrier ownership is now mechanically registered and rejects orphan/backward/self-feed mistakes. High-risk S3/S4/S5/S5b/G5/S6 JSON carriers are wired to `ExpectedArtifact.schema_model` so malformed figure reviews, requirement coverage, chapter/blind/abstract verdicts, S5 review envelopes, page-review routing and G5 publication verdicts fail before sealing. Exhaustive field-level schemas for every remaining carrier/receipt are still incomplete, and the newest additions await executable current-head CI evidence. |

## F. Desktop/product delivery (new client layer)

These are product requirements introduced by the independent desktop reimplementation rather than upstream shell-script fidelity.

| # | Mechanism | Status | Evidence / gap |
|---|---|---|---|
| P1 | Authenticated loopback Python sidecar | MATCH | bearer token, loopback bind, shutdown path, sidecar API tests |
| P2 | Secret-safe Provider Settings | MATCH | Windows Credential Manager abstraction; SQLite stores credential reference only; secret-boundary tests |
| P3 | Tauri starts/stops/proxies sidecar | MATCH | authenticated proxy/lifecycle source plus CI #174 installed-release startup smoke proves bundled-sidecar launch and health readiness |
| P4 | Project create/open/import | MATCH | sidecar endpoints + React panel + artifact API tests |
| P5 | Run start/pause/resume/cancel | MATCH | controller/sidecar/UI + integration tests |
| P6 | Restart recovery from persisted Run history | MATCH | persisted run listing, detached RUNNING/PAUSED resume controls and safe cancel tests |
| P7 | Dashboard / gates / event view | MATCH | React Dashboard + sidecar dashboard endpoint |
| P8 | Artifact/image/PDF viewer | MATCH | artifact API + React viewer |
| P9 | Synthetic actual-stage S0→S6 to delivery PDF | MATCH | `tests/e2e/test_actual_full_chain.py`; mock LLM + real stage modules/filesystem/Python execution |
| P10 | Windows packaged installer launches without dev Python | MATCH | Current Windows local release gates rebuild PyInstaller sidecar + embedded managed Python + Tauri/NSIS, silently install to an isolated directory, clear developer-Python assumptions, and complete authenticated `--startup-smoke` with exit 0 and 0 normal-exit orphans. This has been revalidated after later provider/UI changes. |
| P11 | Real-provider smoke test | PARTIAL | Real Provider Gate on installed product proves fresh-sidecar credential read, Test Connection, real generation with real token accounting, real tool calling, and multiple real S0 legs against Groq `openai/gpt-oss-20b`. Gate stayed fail-closed under schema drift/rate limits. One ceremonial simultaneous green G0 run on a stronger/stable provider remains open. Report: `docs/reviews/v1.0.0-rebuild-real-provider-gate.md`. |

## Intentional deviations

- CLI legs (`codex exec`, `claude -p`) → self-built tool-calling runtime.
- bash/macOS lifecycle scripts → Windows Tauri + authenticated Python sidecar.
- JSON/PID marker state truth → SQLite + append-only events; files remain carriers/evidence.
- upstream sandbox implementation → workspace permission scopes + Windows process/path controls.
- upstream text assets/wordlists are not copied verbatim; equivalent clean-room behavior is implemented.

## Current acceptance rule

Do **not** call the rebuild product-complete until all of the following are true:

1. release-candidate regression/build evidence satisfies
   `docs/decisions/ADR-0001-local-release-evidence-instead-of-mandatory-ci.md`.
   Current-head GitHub Actions is optional evidence, not a mandatory gate; do not claim a
   Linux runner was executed when it was not;
2. Windows release build + managed runtime + NSIS install/startup smoke is green;
3. hard-crash/restart E2E proves real-stage resume behavior;
4. remaining fidelity deviations (notably narrower repair-lane/gate parity and residual low-risk carrier schemas) are either closed or explicitly accepted;
5. timeout/cancel/failure-injection changes have executable release-candidate evidence, not
   source-presence evidence only;
6. real-provider smoke status is stated truthfully.
