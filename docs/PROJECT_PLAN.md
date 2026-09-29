# PROJECT_PLAN — 版本路线与当前计划

> 总方案：`00_MM_AGENT_MASTER_PLAN.md`。本文件是版本级执行计划；完成一项勾一项。

## 版本总览

| 版本 | 主题 | 状态 |
|---|---|---|
| baseline | 骨架 + spec 文档 + 开发环境 + 环境探针 | complete |
| v0.1.0 | Specification + Agent Kernel | complete (historical tag) |
| v0.2.0 | Windows Workspace / Process / Permission | complete (historical tag) |
| v0.3.0 | Provider Abstraction（5 协议，offline contract-tested） | complete (historical tag) |
| v0.4.0 | S0 + G0 + S1 + G1 | complete (historical tag) |
| v0.5.0 | S2 + G2 + Multi-Agent + Red Team + DAG | complete (historical tag) |
| v0.6.0 | S3 + S4 + G3/G4 + Python/MATLAB/XeLaTeX | complete (historical tag) |
| v0.7.0 | S5 Review Arena + Ledgers + Guards + Rework | absorbed into rebuild; source complete |
| v0.8.0 | S5a/S5b + G5 + S6 + Delivery | complete (historical tag) |
| v0.9.0 | Desktop UI + Windows Packaging + Fidelity Run | complete; UI v2 Phase 1–4 PASS |
| v1.0.0 | Hardening + E2E + Final Fidelity + Final External Review | **release candidate — final stronger/ZCode green-G0 gate open** |

## 当前版本级事实（2026-09-29）

本文件下方早期版本的逐项 checkbox 是历史实施清单，不再作为当前 TODO。
当前执行真相请以 `docs/CURRENT_STATE.md`、`LOCAL_HANDOFF_REPORT.md`、
`docs/spec/FIDELITY_MATRIX.md` 为准。

当前剩余发布路径只有：

1. 当前 source-only S0 producer-contract 加固做 focused/full regression；
2. exact current HEAD 重新打包/安装/smoke；
3. stronger/ZCode real-provider 同炉 G0 PASS；
4. 最终 GPT-5.6 Sol release review；
5. 用户授权后再决定正式 `v1.0.0` tag / merge。

CI current-head Actions 不再是强制门，见
`docs/decisions/ADR-0001-local-release-evidence-instead-of-mandatory-ci.md`。

## 每版固定 Release Loop

PLAN → IMPLEMENT → UNIT TEST → INTEGRATION TEST → FAILURE INJECTION → SELF REVIEW →
UPDATE FIDELITY MATRIX → UPDATE DOCS → REVIEW PACKET → GPT-5.6 Sol High 外审 → TRIAGE →
FIX P0/P1 → REGRESSION TEST → FINAL VERIFY → COMMIT → TAG → UPDATE CURRENT_STATE → 下一版。

## v0.1.0 范围（Specification + Agent Kernel）

必做：
- [x] repo skeleton、.reference 只读区、source snapshot、source map、fidelity matrix
- [ ] SQLite schema v1（projects/runs/stages/tasks/task_dependencies/agent_invocations/messages/tool_calls/artifacts/contracts/issues/issue_history/checkpoints/events/providers/model_profiles/usage_records/settings）+ migrations
- [ ] append-only event store
- [ ] 状态枚举（PENDING/READY/QUEUED/RUNNING/WAITING_TOOL/SUCCEEDED/FAILED/CANCEL_REQUESTED/CANCELLED/BLOCKED/DEFERRED）+ 合法迁移表
- [ ] normalized provider interface（base/normalized/capabilities）+ mock provider
- [ ] tool registry + filesystem tool + python tool
- [ ] minimal agent loop（tool-calling，权限检查点，tool_call 持久化）
- [ ] artifact validation（expected artifacts + schema 校验）
- [ ] typed errors
- [ ] cancellation token 基础
- [ ] project workspace creation（目录约定 + project.db）

验收（Mock Agent 闭环）：
- [ ] Mock Agent 写 Python → 跑 → 见 traceback → 改 → 重跑 → 产出通过校验的 artifact，全程事件可回放

不做：MM 具体 S0–S6 业务逻辑、真实 Provider、Tauri UI。

## 环境事实（2026-09-19 勘查）

- Windows 11，git 2.55，Python 3.11.9（另有 3.12/3.13；开发用 uv 管理的独立 .venv），uv 0.12.5，node 24.18，npm 11.16（pnpm 用 corepack 启用），cargo 未装（v0.9 前 rustup）
- XeLaTeX：`D:\Apps\texlive\texlive\2026\bin\windows\xelatex.exe`（发现逻辑必须深搜）
- MATLAB：`D:\Apps\Matlab\bin\matlab.exe`（v26.1，直接根目录布局）
- 参考快照：MM-Final-Skill `5f507e0b`，Mrite `72f87c78`（详见 SOURCE_SNAPSHOT）
- 外审通道：ZCode 内置浏览器 ChatGPT Web（wghela Plus），GPT-5.6 Sol High 已实测可用；质量优先不省 token
- API key 政策：无真实 key；v1.0 以 mock-E2E 收尾，real-provider-tested 如实标 unverified
- 版本循环全自动（用户已确认），外审修复循环 ≤2 轮 focused re-review
