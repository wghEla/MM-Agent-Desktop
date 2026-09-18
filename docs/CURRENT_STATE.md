# CURRENT_STATE — 当前状态（每次接手先读这个）

- **当前版本**: baseline → v0.1.0（Agent Kernel）
- **阶段**: 初始化完成，v0.1.0 实现中
- **最近更新**: 2026-09-19

## 已完成

- [x] git init（main），.gitignore（.reference/.venv/密钥等）
- [x] `.reference/MM-Final-Skill` @ 5f507e0b、`.reference/Mrite` @ 72f87c78（快照固定，见 docs/spec/SOURCE_SNAPSHOT.md；MM 仓库以 protectNTFS=false + sparse-checkout 绕过 6 个 NTFS 非法文件名）
- [x] 规格精读：README/SKILL.md/流程与档位/铁律/角色与契约/提示词与回流/监督清单 + 调度器/回路/本地蜂巢/契约表/统稿守卫 全文 + 蜂群驾驶（结构+wave/红队复算/G2门/级联/S5审稿场）+ 门检判据清单 + 审计结构
- [x] `00_MM_AGENT_MASTER_PLAN.md`（总方案入库副本）
- [x] docs/spec/{SOURCE_SNAPSHOT, SOURCE_MAP, FIDELITY_MATRIX, KNOWN_DEVIATIONS}.md
- [x] AGENTS.md、docs/{PROJECT_PLAN, ARCHITECTURE, CURRENT_STATE}.md、docs/runs/RUN_LOG.md

## 进行中（v0.1.0）

- [ ] pyproject.toml + uv venv + 依赖安装
- [ ] mmagent 包骨架（state/agent/providers/tools/workspace/runtime/orchestration/mm）
- [ ] SQLite schema v1 + migrations + 状态枚举 + event store
- [ ] normalized provider 接口 + mock provider
- [ ] tool registry + fs/python tools + 权限检查点（v0.1 基础版：workspace 内路径校验）
- [ ] agent loop + artifact 校验 + typed errors + cancellation token
- [ ] workspace 创建 + Mock Agent 闭环验收（写py→跑→traceback→改→重跑→artifact PASS）
- [ ] tests: unit + integration + failure injection
- [ ] review packet → GPT-5.6 Sol High 外审 → 修 P0/P1 → tag v0.1.0

## 下一步

v0.1.0 收尾后自动进 v0.2.0（Windows Workspace/Process/Permission），按 PROJECT_PLAN 循环。

## 环境备忘

- 外审：内置浏览器 ChatGPT（wghela Plus / GPT-5.6 Sol High），标签页已 handoff 保留。
- 无真实 API key：一切 provider 相关先 mock/contract 级。
- XeLaTeX：`D:\Apps\texlive\texlive\2026\bin\windows\xelatex.exe`；MATLAB：`D:\Apps\Matlab\bin\matlab.exe`。
