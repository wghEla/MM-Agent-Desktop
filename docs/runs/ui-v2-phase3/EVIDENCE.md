# UI v2 Phase 3 — Provider UX local-validation evidence (dev build, 2026-09-28)

All screenshots are real Tauri dev-window captures on Windows (WebView2, 200% display
scale unless noted). The provider under test talks to a local scripted relay
(`relay3.py`, `127.0.0.1:28911`); the only credential ever used is a fake
`sk-fake-…-TESTONLY` marker key (recorded in `match yes/no` style only, never in full).

| File | Protocol section | What it shows |
|---|---|---|
| dev-A-provider-catalog.png | §9 Provider Catalog UI | Catalog list (7 presets) + right-hand detail pane, no legacy "配置墙" |
| dev-A2-catalog-grid.png | §9 | Catalog grid rendering (preset cards) |
| dev-B-zcode-preset.png | §10 ZCode preset | ZCode preset: editable empty Base URL / Model ID, no hardcoded endpoint |
| dev-C-compatible-noauth.png | §11 Compatible No auth | Compatible preset with auth_style=none: API Key input hidden, keyless save |
| dev-D-model-discovery.png | §12 Model discovery | Discovered list from GET /models (dedup + stable sort), manual fallback visible |
| dev-F-presave-test.png | §15 Pre-save Test Connection | Test Connection in create form → PASS via /providers/test-config without persisting |
| dev-G-created-selected.png | §14 Create → auto-select | Newly created provider auto-selected in left list, detail pane shown |
| dev-H-advanced-openai-chat.png | §8/§13 OpenAI preset lock | OpenAI preset: Base URL locked to https://api.openai.com/v1 under Advanced |
| dev-H2-advanced-capabilities.png | §8 Capability pills | openai_chat capability pills from Runtime (tool_calling, image_input, reasoning low/medium/high) |
| dev-I-credential-saved-detail.png | §20 Saved-credential state | Detail after key saved: "API Key 已保存 / Secure / Windows Credential Manager", 清除/更换 actions; UI & SQLite never echo the secret |
| dev-J-authstyle-chooser.png | §23 Keyless → API key | 鉴权方式 chooser (Bearer / x-api-key) shown when adding a key to a keyless provider |
| dev-K-delete-two-step.png | §22 Delete two-step | 删除… → inline confirmation (确认删除 / 取消) in danger zone |
| dev-K2-after-delete.png | §22/§24 Post-delete | Provider removed from list (only local-scripted-relay remains), single-step 删除… restored, CM clean |
| dev-L-singleflight-model-missing.png | §18/§29 | Single-flight double-click: exactly ONE GET /models hit relay (2 s delay mode); visible FAIL verdict "配置模型不存在或当前账户不可用: scripted-relay" (models 200 but model missing) |
| dev-M1-1440x900.png | §27 Window/DPI | Provider modal at 1440×900 logical (200% scale) |
| dev-M2-1280x800.png | §27 Window/DPI | Provider modal at 1280×800 logical |
| dev-M3-1100x760.png | §27 Window/DPI | Provider modal at ≈1100×760 logical: layout intact, no clipping/overlap |
| dev-N-installed-persist.png | §Packaging / Installed smoke | **Installed** NSIS build after full restart: checklist ✓ 2·模型 "Provider 已配置", 当前模型 = smoke-relay · model-a persisted, detail shows "API Key 已保存 / Secure / Windows Credential Manager", Test Connection ✓ models 端点 200 已确认模型 model-a |

Notes:

- §16/§17 (pre-save test must not persist; no concurrent probes) verified against Runtime
  state + relay3 request log, not visible in a single frame: providers list unchanged +
  0 Credential Manager entries after pre-save test; exactly one relay request for a
  double-clicked Test Connection under 2 s delay mode.
- §19 credential-endpoint binding 400s (edit protocol/base_url with saved key → 400;
  clear → allowed) verified at API level against the dev sidecar and covered by the
  source review; the UI edit form shows the keyless-edit path (Base URL edited 28901→28911
  and saved successfully with no saved credential).
- §18 request evidence: relay3.log went from 11 to 12 lines total after the double-click
  (`GET /v1/models auth='' x-api-key=''`).
- OAuth fail-closed (§26): no preset advertises OAuth; the modal footer states account
  sign-in only appears after a real third-party OAuth / Device Flow adapter is registered
  (visible in dev-A / dev-K2 captures).
