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
| A3 | S1 strategic tournament with real prototypes | PARTIAL | `s1_tournament.py`, adaptive bounded prototype-authoring wave + real prototype execution + `test_s1_tournament.py`; exact upstream route scoring/selection parity remains under audit |
| A4 | G1 route/plan/prototype evidence gate | MATCH | G1 profile semantics + `test_g1_profile_semantics.py` |
| A5 | S2 dependency DAG layered execution | MATCH | `run_s2` follows the pinned 5f507e0b executable behavior: topological layer barriers with per-question sequential execution inside each layer despite the upstream stale “并行” source comment. Durable `checkpoint.s2_question` events skip fully completed questions on resume, mechanically revalidate PASS carriers, and fail closed when a degraded-release carrier is missing; focused pipeline tests cover ordering, reuse and invalidation. |
| A6 | Red-team independent recomputation | PARTIAL | hard read isolation, independent `复算.py`, frozen hashed input packages and tests; exact upstream recompute protocol still under audit |
| A7 | Distinguish terminology vs numeric disagreement | PARTIAL | compare/G2 logic exists; full pinned edge-case parity not yet proven |
| A8 | Arbitration / interpretation responsibility assignment | PARTIAL | arbitration legs exist; depth and archive parity still under audit |
| A9 | Per-question G2 | PARTIAL | `gates/g2.py`, red-team tests; complete upstream evidence semantics not yet declared MATCH |
| A10 | Normal repair bounded to ≤2 | MATCH | bounded rework constant and S2 control flow |
| A11 | Escalation swarm (3 variants + adjudication + recheck) | PARTIAL | executable 3-variant escalation path exists and variant authoring uses the adaptive wave scheduler; full evidence parity pending |
| A12 | Degraded release with unresolved evidence | PARTIAL | `降级放行.json` carrier and G5 integration exist; full delivery-report parity pending |
| A13 | S3 figure evidence + two-round figure review | MATCH | `s3_figures.py`, adaptive plotter/reviewer waves, plot runtime, `test_s3_figures.py` |
| A14 | G3 mechanical figure gate | MATCH | 16–22 figures, schematic/diversity/caption checks + `test_g3_gate.py` |
| A15 | S4 narrative → paper → chapter/blind review → integrate → abstract swarm | PARTIAL | full source path exists; chapter/blind and abstract candidates use bounded waves, and chapter review has persistent best-version rollback; exact upstream editorial-guard ordering/parity remains under audit |
| A16 | G4 paper gate | MATCH | compile/page/abstract-1-page/audit/src/trace/matrix checks exist + `test_g4_gate.py` + `TestG4AbstractPage` |
| A17 | S5 18-step review-round semantics | PARTIAL | review/rework/ledger/checkpoint loop, R45 merge, persistent rollback and four-lane adaptive review waves exist. Source now also has per-leg wave deadlines with awaited cancellation before retry and peer cleanup; remaining fidelity work is narrower repair-lane/order parity, and the newest timeout changes still await executable current-head CI evidence. |
| A18 | Reviewer A/B + defect hunter + judge simulator + mechanical lane | MATCH | four independent role legs, page-image judge input, mechanical lane; pipeline tests |
| A19 | S5a abstract finalization / S5b beautification | PARTIAL | both implemented and tested; upstream cosmetic-loop parity still under audit |
| A20 | G5 publication gate | MATCH | final compile, G4 reuse, ledger convergence, stale-value/page guards, defect review, R49 figure route, R50 calc shelve, R51 compile-before-recheck, R52 page guard all implemented + `TestG5Rework` |
| A21 | S6 final page review / fixes / harvest / retrospective | PARTIAL | implemented with run metrics, retrospective schema (`s6_contracts.py`), resumable legs; installed-product delivery proof pending |

## B. Loops, ledger, and guards

