# CURRENT_STATE — 当前状态（每次接手先读这个）

- **当前版本**: v0.4.0 进行中（S0/G0/S1/G1 核心已提交）→ 外审+tag 待完成
- **最近更新**: 2026-09-19
- **测试**: 140 passed, ruff clean
- **Git**: 3 tags（v0.1.0/v0.2.0/v0.3.0）+ v0.4.0 core commit 1d6fb69

## 已发布

### v0.1.0 — Agent Kernel（外审 8 轮 GO）
SQLite schema v1（19 表 + append-only 触发器）、状态机 11 态 + 租约 CAS + 专用收口 +
transactional outbox、typed errors（ErrorKind 18 类）、取消令牌、
路径策略（词法 reparse walk + ADS/保留名/尾点/空白拒绝）、角色权限（default deny + host_code），
工作区（中文目录 + 单运行锁 + pid 存活检查）、产物校验 + 内容寻址封存、
归一化 Provider 接口 + Mock、工具注册表（fs/python + lifecycle gate）、AgentLoop、
阈值常量 + 角色分档表。详见 docs/runs/v0.1.0.md。

### v0.2.0 — Windows Workspace / Process / Permission（外审 16 轮 GO）
ProcessManager（Job Object KILL_ON_JOB_CLOSE + CREATE_SUSPENDED 原子启动 +
per-name 生命周期锁 + compare-and-remove + 三态取消因果（killed/natural_exit/failed）+
输出预算 + 确认式终止 + shutdown 统一 resolution）、EnvironmentManager（XeLaTeX 深搜 +
MATLAB 双布局 + capability cache + 体检分级）、17 角色注册表（scopes/tools/reasoning +
红队权限层隔离 + host_code）、python 工具接入 Job Object。
详见 docs/runs/v0.2.0.md。

### v0.3.0 — Provider Abstraction（外审 3 轮 GO）
五协议适配器（openai_chat/openai_responses/anthropic_messages/gemini/openai_compatible）；
Normalized* 类型；parse_retry_after（delta/HTTP-date/畸形→None）接线五适配器 429；
safe_json（畸形 2xx → PROVIDER_PROTOCOL）；stop fail-closed（未知 finish_reason 不默认 END_TURN）；
能力诚实（streaming=False/image_input=False/reasoning_levels 如实）；
密钥边界（ProviderConfig ENV:/WINCRED: 前缀强制 + redact_secret）；
role routing / model profiles；Responses continuation_items。
详见 docs/runs/v0.3.0.md。

## 当前进行中（v0.4.0 — S0+G0+S1+G1）

已提交（1d6fb69）：
- [x] contracts/s0_contracts.py（ProblemContract Pydantic 需求号校验）
- [x] gates/g0.py（G0 门检 8 条判据 + 空问题检查）
- [x] pipeline/s0_s1.py（run_s0 + check_g1 + run_s1）
- [x] roles/prompts.py（clean-room Reader/AnswerPredictor/Planner）
- [x] roles/registry.py（answer_predictor scope 修复）
- [x] tests/pipeline/（G0 门检 10 项 + S0/S1 管线 2 项）

待完成：
- [ ] S1 原型路线执行（prototype run + route judgement）
- [ ] 三档 profiles 深度/标准/快速
- [ ] Run Dashboard API
- [ ] review packet → GPT 外审 → 修 P0/P1 → tag v0.4.0

## 下一步接手

1. 读本文件 + PROJECT_PLAN + FIDELITY_MATRIX
2. `git log --oneline -5` 恢复上下文
3. 继续实现 v0.4.0 待完成项（S1 原型执行/三档/API）
4. 完成后走 review packet → GPT 外审 → tag 循环
5. 之后 v0.5.0（S2/G2/RedTeam/DAG）→ v0.6.0（S3/S4/G3/G4/工具链）→ … → v1.0.0

## 关键环境事实

- 外审：内置浏览器 ChatGPT（wghela Plus / GPT-5.6 Sol High）
- API key：无真实 key，一切 Provider 实现为 offline contract-tested
- XeLaTeX：`D:/Apps/texlive/texlive/2026/bin/windows/xelatex.exe`
- MATLAB：`D:/Apps/Matlab/bin/matlab.exe`（直接根目录布局）
- 教训：盲 str.replace 用 assert 验证；pywintypes.error ≠ OSError（用 _WIN_ERRORS）；
  pytest fixture tmp_path 清理前必须 close Database；MockProvider 脚本跨任务共享 cursor
