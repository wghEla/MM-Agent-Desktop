# MM-Agent Desktop UI v2

Status: implementation baseline
Branch: `gpt/fidelity-rebuild`

## Product direction

MM-Agent Desktop is not a generic chat client and not an admin dashboard. It is a
long-running mathematical-modeling workbench whose authoritative state remains the
Python Runtime + SQLite pipeline.

The UI borrows interaction principles, not source code, from several open workspaces:

- ZCode: calm, dense, operational desktop UI; clear workspace/model/session hierarchy.
- Codex: workspace-first shell; configuration stays outside the primary task surface.
- WorkDSH / DeepSeek Harness: keep runtime/domain ownership authoritative and make the
  workbench a projection instead of inventing a second state machine.
- HaJiMi Math Model Agent: separate model/provider configuration from the working
  conversation/workspace surface.

## Non-negotiable architecture boundary

UI v2 MUST NOT introduce a second source of truth for:

- S0-S6 state;
- G0-G5 results;
- task status / leases / attempts;
- Issue Ledger;
- degraded-release state;
- artifact truth;
- run cancellation;
- provider credentials.

All of those continue to come from the existing authenticated sidecar APIs and SQLite.

Local UI persistence may store only presentation/bookmark information such as:

- recently opened workspace paths;
- panel widths/collapse state;
- theme;
- last selected run / artifact.

Removing a bookmark must never delete a workspace.

## Information architecture

```
+------------------+--------------------------------------+--------------------+
| Workspace        | Project / model / controls           | Artifacts          |
|                  +--------------------------------------+                    |
| current project  | S0 G0 S1 G1 ... G5 S6               | paper.pdf          |
| import materials +--------------------------------------+ figures/           |
|                  | Current stage                         | results/           |
| runs             | tasks / gates / actionable errors    | review/ledger      |
|                  |                                      | preview            |
| settings         | event details are secondary          |                    |
+------------------+--------------------------------------+--------------------+
```

### Left rail — Workspace

Primary objects:

1. current workspace;
2. imports/materials;
3. run history;
4. new run;
5. settings entry.

The user should not need to see provider configuration fields during normal work.

Future phase:

- recent workspaces registry;
- native folder picker;
- file tree rooted at the workspace;
- workspace rename/remove-bookmark actions.

## Center — Pipeline

The center is pipeline-first, not chat-first.

Persistent stage rail:

```
S0 -> G0 -> S1 -> G1 -> S2 -> G2 -> S3 -> G3 -> S4 -> S5 -> G5 -> S6
```

Each item is a projection from current Dashboard data and may display:

- idle;
- running;
- succeeded;
- failed;
- paused/waiting.

Current stage details show:

- role / node;
- status;
- attempt;
- actionable error.

Gates are first-class milestones. Event logs are secondary expandable evidence.

## Right rail — Artifacts

Artifacts are always one click away from the pipeline.

Categories remain runtime-derived. Typical roots:

- 输入
- 求解
- 图片
- 论文
- 审稿
- 台账
- 交接
- 交付

Preview support continues to reuse the current artifact API:

- text / JSON / Markdown / TeX;
- images;
- PDF;
- binary metadata.

## Provider settings

Provider configuration moves out of the workspace rail into a dedicated settings surface.

Presentation:

```
Providers              Selected provider
---------              -----------------
OpenAI                 Authentication
Anthropic              API key saved in Windows Credential Manager
Gemini                 [replace]
Groq
OpenAI Compatible      Endpoint
Custom                 Model
                       [Test Connection]
                       > Advanced
```

The normal path should expose only:

- provider/preset;
- API key;
- model;
- Test Connection.

Advanced contains protocol-level fields:

- Base URL;
- protocol;
- reasoning;
- image input;
- reasoning_effort;
- max output;
- timeout.

Secrets are never read back into the UI.

## Authentication architecture

Represent authentication explicitly:

```ts
type AuthKind = "api_key" | "oauth" | "none";
```

v1 production path remains API key + Windows Credential Manager.

OAuth/account login is shown only for providers where a documented third-party OAuth /
device flow is actually implemented. UI must not imply that a consumer subscription is
interchangeable with API access.

Forbidden implementation shortcuts:

- browser-cookie import;
- session-token extraction;
- borrowing another application's OAuth client;
- pretending to be an official first-party client;
- persisting bearer/API secrets in SQLite/localStorage/logs.

## Provider presets

Presets are UI conveniences, not new runtime protocols.

A preset may supply:

- label/icon;
- runtime protocol;
- default base URL;
- capability defaults.

The underlying adapter stays one of the existing runtime protocols.

Custom / OpenAI Compatible remains available for ZCode, relays, NewAPI/OneAPI, vLLM,
and similar endpoints.

## Visual system

Character:

- calm;
- dense;
- technical;
- desktop-first;
- low decoration;
- long-session friendly.

Rules:

- use a small neutral surface hierarchy;
- sparse accent color;
- semantic success/warning/destructive colors only for state;
- compact 12/13/14px operational typography;
- 4/8/12/16px spacing rhythm;
- restrained radii;
- monospace only for paths, ids, hashes, model names and logs;
- no oversized marketing cards;
- no full-surface gradients;
- no excessive borders where spacing/text hierarchy is enough.

