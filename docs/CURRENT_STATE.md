# CURRENT_STATE — fidelity rebuild on gpt/fidelity-rebuild

Branch: `gpt/fidelity-rebuild`
HEAD: `cc46332` + local final-gate validation commit — GPT final source/release-gate fixes, LOCALLY VALIDATED by ZCode (see "Final source gate validation" below)
Tests: **locally verified at this HEAD: 451 passed / 0 failed + Ruff clean + frontend build OK + secret scan clean**

## Round-3 external source review

Round 3 was performed directly from GitHub; ChatGPT browser login is no longer a blocker.
Report: `docs/reviews/v1.0.0-rebuild-external-review-round3.md`
Verdict: **HOLD (P0=0)**.

The 422-test baseline had claimed these deterministic items closed:
- **B14 → MATCH**: S2 cascade invalidation — any re-executed upstream question
  durably drops all downstream checkpoints (`pipeline.s2_downstream_invalidated`)
  and forces rerun, even when the downstream artifacts still pass their own G2.
- **E8 → MATCH**: bounded compile-repair protocol (`compile_repair.py`) wired into
  S4 final compile, S5b initial compile and G5 rework R51: writer leg gets the log
  errors, must write a repair receipt, paper recompiles; exhaustion fails closed.
- **B9 → MATCH**: structure guard extended with R38③ appendix lstlisting-inventory,
  R68⑤ body graphics + receiver flagging, R47 code-chapter detection; new
  `guarded_repair.py` runs 改前快照 → 腿 → 结构守卫 → 违规整份回退 + 留底 on the G5
  rework text route; reverted legs cannot resolve ledger issues.

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


## Round-3 current boundary

Open release-level source findings:
- S5 calculation repair/escalation still lacks the full recompute → red-team → G2 → downstream propagation protocol.
- G5 figure repair still lacks dependent-text synchronization as part of the same repair transaction.
- Change Guard is not wired into production late-stage writer revisions; Structure Guard coverage is also incomplete across S4/S5/S5b/S6 writer paths.

Round-3 reviewer patches after `33544ec` include fail-closed/deterministic S5 escalation receipts, real final-round escalation extension, no degradation after failed/missed verdicts, no G5 self-authorized calc degradation, strict G5 receipt/verdict identity, real page-image input for G5/S6 reviews, durable S2 invalidation tombstones, crash-safe guarded repair, stage-scoped guarded compile repair, and an OpenAI-compatible vision capability setting.

These source-only patches must be locally regression-tested before current HEAD is described as green.

## Round-3 source closure after external review

Source-only closure is now implemented through the current branch HEAD. The three
release-level Round-3 P1s are **source-closed but regression-pending**:

- S5 calculation repair/escalation now reuses the verified S2 solver execution +
  independent red-team + G2 protocol, recomputes downstream questions, writes change
  manifests, reruns figures, and guarded-syncs dependent text before the Issue Ledger
  receives a repair receipt. Escalation winner selection is Runtime-promoted into the
  canonical solver/result carrier.
- G5 figure repair is now one transaction: Plotter receipt -> Runtime plot execution ->
  guarded Writer dependent-text sync -> Runtime generation-bound ledger receipt. The same
  anti-self-certification semantics were also applied to normal S5 figure repair/fuse.
- Change Guard + Structure Guard are now jointly enforced by the shared durable guarded
  repair primitive across late S4/S5/S5b/G5/S6 writer/integrator mutation paths and compile
  repair. Initial draft/independent abstract candidate generation remains intentionally
  outside diff-guarding.

Detailed handoff:
`docs/reviews/v1.0.0-rebuild-round3-source-closure-handoff.md`

**Round-3 local verification supersedes the earlier evidence boundary.**
`f17d248e43cb3e21871e1455cda2334eec66c9c0` is the last locally verified green baseline:
439 passed / 0 failed, Ruff clean, frontend build green.


## Round-3 local validation — 2026-09-27 — COMPLETE

ZCode pulled `33544ec..f94d08e` (GPT source-only closure of the three Round-3 release P1s)
and validated it locally:

- **Stage A focused regression**: 149 passed after updating 4 fixtures to the new
  fail-closed semantics (S4 directed-revision receipt, G5 figure-transaction writer-sync
  leg, failed S5 escalation no longer grants an extension round, reviewer verdicts must
  carry explicit generation). No production semantics were weakened.
