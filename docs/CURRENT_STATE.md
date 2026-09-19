# CURRENT_STATE — 当前状态（每次接手先读这个）

- **当前版本**: v0.3.0 已 tag → **v0.4.0（S0/G0/S1/G1）待实现**
- **最近更新**: 2026-09-19

## 已发布版本

### v0.1.0 — Agent Kernel（外审 8 轮 GO）
SQLite schema v1（19 表 + append-only 触发器）、状态机 11 态 + 租约 CAS + 专用收口函数 +
transactional outbox、typed errors、取消令牌、路径策略（词法 reparse + Win32 加固）、
角色权限（default deny + host_code 位）、工作区（中文目录 + 单运行锁）、
产物校验 + 内容寻址封存、归一化 Provider 接口 + Mock、工具注册表、AgentLoop、
预算骨架、阈值常量、项目 API。74→107 测试。

### v0.2.0 — Windows Workspace / Process / Permission（外审 16 轮 GO）
ProcessManager（Job Object KILL_ON_JOB_CLOSE + CREATE_SUSPENDED 原子启动 +
per-name 生命周期锁 + compare-and-remove + 三态取消因果 + 输出预算 +
确认式终止）、EnvironmentManager（XeLaTeX 深搜 + MATLAB 双布局 + capability cache +
体检分级）、17 角色注册表（scopes/tools/reasoning 分档 + 红队权限层隔离）、
python 工具接入 Job Object、路径加固（ADS/保留名/尾点/reparse）。

### v0.3.0 — Provider Abstraction（外审 3 轮 GO）
五协议适配器（openai_chat/openai_responses/anthropic_messages/gemini/openai_compatible）
全部归一到 Normalized*；parse_retry_after 接线五适配器 429 路径；
错误归一 + PROVIDER_PROTOCOL 新错误类 + stop fail-closed；
能力诚实（streaming=False/image_input=False/reasoning_levels 如实）；
密钥边界（ProviderConfig ENV:/WINCRED: 前缀强制 + redact_secret 出口）；
role routing / model profiles；Responses continuation_items。
129 测试，ruff 全绿。

## 下一步（v0.4.0 — S0 + G0 + S1 + G1）

总方案 §29 v0.4.0 必做：
- [ ] input import（PDF parse/render、XLSX/CSV/DOCX inventory）
- [ ] Reader 角色（读题官）：产 交接/题面契约.json + 交接/数据档案.json + 读题体检.md
- [ ] Answer Predictor（答卷预测官）：产 预测 + 需求追踪矩阵
- [ ] Planner（规划师）：产 交接/路线侦察.json + 交接/计划.json
- [ ] 原型路线真实执行（prototype routes）
- [ ] route judgement + plan finalize
- [ ] G0 gate（题面契约/数据档案机械项，判据见 SOURCE_MAP §2 G0 行）
- [ ] G1 gate（计划/路线/原型证据）
- [ ] 深度/标准/快速三档差异（profiles）
- [ ] Run Dashboard API（第一版）
- [ ] 每角色 contract + pipeline test + mock provider 测试
- [ ] 更新 FIDELITY_MATRIX A1–A4 / D8–D10 / C 组
- [ ] review packet → GPT 外审 → 修 P0/P1 → tag

## 参考规格（v0.4.0 重点读）

- `.reference/MM-Final-Skill/流水线/角色/读题官.md` / `答卷预测官.md` / `规划师.md`
- `.reference/MM-Final-Skill/流水线/运行时/门检.py` G0 函数
- `.reference/MM-Final-Skill/流水线/蜂群驾驶.py` _S1侦察/_S1原型/_S1裁决/_S1定稿/_G1检查
- `docs/spec/SOURCE_MAP.md` §1 S0/S1 行 + §2 G0/G1 行

## 环境备忘

- 外审：内置浏览器 ChatGPT（wghela Plus / GPT-5.6 Sol High）。注意：浏览器可能被重置，
  重开会话后找最近聊天列表或发起新会话发证据即可。
- API key：无真实 key；provider 层 mock/contract 级验证，real-provider 标 unverified。
- XeLaTeX：`D:/Apps/texlive/texlive/2026/bin/windows/xelatex.exe`；MATLAB：`D:/Apps/Matlab/bin/matlab.exe`。
- 教训：改源码禁止盲 str.replace（用 assert+getsource 验证）；stash drop 丢代码（fsck 恢复）；
  pywintypes.error 不是 OSError 子类（用 _WIN_ERRORS 元组）；浏览器 DOM snapshot 需要 evaluate() 提取长文本。