| # | Mechanism | Status | Evidence / gap |
|---|---|---|---|
| B1 | Issue Ledger five-state machine | MATCH | `issue_ledger.py`, `test_issue_ledger.py` |
| B2 | Issue identity merge / reopen / severity only rises | MATCH | location + similarity thresholds and generation tracking tested |
| B3 | Repair receipts / unknown-id ignore / attempt accounting | MATCH | receipt idempotency + generation CAS in ledger tests |
| B4 | Reviewer-only paired verdict / missed verdict reopens | MATCH | verdict generation CAS + fail-closed missed verdict behavior |
| B5 | R45 abstention-vote merge semantics | MATCH | only judge-simulator unverifiable negatives abstain; substantive unresolved votes veto, resolved votes otherwise resolve, and all-abstention cases fall through to missed-verdict reopen; focused tests cover all three cases |
| B6 | Convergence = no blocking active issues | MATCH | ledger convergence mechanically checks blocking severities |
| B7 | Fuse after ≥2 attempts | PARTIAL | fuse candidate and shelving rules implemented; hard/correctness escalation parity remains under audit |
| B8 | Change Guard 0.45 / 0.70 | MATCH | sentence units + named mask + min-ratio implementation and tests |
| B9 | Structure Guard | PARTIAL | input-set/file-loss/empty-file checks exist; complete upstream appendix/title rules not all evidenced |
| B10 | Page Guard | MATCH | +max(10%,2 pages) and sudden-drop guard implemented/tested |
| B11 | Integrator/frozen-fact guard | PARTIAL | editorial/frozen-input protections exist, but complete per-file fingerprint parity not proven |
| B12 | Version-change manifest / stale-value guard | PARTIAL | stale-value scan exists and is wired into G5; full calc→figure→text propagation proof pending |
| B13 | Best-retention / rollback package / 0.5 noise band | MATCH | shared retention runtime persists pre-review TeX snapshots for S4/S5; relative verdict wins, 0.5 score drop is the fallback, prior files are restored, and S4/S5 integration tests prove rollback behavior |
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
| E3 | Pause / resume / cancel + process-tree cleanup | PARTIAL | controller cancellation reaches AgentLoop and the desktop compile hook; blocking compile is moved off the sidecar event loop; Windows shared ProcessManager owns Python/XeLaTeX process trees and sidecar shutdown cleanup. Installed-app cancellation-during-live-tool proof is still pending. |
| E4 | Layered timeout / recycle before reassignment | PARTIAL | Source now implements the pinned R60 invariant in the new runtime: each wave leg starts its deadline only after acquiring a concurrency slot; timeout cancellation is awaited before retry, preventing old/new double writers; programming exceptions cancel+await peer legs; default wave deadline is 1300s and S4/S5 review waves retain 3600s. Python/XeLaTeX share the Windows Job Object ProcessManager, MATLAB helper uses the same backend, and external-tool envs are allowlisted. Focused timeout/recycle tests exist, but latest-head CI has not executed because GitHub Actions jobs are currently failing before runner startup. |
| E5 | 429 handling and concurrency reduction | MATCH | typed `RateLimitError` → durable QUEUED is wired through adaptive 4→2 waves with one retry. Context-aware `run_role_leg` gives direct standalone legs the same one-job-wave retry semantics while an active outer wave owns retry/concurrency to prevent double retry; focused tests cover direct and nested/outer-wave paths. |
| E6 | MAX_LEGS / MAX_HOURS emergency budget guard | MATCH | durable task count + accumulated RUNNING intervals are checked before executable role legs and at pipeline boundaries; pause time is excluded; unit tests cover both ceilings |
| E7 | JSON repair loop | PARTIAL | tool-call malformed JSON recovery exists; full artifact-schema rewrite loop parity incomplete |
| E8 | Compile repair loop | PARTIAL | compile failure is fail-closed and repair paths exist in later stages; bounded general compile-repair protocol not fully matched |
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
| P10 | Windows packaged installer launches without dev Python | MATCH | CI #174 builds NSIS, silently installs it, verifies embedded managed Python, clears developer Python PATH/override state, and the installed app completes authenticated sidecar readiness via --startup-smoke |
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
2. Windows release build + managed runtime + NSIS install/startup smoke is green;
3. hard-crash/restart E2E proves real-stage resume behavior;
4. remaining fidelity deviations (notably narrower repair-lane/gate parity and residual low-risk carrier schemas) are either closed or explicitly accepted;
5. timeout/cancel/failure-injection changes on the current head have executable CI evidence, not source-presence evidence only;
6. real-provider smoke status is stated truthfully.