## Agent product architecture

UI v2 keeps the proven modeling runtime but adopts several mature agent-product patterns.

### One authoritative runtime

The desktop UI behaves like an app-server client:

```
Desktop UI
   |
Authenticated sidecar API
   |
Runtime / SQLite / ProcessManager
   |
Providers + Tools + S0-S6
```

The UI must not infer that a task succeeded because text looks successful.

### Session/run as a durable object

A Run is a resumable durable execution, not a chat tab. The UI therefore presents:

- current run;
- historical runs;
- durable status;
- current owner / resumability;
- stage/gate projection;
- artifacts produced by that run.

Conversation-like interaction, when added, is an input surface to the run rather than
the source of run truth.

### Model routing is configuration, not agent identity

Roles remain semantic modeling roles. A role is not permanently coupled to one provider.
Future UI may expose a model policy such as:

```
Default model
Calculation / solver model
Review / critic model
Vision review model
Fallback model
```

but Runtime-owned routing decides which concrete model profile serves each role.

### Full-auto vs collaborative operation

The eventual product should distinguish execution mode from quality profile.

Quality profile remains:

- 快速;
- 标准;
- 深度.

Execution mode may later become:

- **全自动** — proceed through gates whenever Runtime conditions permit;
- **协作** — pause at defined human checkpoints for instructions/approval.

This is intentionally not implemented as a UI-only toggle. It requires an explicit Runtime
policy before the control is enabled.

### Extension surface

Do not hard-code every future capability into the main workspace.

Potential extension domains:

- specialist agents;
- reusable skills;
- connectors / MCP;
- templates;
- dataset tools;
- literature/research tools.

They should enter through a capability/extension surface while S0-S6 remains the modeling
workflow owner.

### Human interaction

A future compact composer may allow:

- additional constraints;
- answering a Runtime question;
- approving/rejecting a collaborative checkpoint;
- attaching a file;
- requesting a bounded rerun.

It must not silently mutate ledger/gate state. Human actions become explicit durable events.

## Delivery phases

### Phase 1 — shell re-layout

- three-pane desktop shell;
- Provider settings modal;
- compact run toolbar;
- stage rail;
- Artifacts dock moved to right pane;
- preserve all current behavior.

### Phase 2 — workspace UX

- recent workspace bookmarks — implemented + locally verified;
- native folder picker — implemented + locally verified;
- workspace file tree — source implemented, local validation pending;
- first-run onboarding — source implemented, local validation pending;
- project/open/create dialogs — source implemented, local validation pending.

Workspace tree security contract:

- sidecar enumerates only fixed user-visible roots;
- `.mmagent` and arbitrary filesystem paths are excluded;
- every returned existing path is revalidated by `PathPolicy`;
- traversal is bounded by item count and depth;
- preview is read-only and shares the same authenticated sidecar boundary.

### Phase 3 — provider UX

- provider preset registry;
- model discovery / manual fallback;
- API-key status presentation;
- capability-driven advanced fields;
- formal OAuth extension point.

### Phase 4 — local validation

Requires Windows/Tauri runtime:

- DPI and resizing;
- Chinese long strings;
- create/open/reopen workspace;
- provider create/test/restart;
- run start/pause/resume/cancel;
- PDF/image/text preview;
- release package build and startup smoke.

## Acceptance principle

A UI change is successful only when it changes presentation without weakening the proven
product gates:

- Source/Pipeline GO;
- Windows Package PASS;
- Installed Cancellation PASS;
- Installed Credential PASS.

## Local validation record (2026-09-28, Windows)

Phase 1 in full plus the picker/bookmark portion of Phase 2 were implemented and validated
on a real Windows/Tauri runtime. Report: `docs/reviews/v1.0.0-rebuild-ui-v2-local-validation.md`.

- Native folder/file picker shipped via the official `tauri-plugin-dialog` (npm
  `@tauri-apps/plugin-dialog`, capability `dialog:allow-open` only). Workspace create/open is
  picker-first with the manual path preserved under 高级：手动路径; the import panel gained a
  multi-select file picker.
- Recent-workspace bookmarks are presentation-only localStorage (`mmagent.recentWorkspaces`)
  and survive an app restart; truth remains Runtime/SQLite.
- Visual checklist passed at 1440×900 / ≈1220×740 / ≈1040×700 logical (200% display scale);
  fail-closed gate states (G1 FAIL → run FAILED) render truthfully with correct color
  semantics; PDF/PNG/JSON previews verified against a live run's artifacts.
- Package/version alignment note: the release build rejects mismatched npm/crate minors
  (e.g. `@tauri-apps/api` 2.12 vs crate 2.11) — keep them on the same minor.
- The first local-validation round covered Phase 1 plus native picker/recent bookmarks.
- Phase 2 is now source-complete on the branch: Runtime-backed workspace file tree,
  workspace file preview, first-run onboarding, and dedicated create/open dialogs are
  implemented after the verified `ffe1793` baseline. These Phase-2 additions are
  source-only until the next Windows/Tauri local validation.
- Phases 3–4 remain open; nothing here declares Product Release GO.
