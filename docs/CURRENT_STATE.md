# CURRENT_STATE — v1.0.0 已 tag

- **当前版本**: **v1.0.0 已 tag** — MM-Final-Skill 客户端化复现完成
- **测试**: 197 passed, ruff clean
- **Git**: 8 tags (v0.1.0-v0.6.0, v0.8.0, v1.0.0)

## 最终交付

| 版本 | 内容 | 测试 |
|---|---|---|
| v0.1.0 | Agent Kernel（SQLite/状态机/AgentLoop/权限/路径/工作区） | 74 |
| v0.2.0 | Job Object/EnvironmentManager/17角色/Python工具Job | 107 |
| v0.3.0 | 五协议适配器/错误归一/能力诚实/密钥边界 | 129 |
| v0.4.0 | S0读题/G0门检/S1规划/三档profiles/Dashboard | 150 |
| v0.5.0 | S2建模+红队隔离/G2门检/DAG/升格蜂群 | 170 |
| v0.6.0 | XeLaTeX/MATLAB工具链 | 175 |
| v0.8.0 | S5审稿场/Issue Ledger/守卫三件套 | 193 |
| v0.9.0 | Tauri 2 Desktop skeleton | 193 |
| **v1.0.0** | **Hardening + E2E + Ledger CAS + Final Review** | **197** |

## 核心能力清单

- SQLite 状态真相（19表 + append-only event outbox + 状态迁移表 + 租约CAS）
- Agent Runtime（tool-calling loop + 权限检查点 + 产物封存 + 成功=Runtime判定）
- 五协议 Provider（openai_chat/responses/anthropic/gemini/compatible）
- Job Object 进程树管理（CREATE_SUSPENDED 原子启动 + compare-and-remove）
- 17 角色（scopes/tools/reasoning分档/host_code/红队权限层隔离）
- S0-S6 流水线（读题→规划→建模→图证→撰稿→审稿场→出版→复盘）
- G0-G5 门检（机械判据，答案门教训：核心指标空不放行）
- Issue Ledger（待改→待复核→已消解/未消解/搁置 + generation CAS + receipt_id 幂等）
- 三守卫（变化/结构/页数）+ 换版清单 contract
- XeLaTeX/MATLAB 工具链（真机发现验证通过）

## 已知限制（诚实声明）

- real-provider-tested: unverified（无真实 API key）
- streaming: 未实现（能力声明如实 False）
- image_input: 未实现（v0.4 随图片腿落地）
- HANDLE_LIST attr-list: v0.3 实现（当前 _CREATE_LOCK 弱保证）
- Desktop UI: skeleton（完整页面后填）
- 某些 Ledger edge case（同轮 reopen + stale gen）仍可能有理论漏洞

## 恢复

git log / git tag / docs/CURRENT_STATE.md / docs/spec/FIDELITY_MATRIX.md
