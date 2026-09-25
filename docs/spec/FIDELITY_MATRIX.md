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
| A1 | S0 problem digestion / contract / prediction / trace matrix | PARTIAL | `s0_s1.py`, resumable role legs, `test_s0_s1.py`; exact upstream seed/health-check decomposition not fully audited |
| A2 | G0 contract gate | MATCH | `gates/g0.py`, `test_g0_gate.py` |
| A3 | S1 strategic tournament with real prototypes | PARTIAL | `s1_tournament.py`, real prototype execution, `test_s1_tournament.py`; upstream wave/parallel tournament semantics still being audited |
| A4 | G1 route/plan/prototype evidence gate | MATCH | G1 profile semantics + `test_g1_profile_semantics.py` |
| A5 | S2 dependency DAG layered execution | PARTIAL | DAG + topological layers implemented; questions inside a layer remain sequential |
| A6 | Red-team independent recomputation | PARTIAL | hard read isolation, independent `复算.py`, frozen hashed input packages and tests; exact upstream recompute protocol still under audit |
| A7 | Distinguish terminology vs numeric disagreement | PARTIAL | compare/G2 logic exists; full pinned edge-case parity not yet proven |
| A8 | Arbitration / interpretation responsibility assignment | PARTIAL | arbitration legs exist; depth and archive parity still under audit |
| A9 | Per-question G2 | PARTIAL | `gates/g2.py`, red-team tests; complete upstream evidence semantics not yet declared MATCH |
| A10 | Normal repair bounded to ≤2 | MATCH | bounded rework constant and S2 control flow |
| A11 | Escalation swarm (3 variants + adjudication + recheck) | PARTIAL | executable 3-variant escalation path exists; full evidence parity pending |
| A12 | Degraded release with unresolved evidence | PARTIAL | `降级放行.json` carrier and G5 integration exist; full delivery-report parity pending |
| A13 | S3 figure evidence + two-round figure review | MATCH | `s3_figures.py`, plot runtime, `test_s3_figures.py` |
| A14 | G3 mechanical figure gate | MATCH | 16–22 figures, schematic/diversity/caption checks + `test_g3_gate.py` |
| A15 | S4 narrative → paper → chapter/blind review → integrate → abstract swarm | PARTIAL | full source path exists with focused tests; exact upstream editorial-guard ordering/parity still under audit |
| A16 | G4 paper gate | PARTIAL | compile/page/audit/src/trace checks exist + `test_g4_gate.py`; not all upstream mechanical clauses proven |
| A17 | S5 18-step review-round semantics | PARTIAL | review/rework/ledger/checkpoint loop exists and is resumable; exact 18-step parity and scoring/plateau semantics remain incomplete |
| A18 | Reviewer A/B + defect hunter + judge simulator + mechanical lane | MATCH | four independent role legs, page-image judge input, mechanical lane; pipeline tests |
| A19 | S5a abstract finalization / S5b beautification | PARTIAL | both implemented and tested; upstream cosmetic-loop parity still under audit |
| A20 | G5 publication gate | PARTIAL | final compile, G4 reuse, ledger convergence, stale-value/page guards, defect review exist; all R49–R52 paths not yet proven |
| A21 | S6 final page review / fixes / harvest / retrospective | PARTIAL | implemented with run metrics and resumable legs; installed-product delivery proof pending |

## B. Loops, ledger, and guards

| # | Mechanism | Status | Evidence / gap |
|---|---|---|---|
| B1 | Issue Ledger five-state machine | MATCH | `issue_ledger.py`, `test_issue_ledger.py` |
| B2 | Issue identity merge / reopen / severity only rises | MATCH | location + similarity thresholds and generation tracking tested |
| B3 | Repair receipts / unknown-id ignore / attempt accounting | MATCH | receipt idempotency + generation CAS in ledger tests |
| B4 | Reviewer-only paired verdict / missed verdict reopens | MATCH | verdict generation CAS + fail-closed missed verdict behavior |
| B5 | R45 abstention-vote merge semantics | NOT IMPLEMENTED | judge prompt can abstain, but dedicated abstention merge semantics are not evidenced |
| B6 | Convergence = no blocking active issues | MATCH | ledger convergence mechanically checks blocking severities |
| B7 | Fuse after ≥2 attempts | PARTIAL | fuse candidate and shelving rules implemented; hard/correctness escalation parity remains under audit |
| B8 | Change Guard 0.45 / 0.70 | MATCH | sentence units + named mask + min-ratio implementation and tests |
| B9 | Structure Guard | PARTIAL | input-set/file-loss/empty-file checks exist; complete upstream appendix/title rules not all evidenced |
| B10 | Page Guard | MATCH | +max(10%,2 pages) and sudden-drop guard implemented/tested |
| B11 | Integrator/frozen-fact guard | PARTIAL | editorial/frozen-input protections exist, but complete per-file fingerprint parity not proven |
| B12 | Version-change manifest / stale-value guard | PARTIAL | stale-value scan exists and is wired into G5; full calc→figure→text propagation proof pending |
| B13 | Best-retention / rollback package / 0.5 noise band | NOT IMPLEMENTED | no sufficient source/test evidence |
| B14 | Cascade recomputation / downstream invalidation | PARTIAL | DAG primitives exist; full durable invalidation-and-rerun behavior not yet proven |

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
| D4 | Review target / plateau | 8.6 / 0.15 | PARTIAL | values are present; complete S5 scoring/plateau decision semantics not yet matched |
| D5 | Beauty threshold | 8.5 | PARTIAL | value present; full upstream use in convergence path not fully proven |
| D6 | Change guard / escalated guard | 0.45 / 0.70 | MATCH | thresholds + guard implementation/tests |
| D7 | Default concurrency / 429 floor | 4 / 2 | NOT IMPLEMENTED | constants exist, but dynamic wave concurrency reduction is not implemented |
| D8 | Deep profile | routes3 / abstract5 / review4 / beauty2 / 600 / 40h | PARTIAL | profile values match; budget enforcement and full all-role high-effort semantics not fully wired |
| D9 | Standard profile | abstract3 / review3 / role tiers / 30h | PARTIAL | values/routing exist; runtime budget enforcement incomplete |
| D10 | Quick profile | hard-question tournament / routes2 / review2 / beauty1 / 20h | PARTIAL | values exist; exact hard-question-only tournament behavior remains under audit |
| D11 | ≤20 pages / 16–22 figures / src≥0.6 / decimals≤4 | PARTIAL | thresholds and several gates/audit checks exist; complete combined publication proof pending |

