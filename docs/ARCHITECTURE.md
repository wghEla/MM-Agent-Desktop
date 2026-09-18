# ARCHITECTURE — 产品与技术架构（Architecture Freeze）

> 依据总方案 §4/§6 固化。除非 P0 证据，不推翻。

## 1. 总览

```text
Tauri 2 + React + TypeScript（GUI，不承载状态真相）
        │  HTTP/IPC（mmagent.api）
        ▼
Python 3.11 Core（asyncio + Pydantic + SQLite）
  ├─ mmagent.api            Desktop 稳定 API（projects/runs/providers/artifacts）
  ├─ mmagent.orchestration  engine / scheduler / dag / node / gate / retry / resume
  ├─ mmagent.agent          Agent Runtime：loop / context / session / tool_protocol / budget
  ├─ mmagent.providers      协议抽象：openai_responses / openai_chat / anthropic_messages / gemini / openai_compatible
  ├─ mmagent.runtime        process(Windows Job Object) / cancellation / environment / concurrency / rate_limit
  ├─ mmagent.workspace      root / path_policy / permissions / snapshot / artifacts
  ├─ mmagent.tools          registry / filesystem / python / matlab / latex / pdf / spreadsheet / document / image / shell(受限)
  ├─ mmagent.state          db / models / repositories / events / checkpoints / migrations
  └─ mmagent.mm             数模领域层：config / contracts / roles(17) / pipeline(S0–S6) / gates(G0–G5) / guards / ledger / templates
```

## 2. 状态模型

- **SQLite 唯一 authoritative mutable state**（`<projectRoot>/.mmagent/project.db`）。
- append-only `events` 表：一切状态迁移与运行事件可回放。
- 核心表：projects, runs, stages, tasks, task_dependencies, agent_invocations, messages,
  tool_calls, artifacts, contracts, issues, issue_history, checkpoints, events, providers,
  model_profiles, usage_records, settings。
- Task 状态枚举：PENDING / READY / QUEUED / RUNNING / WAITING_TOOL / SUCCEEDED / FAILED /
  CANCEL_REQUESTED / CANCELLED / BLOCKED / DEFERRED（显式迁移表，禁模糊布尔）。
- JSON/Markdown（交接/*.json、台账/*.json）是**可读 carrier 与跨角色契约文件**，不是状态真相；
  Agent 不直接写 SQLite，只能经 Runtime/Repository。

## 3. Agent Runtime

- tool-calling loop：assemble context → provider.generate → tool_call? → permission check →
  execute → persist tool_call+result → feed back。
- Invocation 元数据：invocation_id/task_id/role_id/provider_profile/model/reasoning/
  context_manifest/started_at/ended_at/status/usage。
- 成功判定（declared != enforced）：expected artifacts 存在 ∧ schema valid ∧ 必要 tool 执行成功 ∧
  node verifier PASS ∧ 状态事务成功。
- Provider 按协议抽象（NormalizedMessage/ToolCall/Response/Usage/CapabilitySet）；
  reasoning 档位不支持时声明 unsupported，不伪装。

## 4. 权限与工作区

- Default deny；role 声明 read_scopes/write_scopes/allowed_tools/network/shell。
- 路径检查：canonicalize、拒 `..`、拒越界绝对路径、Windows junction/reparse 逃逸检测、
  Runtime 提供 temp、shell cwd 锁工作区。
- 红队硬隔离：红队 role 的 read_scopes 不含 `求解/**`、建模笔记、解读 → 权限层 PermissionDenied。

## 5. Windows 运行时

- 进程树所有权：Windows Job Object（pywin32）+ process registry + timeout + cancel + hard kill
  fallback + orphan detection。腿超时 < 波次超时（防双写）；重派前回收旧副本。
- 受管 Python：uv 维护；产品版 `%LOCALAPPDATA%\MM-Agent\runtime\python|venv`；开发期仓库 `.venv`。
- 工具发现：XeLaTeX 深搜 `D:\Apps\texlive\**\bin\windows\xelatex.exe`；
  MATLAB 兼容 `<root>/bin/matlab.exe` 与 `<root>/R*/bin/matlab.exe`；capability cache + UI 显示。
- Secret：Windows Credential Manager；SQLite 只存 reference；红线见 AGENTS.md。

## 6. 领域层（mm.mm）

- contracts/：Pydantic 唯一 schema 权威（题面契约/数据档案/计划/假设台账/结果声明/红队/仲裁/
  实验记录/换版清单/审稿/复盘…）。消费者只能 import，不得复写字段（contract tests 强制）。
- roles/：17 角色，每个 `role.yaml + prompt.md + tests`（clean-room prompt；schema 引用 contracts）。
- pipeline/：s0..s6 + g5_publish；gates/：g0..g5 + 叙事门；guards/：change/structure/page/stale_value；
  ledger/：issue_ledger/repair_receipt/verdict_merge/fuse；config/：profiles/thresholds/role_routing。

## 7. 关键阈值默认值（thresholds.py，复现上游行为值）

红队容差 0.01；图评 2 轮/7.0；章评 2 轮/7.0；审稿达标 8.6/平台期 0.15；美观 8.5；
变化守卫 0.45/升格 0.70；页数守卫 +max(10%, 2页)；默认并发 4（429 降并发，下限 2）；
熔断 attempt≥2；正文 ≤20 页；图 16–22；% src 覆盖率 ≥0.6；小数 ≤4。
档位：深度/标准/快速 参数表见 FIDELITY_MATRIX D8–D10。

## 8. 桌面端（v0.9）

页面：首页/新建项目/Run Dashboard（左阶段树/中当前节点/右事件+台账+产物/底控制条）/
Provider Settings（Test Connection/role routing）/Artifact Viewer（含 PDF 预览）。
GUI 只调 Backend API。打包：Tauri Windows installer（NSIS/MSI）。