- **Stage B distinguishing tests**: new `tests/pipeline/test_round3_closures.py` (12 tests,
  all real production paths — `run_s5`, `run_g5_rework`, verified recompute/escalation,
  IssueLedger, event persistence, filesystem mutation):
  - S5 calc repair runs solver → red-team → G2 → downstream topological recompute →
    change manifests → plot rerun → guarded writer sync, and only then a ledger receipt
    (`s5.calc_cascade_*`, `pipeline.s2_downstream_invalidated`, fresh `checkpoint.s2_question`).
  - Failing verified recompute leaves the Issue active with NO ledger receipt.
  - Change manifests are frozen BEFORE carrier propagation and survive a failed sync.
  - S5 calc escalation requires 获胜变体 adjudication and Runtime-promotes the winning
    variant into the canonical solver/result carrier (`pipeline.s2_escalation_promoted`).
  - Plotter/Modeler receipts alone can never advance an issue (S5 normal + G5 rework);
    G5 writer-sync failure keeps the issue active and fails the publication gate.
  - Change Guard reverts a broad unnamed rewrite (0.45); the same rewrite passes the
    escalated 0.70 limit; durable guard snapshots survive crash/resume and roll back
    orphaned mutations; reverted repairs delete their receipt artifacts.
- **Stage C**: `openai_compatible` `extra.image_input` round-trip (explicit True/False and
  default False) verified at the API/adapter level; desktop Provider Settings carries the
  该兼容渠道支持图片输入 checkbox for compatible channels only.
- **Stage D**: full suite **439 passed / 0 failed**, `ruff check .` clean, `npm run build`
  green (vite 157.82 kB).

Fidelity status at this HEAD: **B7, B8, B14, E8 → MATCH** (evidence updated in
FIDELITY_MATRIX); B9 stays PARTIAL only for the P2-1 master-plan structural invariants
(core-structure files / problem-chapter count); A17/A20 stay PARTIAL for upstream
ordering/parity audits.

No tag, no merge, per Round-3 protocol. Next: Round-4 external source review.


## Round-4 external source review — source fixes pending local regression

Report:
`docs/reviews/v1.0.0-rebuild-external-review-round4.md`

Last locally verified HEAD:
`f17d248e43cb3e21871e1455cda2334eec66c9c0`
(439 passed / Ruff clean / frontend build green).

Current remote HEAD contains Round-4 source-only fixes after that baseline and is therefore
**not yet current-head green**.

Round-4 source findings/fixes:
- **P1 fixed in source:** a failed G5 figure transaction could fall through to the
  Writer-only G5 text route because it selected every non-calc Issue. Text repair is now
  strictly `目标 == "文"`; figure Issues can advance only through the full figure transaction.
- S5 calc/figure Issue routing now requires exactly one related question so one
  `(id,generation)` cannot be consumed by multiple question transactions in one round.
- S5 non-final rework now performs bounded guarded compile/fix before writing its round
  checkpoint; unresolved compile errors are merged back as a hard mechanical Issue.
- G5 per-round success now requires both Page Guard and Defect Hunter PASS.
- OpenAI-compatible 4xx error text is secret-redacted.
- OpenAI-compatible `reasoning_effort` is no longer sent by default; it requires an
  explicit provider capability flag exposed in Provider Settings.

Next action: local focused regression + full pytest/Ruff/frontend build. Do not tag/merge
or start MSVC/real-provider smoke until this regression is green.


## Round-4 local validation — 2026-09-27 — COMPLETE

ZCode pulled `f17d248..902abe2` (GPT Round-4 source-only fixes) and validated locally:

