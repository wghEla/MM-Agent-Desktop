# CURRENT_STATE — 当前状态（每次接手先读这个）

- **当前版本**: v0.8.0 已 tag → **v0.9.0 Desktop UI + v1.0.0 Hardening 待实现**
- **测试**: 193 passed, ruff clean
- **Git**: 7 tags (v0.1.0-v0.6.0, v0.8.0)

## 版本总览

| 版本 | 内容 | 测试 | 状态 |
|---|---|---|---|
| v0.1.0 | Agent Kernel: SQLite 19表/状态机/AgentLoop/权限/路径/工作区 | 74 | ✅ tag |
| v0.2.0 | Job Object/EnvironmentManager/17角色/Python工具Job | 107 | ✅ tag |
| v0.3.0 | 五协议适配器/错误归一/能力诚实/密钥边界 | 129 | ✅ tag |
| v0.4.0 | S0读题/G0门检/S1规划/三档profiles/Dashboard | 150 | ✅ tag |
| v0.5.0 | S2建模+红队隔离/G2门检/DAG/升格蜂群/降级放行 | 170 | ✅ tag |
| v0.6.0 | XeLaTeX编译/MATLAB batch/页数/日志检查 | 175 | ✅ tag |
| v0.8.0 | S5审稿场/Issue Ledger/守卫三件套(变化/结构/页数) | 193 | ✅ tag |
| v0.9.0 | Desktop UI (Tauri) | — | 待实现 |
| v1.0.0 | Hardening/E2E/Final Review | — | 待实现 |

## 下一步

### v0.9.0 Desktop UI
- [ ] Tauri 2 + React + TypeScript 脚手架
- [ ] 项目创建/打开/导入
- [ ] Run Dashboard（阶段树/事件流/台账/产物）
- [ ] Provider Settings
- [ ] Windows installer

### v1.0.0 Hardening + E2E
- [ ] 完整合成题 E2E
- [ ] crash recovery / pause / resume
- [ ] provider failure / rate limit / stale value 测试
- [ ] Final review packet → GPT 外审 → tag v1.0.0

## 核心模块清单

| 模块 | 路径 | 功能 |
|---|---|---|
| state/ | models/db/events/repositories/schema_v1 | SQLite 状态真相 + 事件 outbox |
| agent/ | loop/context/budget/errors | Agent Runtime（tool-calling loop） |
| providers/ | 5 适配器 + normalized/capabilities/mock/_http_util | 归一化 Provider 层 |
| tools/ | registry/filesystem/python/latex/matlab | 工具执行（权限检查点在 registry） |
| workspace/ | root/path_policy/permissions/artifacts | 工作区 + 权限 + 产物封存 |
| runtime/ | process/cancellation/environment | Job Object/取消/工具发现 |
| orchestration/ | dag | 拓扑分层/环检测/下游闭包 |
| mm/contracts/ | s0_contracts/s2_contracts | Pydantic schema 权威 |
| mm/roles/ | registry/prompts | 17 角色 + clean-room 提示词 |
| mm/pipeline/ | s0_s1/s2_model/s5_review | S0-S6 流水线节点 |
| mm/gates/ | g0/g2 | 门检机械判据 |
| mm/guards/ | guards | 变化/结构/页数守卫 |
| mm/ledger/ | issue_ledger | 意见台账状态机 |
| mm/config/ | thresholds/profiles/role_routing | 阈值/档位/路由 |
| api/ | projects/dashboard | Desktop API |

## 恢复序列

1. 本文件 → PROJECT_PLAN → FIDELITY_MATRIX
2. `git log --oneline -10` 看最近变更
3. 继续当前 TODO

## 关键教训

- 盲 str.replace 用 assert+getsource 验证
- pywintypes.error ≠ OSError（用 _WIN_ERRORS 元组）
- MockProvider 脚本跨任务共享 cursor（每任务需足够回合）
- tmp_path 清理前 close Database
- GPT 外审固定同一会话
- CREATE_SUSPENDED 原子启动：ctor 放 rollback scope 内
- 终止确认 = Job ActiveProcesses==0（不只 root 退出）
- _resolve 统一出口 = close+cleanup+remove_quarantined+清标记+compare-remove+unresolved.pop