## E. Runtime and resilience

| # | Mechanism | Status | Evidence / gap |
|---|---|---|---|
| E1 | One owner per workspace | MATCH | `run.lock` + PID liveness + tests |
| E2 | Node/stage/S5-round resume; active residue fail-closed | PARTIAL | deterministic node reuse/retry, stage checkpoints and S5 snapshots exist; true hard-crash full-stage E2E still required |
| E3 | Pause / resume / cancel + process-tree cleanup | PARTIAL | controller + cancellation + Windows process controls exist; installed-app failure proof pending |
| E4 | Layered timeout / recycle before reassignment | PARTIAL | tool/runtime cleanup exists; full wave timeout semantics incomplete |
| E5 | 429 handling and concurrency reduction | PARTIAL | typed retryable 429 behavior exists; adaptive concurrency reduction to floor 2 does not |
| E6 | MAX_LEGS / MAX_HOURS emergency budget guard | NOT IMPLEMENTED | profile constants exist, but authoritative engine enforcement is not evidenced |
| E7 | JSON repair loop | PARTIAL | tool-call malformed JSON recovery exists; full artifact-schema rewrite loop parity incomplete |
| E8 | Compile repair loop | PARTIAL | compile failure is fail-closed and repair paths exist in later stages; bounded general compile-repair protocol not fully matched |
| E9 | Run feedback ledger / metrics | MATCH | S6 event/task metrics → `审稿/回流账.json` + tests |
| E10 | Producer/consumer contract enforcement | PARTIAL | Pydantic/artifact schema boundary exists; exhaustive consumer⊆producer contract audit not complete |

## F. Desktop/product delivery (new client layer)

These are product requirements introduced by the independent desktop reimplementation rather than upstream shell-script fidelity.

| # | Mechanism | Status | Evidence / gap |
|---|---|---|---|
| P1 | Authenticated loopback Python sidecar | MATCH | bearer token, loopback bind, shutdown path, sidecar API tests |
| P2 | Secret-safe Provider Settings | MATCH | Windows Credential Manager abstraction; SQLite stores credential reference only; secret-boundary tests |
| P3 | Tauri starts/stops/proxies sidecar | PARTIAL | source implemented; current Windows CI proof is pending after ICO replacement |
| P4 | Project create/open/import | MATCH | sidecar endpoints + React panel + artifact API tests |
| P5 | Run start/pause/resume/cancel | MATCH | controller/sidecar/UI + integration tests |
| P6 | Restart recovery from persisted Run history | MATCH | persisted run listing, detached RUNNING/PAUSED resume controls and safe cancel tests |
| P7 | Dashboard / gates / event view | MATCH | React Dashboard + sidecar dashboard endpoint |
| P8 | Artifact/image/PDF viewer | MATCH | artifact API + React viewer |
| P9 | Synthetic actual-stage S0→S6 to delivery PDF | MATCH | `tests/e2e/test_actual_full_chain.py`; mock LLM + real stage modules/filesystem/Python execution |
| P10 | Windows packaged installer launches without dev Python | NOT IMPLEMENTED | sidecar distribution/bundling + installer smoke remains |
| P11 | Real-provider smoke test | NOT IMPLEMENTED | intentionally unverified until a real credential is supplied |

## Intentional deviations

- CLI legs (`codex exec`, `claude -p`) → self-built tool-calling runtime.
- bash/macOS lifecycle scripts → Windows Tauri + authenticated Python sidecar.
- JSON/PID marker state truth → SQLite + append-only events; files remain carriers/evidence.
- upstream sandbox implementation → workspace permission scopes + Windows process/path controls.
- upstream text assets/wordlists are not copied verbatim; equivalent clean-room behavior is implemented.

## Current acceptance rule

Do **not** call the rebuild product-complete until all of the following are true:

1. current-head Python Linux + Windows CI is green;
2. current-head Windows frontend + Cargo check is green;
3. hard-crash/restart E2E proves real-stage resume behavior;
4. installer launches a bundled sidecar on a clean Windows machine;
5. failure-injection matrix is closed or explicitly documented as accepted deviation;
6. real-provider smoke status is stated truthfully.
