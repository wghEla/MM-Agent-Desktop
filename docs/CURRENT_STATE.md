# CURRENT_STATE — 当前状态（每次接手先读这个）

- **当前版本**: v0.1.0 已 tag → **v0.2.0（Windows Workspace / Process / Permission）进行中**
- **最近更新**: 2026-09-19

## 已发布

### v0.1.0 — Specification + Agent Kernel（GO，外审 8 轮）

- 18 个内核模块：SQLite schema v1（19 表 + events append-only 触发器）、迁移器、
  事件存储、仓储层（状态机 11 态 + 租约 CAS + 专用收口函数 + outbox 事件）、
  typed errors、取消令牌、路径策略（词法 reparse + Win32 加固）、
  角色权限（scopes + host_code 位）、工作区（中文目录 + 单运行锁）、
  产物校验 + 内容寻址封存、归一化 Provider 接口 + Mock、
  工具注册表（fs.read/write/list + python.run 受管解释器）、AgentLoop、
  预算骨架、阈值常量、项目 API。
- 测试 74 全过（unit / integration / adversarial+failure / tools），ruff 干净。
- 外审：GPT-5.6 Sol High 8 轮（R1: 3P0/8P1/8P2 → R8: GO），全部 P0/P1 闭环，
  原文见 docs/reviews/v0.1.0-external-review*.md（8 份）。

## 进行中（v0.2.0）

计划要点（总方案 §29）：

- [ ] path_policy 强化：handle-based open（GetFinalPathNameByHandle）评估/落地
- [ ] Windows Job Object 进程树管理（pywin32），替代 taskkill /T；orphan 检测
- [ ] 角色权限系统完整化（role scope 全量测试矩阵）
- [ ] Environment Manager：XeLaTeX 深搜发现、MATLAB 双布局发现、capability cache、体检 API
- [ ] 受管 Python bootstrap（uv）
- [ ] v0.1 遗留 P2 清理：docstring 同步（transition_task/mark_task_cancelled）、create_invocation 私有化评估
- [ ] 外审循环后 tag v0.2.0

## 环境备忘

- 外审：内置浏览器 ChatGPT（wghela Plus / GPT-5.6 Sol High），标签页 handoff 保留，直接复用。
- API key：无真实 key；provider 层 mock/contract 级验证，real-provider 标 unverified。
- XeLaTeX：`D:/Apps/texlive/texlive/2026/bin/windows/xelatex.exe`（发现逻辑深搜）。
- MATLAB：`D:/Apps/Matlab/bin/matlab.exe`（双布局兼容）。
- 教训（round6 事故）：改源码禁止盲 str.replace——必须 Read 后 Edit，或 assert + getsource 验证。
