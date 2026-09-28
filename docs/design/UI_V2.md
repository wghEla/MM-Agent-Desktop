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

## Delivery phases

### Phase 1 — shell re-layout

- three-pane desktop shell;
- Provider settings modal;
- compact run toolbar;
- stage rail;
- Artifacts dock moved to right pane;
- preserve all current behavior.

### Phase 2 — workspace UX

- recent workspace bookmarks;
- native folder picker;
- workspace file tree;
- first-run onboarding;
- project/open/create dialogs.

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