- **Stage A focused regression**: 90 tests green after one fixture update — the old
  G5 fixture deliberately let the failed-figure issue take the text route ("also takes
  the G5 text route"), which is exactly the Round-4 P1 and is now forbidden; the fixture
  instead queues a would-succeed Writer-only response and proves it is never consumed.
- **New Round-4 distinguishing tests** (`tests/pipeline/test_round4_closures.py`, 9 tests,
  all real production paths):
  - `test_g5_failed_figure_transaction_cannot_fall_through_text_route` (in
    test_round3_closures.py): figure transaction failure keeps the 图 issue active with
    no ledger receipt even with a would-succeed Writer response queued, and the
    guarded-repair log proves node `G5:R1:文` never ran for the figure issue.
  - `test_s5_multi_question_calc_issue_is_unrouted_once` /
    `test_s5_multi_question_figure_issue_is_unrouted_once`: an issue naming two questions
    is routed to NO transaction (unrouted, active, zero receipts, 尝试次数 stays 0).
  - `test_s5_round_checkpoint_contains_post_rework_compile_evidence`: every post-rework
    checkpoint carries `post_rework_compile` evidence (A17 step 17).
  - `test_s5_post_rework_compile_failure_becomes_hard_issue`: a compile that stays broken
    after bounded repair is merged as 硬伤/文/编译 BEFORE the checkpoint; every checkpoint's
    ledger snapshot shows it (no healthy-looking checkpoint of a broken carrier).
  - `test_g5_page_guard_failure_cannot_end_rework_round`: with 20 pages vs baseline 10 and
    the hunter passing, the loop still enters round 2 (`new_pass = page_ok AND hunter`).
  - `test_openai_compatible_4xx_never_exposes_api_key`: a 400 body echoing the credential
    comes back redacted through the ProviderError.
  - `test_compatible_reasoning_effort_default_off` / `_explicit_on`: `reasoning_effort` is
    sent only behind the explicit capability; reasoning_levels advertised only then.
  - `test_compatible_profile_extra_round_trip_both_capabilities`: both compatible-only
    extras persist through the provider-profile API.
- **Stage B**: full suite **448 passed / 0 failed**, `ruff check .` clean, `npm run build`
  green (vite 158.10 kB). **Secret scan**: 247 tracked files, no real-looking secrets.

A17/A20 remain PARTIAL (per Round-4 protocol: full Master-Plan ordering/parity audit still
pending); B9 remains PARTIAL for the P2-1 structural invariants. No tag, no merge.
Next: GPT-5.6 Sol final source/release-gate review.

## Final Source / Release Gate — post Round-4

Review:
`docs/reviews/v1.0.0-rebuild-final-source-release-gate.md`

Last fully locally verified baseline:

`c4a38cbfa468a7d406306b36d16dcf49720368ca`

Evidence at that baseline:
- focused regression 90 passed;
- full pytest 448 passed / 0 failed;
- Ruff clean;
- frontend build green;
- secret scan clean;
- known open source-level P0/P1 after Rounds 1–4: 0.

Final source-gate patches after `c4a38cb`:
- S6 final figure repair now requires guarded dependent-text synchronization after Runtime
  plot execution and before final compile/harvest.
- Runtime now writes `交付/交付报告.md` with mechanically disclosed degraded/unresolved
  state and run metrics.
- OpenAI-compatible Test Connection now falls back from a missing/unsupported `/models`
  endpoint to a real minimal chat request using the configured model.

Focused behavior tests for these patches are source-added. Current remote HEAD is therefore
**micro-regression pending** and must not yet be called current-head green.

Gate decisions:
- Source/Pipeline: CONDITIONAL GO pending this final micro-regression.
- Product Release: HOLD until current-head MSVC/Tauri/NSIS installed validation,
  installed live cancellation proof, real-provider smoke, and the repository's CI
  acceptance requirement (or an explicit ADR changing that rule) are satisfied.

## Final source gate validation — 2026-09-27 — COMPLETE

ZCode pulled `c4a38cb..cc46332` (GPT final source/release-gate fixes) and validated:

- **F1 S6 figure→text sync**: the S6 figure route is now the full transaction
  (Plotter receipt → Runtime plot execution → guarded Writer sync of captions/
  references/numeric text via `审稿/回执_S6_图同步问{q}.json` → final compile →
  mechanical G5 → fresh visual terminal review → harvest). Sync failure fails S6
  with no harvest and no `checkpoint.s6_complete`
  (`test_s6_figure_sync_failure_blocks_harvest`).
- **F2 Runtime delivery report**: `交付/交付报告.md` is generated mechanically by the
  Runtime from 交接/降级放行.json, 台账/审稿台账.json and run metrics — listing degraded
  questions, exact review `(id,generation)` entries, every non-已消解 ledger row. The
  model cannot hide unresolved state
  (`test_s6_delivery_report_discloses_degraded_state`: 审-9-01 / generation=2 /
  升级已耗尽 disclosed; `result["delivery_report"] == "交付报告.md"`).
- **Compatible Test Connection fallback**: `GET /models` failure falls back to a real
  minimal chat-completions probe (configured model, max_tokens=1, no reasoning_effort
  unless explicitly opted in, 4xx bodies redacted)
  (`test_compatible_connection_falls_back_to_real_chat_when_models_missing`).

**Stage A focused**: 20 passed. **Full pytest**: **451 passed / 0 failed** (129.9s).
**Ruff**: clean. **Frontend build**: green (vite 158.10 kB). **Secret scan**: 249 tracked
files clean; fake keys are clearly test-only.

## Gate decisions at this HEAD

- **Source/Pipeline Gate = GO** — no known open source-level P0/P1 from Rounds 1-4 plus
  the final gate findings.
- **Windows Package Gate = PASS** — release packaging, NSIS installer, silent install,
  and developer-Python-independent startup smoke fully validated locally.
- **A12 → MATCH** (producer + exact consumption + G5 fail-closed + S6 delivery disclosure,
  all with focused tests). A17/A20/B9 remain PARTIAL (parity audits / P2-1 invariants) and
  must not be force-promoted.
- **Overall Product Release Gate = HOLD** — remaining external evidence:
  1. real-provider smoke with a user credential;
  2. current-head CI evidence or an explicit ADR replacing that acceptance rule;
  3. explicit acceptance of remaining fidelity deviations.

  Installed live cancellation/process-tree proof: **PASS** (2026-09-28).

## Windows Product Release Package Gate — 2026-09-28 — PASS

All pre-packaging checks, build steps, installers, and runtime isolations passed locally:

- **Source regression**:
  - `uv run ruff check .`: clean
  - `uv run pytest -q`: 451 passed / 0 failed (208.1s)
  - `npm ci` + `npm run build`: green (vite 158.10 kB)
  - Version metadata: `1.0.0-rebuild.1` verified consistent across package.json, package-lock.json, Cargo.toml, Cargo.lock, tauri.conf.json.
- **Toolchain & System**:
  - MSVC Build Tools: installed to `D:\dev\msvc` (version 17.14.37710.0, toolset 14.44.35207, cl 19.44.35229, link 14.44.35229.0, MSBuild 17.14.60.43110)
  - Windows SDK: 10.0.26100.0 (`C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64\kernel32.Lib`)
  - WebView2: Evergreen Runtime 153.0.4234.48 available
  - Rust target: `x86_64-pc-windows-msvc` (rustc 1.98.1)
- **PyInstaller Sidecar**:
  - Built: `apps/desktop/src-tauri/binaries/mmagent-sidecar-x86_64-pc-windows-msvc.exe` (40,493,610 bytes)
  - Smoke: `--help` returned exit code 0.
- **Managed Scientific Python Runtime**:
  - Relocatable distribution: CPython 3.11.16 + 39 scientific packages (numpy, pandas, scipy, matplotlib, scikit-learn, sympy, statsmodels, openpyxl, xlrd, python-docx, pypdf, pymupdf, pillow, networkx, pydantic, etc.)
  - Manifest: `apps/desktop/src-tauri/resources/runtime/MMAGENT_RUNTIME.json` (387 bytes)
  - Runtime import smoke: `apps/desktop/src-tauri/resources/runtime/python.exe` verified -> `managed-runtime-ok`
- **Tauri Release & NSIS Bundle**:
  - Release binary: `apps/desktop/src-tauri/target/release/mmagent-desktop.exe` (12,878,336 bytes, 2026-09-28 12:21:41)
  - NSIS installer: `apps/desktop/src-tauri/target/release/bundle/nsis/MM-Agent Desktop_1.0.0-rebuild.1_x64-setup.exe` (158,394,058 bytes, 2026-09-28 12:21:40)
- **Silent Installation**:
  - Target directory: `D:\dev\MM-Agent-Desktop-release-smoke`
  - Exit code: 0
  - Installed artifacts confirmed: `mmagent-desktop.exe`, `mmagent-sidecar.exe`, `runtime/python.exe`, `runtime/MMAGENT_RUNTIME.json`, `uninstall.exe`.
  - Installed runtime verification: python imports verified -> `installed-runtime-ok`
- **Developer-Python-Independent Startup**:
  - Launched in isolated child process with system-only PATH (`C:\Windows\system32;C:\Windows;C:\Windows\System32\Wbem;C:\Windows\System32\WindowsPowerShell\v1.0\`), and with `MMAGENT_PYTHON`, `PYTHONPATH`, and `VIRTUAL_ENV` completely purged.
  - Command: `mmagent-desktop.exe --startup-smoke`
  - Result: Exit code 0 (loopback token generated, sidecar spawned with bundled Python, `/health` endpoint verified, clean exit).
- **Orphan Process Check**:
  - Win32_Process inspection across `mmagent-desktop.exe`, `mmagent-sidecar*.exe`, `runtime/python.exe`: 0 orphan processes found.



## Installed Cancellation Gate — 2026-09-28 — PASS

The **installed** product (1.0.0-rebuild.1, `D:\dev\MM-Agent-Desktop-release-smoke`)
started a real long task (S1 prototype executed by the Runtime's `python.run` under the
Windows Job Object: managed python parent + sleeping child), cancelled through the
product's authenticated cancel endpoint:

- Terminal within **0.7 s**: durable run CANCELLED, parent+child processes dead,
  0 owned orphans, `cancel_probe_finished.txt` absent, progress file frozen.
- No retry/double-writer; fresh-sidecar restart reconstructed CANCELLED from SQLite
  with no auto-resume; a post-cancel new run executed short prototype tasks
  SUCCEEDED and paused cleanly at the safe boundary.
- Evidence: `docs/runs/installed-cancellation/` +
  `docs/reviews/v1.0.0-rebuild-installed-cancellation-gate.md`.

Two real product defects were found and fixed during the gate (source fixes → full
repackage → reinstall before the gate run):
1. `WindowsCredentialStore` unusable on current pywin32 (CredWrite bytes→str blob,
   CredRead utf-16le decode) — 3 focused tests;
2. keyless provider profiles sent an empty `Authorization: Bearer ` header which httpx
   rejects — openai_chat/openai_responses now omit it — 2 focused tests.

Regression at gate HEAD: **456 passed / 0 failed**, Ruff clean, frontend build green,
NSIS rebuilt, startup smoke exit 0.

Gate decisions: Source/Pipeline = GO · Windows Package = PASS · Installed Cancellation =
**PASS** · Product Release = HOLD (Real Provider Smoke, CI acceptance decision,
fidelity-deviation acceptance remaining).


## Installed Credential Gate — 2026-09-28 — PASS

Root cause of the deferred frozen-sidecar read failure: PyInstaller missed
win32cred's lazy `win32timezone` import; the old get() masked every read error
as "not found". Fixed (hidden import + explicit NOT_FOUND/READ_FAILED taxonomy
+ non-secret diagnostics endpoints + openai_chat /models→chat fallback), full
repackage + reinstall, then installed-product E2E with a fake secret:
product-boundary write → SQLite stores only the ref → full app exit → fresh
sidecar reads the credential → Test Connection falls back to authenticated
chat → a loopback relay requiring that exact Bearer served 29/29 authenticated
requests (0 mismatches) while the installed Runtime completed all of S0+S1 and
paused at the safe boundary. All test credentials deleted from Credential
Manager afterwards. Evidence: `docs/runs/installed-credential/`,
`docs/reviews/v1.0.0-rebuild-installed-credential-gate.md`.

Gates: Source/Pipeline GO · Windows Package PASS · Installed Cancellation PASS ·
**Installed Credential PASS** · Real Provider **WAITING_FOR_USER_CREDENTIAL**
(user enters API Key / Base URL / Model in the installed app tonight) · CI
decision open · deviation acceptance open. Regression: 462 passed / Ruff clean.


## Real Provider Gate — 2026-09-28 — CONDITIONAL PASS

User supplied a real Groq credential through this session; it was entered once
via the installed product boundary and lives only in Windows Credential Manager.

- R1 fresh-sidecar credential read PASS (found=true after full app restart).
- R2 Test Connection PASS (/models 200, 1.56s).
- R3 real generation PASS (real invocations with true token accounting).
- R4 real tool calling PASS (fs.read/fs.write executed by the Runtime; sealed
  artifacts; permission denials cleanly self-correctable).
- Provider-proven corrections: model llama-3.1-8b-instant → 404 model_not_found
  → openai/gpt-oss-20b (real /models list); reasoning_effort is REQUIRED by
  gpt-oss on Groq → profile reasoning=low. Base URL/protocol/key untouched.
- Short real stage: S0.2 SUCCEEDED in 7 real runs, S0.3 in 3, both together in
  v8/v10; G0 green not achieved in one run due to 8B-model contract-schema
  variance + free-tier rate limits — G0 fail-closed correctly every time
  (real-model proof of the pipeline's contract enforcement).
- In-gate product fixes (source→tests→repackage→reinstall→rerun): fs.read
  directory-read PermissionError no longer kills a leg (clean tool error,
  model self-corrected); answer_predictor read scopes now cover 数据档案.json
  its own prompt requires. 464 passed / 0 failed, Ruff clean.
- Evidence: docs/runs/real-provider/, docs/reviews/v1.0.0-rebuild-real-provider-gate.md.

Gates: Source GO · Package PASS · Cancellation PASS · Credential PASS ·
Real Provider CONDITIONAL PASS (one ceremonial green-G0 run open; achievable
with quota/stronger model, no code change implicated) · CI decision open ·
deviation acceptance open.
