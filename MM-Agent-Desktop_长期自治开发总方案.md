# MM-Agent Desktop：MM-Final-Skill 客户端化复现——长时自治开发总方案

> **用途**：本文件是 ZCode / GLM-5.3-Flash 的长期实施总任务书，也是项目的最高层产品与工程规格。  
> **核心目标不是“做一个通用数模 Agent”**，而是把 `qybaihe/MM-Final-Skill` 的论文铸造厂能力，以独立桌面客户端 + 自研 Agent Runtime + 用户自配 API 的方式尽可能高保真复现。  
> **参考 Skill**：<https://github.com/qybaihe/MM-Final-Skill>  
> **产品形态参考**：<https://github.com/Rzna-5559/Mrite>（仅参考“一键导入题目/数据→自动求解→论文”的产品体验；其 `App/` 当前不是可复用实现）  
> **首发平台**：Windows 11  
> **实施模型**：ZCode 中的 GLM-5.3-Flash  
> **外部顾问 / Reviewer**：ZCode 内置浏览器中的 ChatGPT Web，GPT-5.6 Sol，High thinking  
> **最终完成条件**：真实 `v1.0.0` tag + Windows 可运行客户端 + 端到端流水线 + 外审无未解决 P0/P1。

---

## 0. 一句话定义

MM-Agent Desktop 是 **MM-Final-Skill 的独立客户端化重实现**：

```text
题目 PDF + 附件
      ↓
S0 吃透题目
      ↓ G0
S1 战略锦标赛
      ↓ G1
S2 建模求解 + 红队独立复算
      ↓ G2/每问
S3 图证 + 图评
      ↓ G3
S4 论文撰写 + 章评 + 闭卷读者 + 统稿 + 摘要蜂群
      ↓ G4
S5 多路审稿场 + 台账 + 定向回炉 + 熔断
      ↓
S5a 摘要定稿
      ↓
S5b 美化
      ↓ G5 出版门
S6 逐页终审 + 整改 + 出版收割 + 复盘
      ↓
PDF + LaTeX + 图 + 求解脚本 + 交接 + 审稿记录 + 复盘报告
```

变化只有“执行载体”：

```text
原 Skill：
蜂群驾驶.py
  → 本地蜂巢.py
  → role.sh / 图片腿.sh
  → codex exec / claude -p

新客户端：
Pipeline Orchestrator
  → Agent Runtime
  → Provider Adapter
  → 用户配置的模型 API
  → Tool Runtime
  → Python / MATLAB / XeLaTeX / Files / PDF / Spreadsheet / Image
```

**业务行为尽量复现，CLI 依赖全部移除。**

---

# 1. 项目优先级：谁是“真规格”

出现冲突时，按以下优先级处理：

1. **用户明确要求**
2. **本总方案**
3. **MM-Final-Skill 当前公开实现所体现的行为不变量**
4. `MM-Final-Skill/.claude/skills/paper-foundry/references/*`
5. `MM-Final-Skill/流水线/蜂群驾驶.py`、`回路.py`、`调度器.py`、`运行时/*`
6. MM-Final-Skill 角色文件所体现的职责和输入输出契约
7. Mrite 的产品交互思路
8. OpenHands / Cline / Continue / Aider 等 Agent 项目的工程结构
9. 实施模型自己的偏好

**禁止**因为更容易实现而把第 3～6 项的核心行为删掉，然后仍声称“复现 MM-Final-Skill”。

---

# 2. 开发开始时必须建立只读参考区

项目仓库内创建：

```text
.reference/                 # 必须加入 .gitignore
  MM-Final-Skill/           # 只读参考，不提交
  Mrite/                    # 只读参考，不提交
```

启动时：

```powershell
git clone https://github.com/qybaihe/MM-Final-Skill .reference/MM-Final-Skill
git clone https://github.com/Rzna-5559/Mrite .reference/Mrite
```

如果已存在则 `git fetch`，但**不能自动改写正在使用的规格快照**。

第一次 baseline 时读取并记录：

```text
docs/spec/SOURCE_SNAPSHOT.md
```

内容必须包括：

- MM-Final-Skill URL
- 读取时的 HEAD commit SHA
- Mrite URL
- 读取时的 HEAD commit SHA
- 日期
- 哪些源文件被视为规格来源
- 许可证状态说明

后续整个 v0.x 默认以该固定 SHA 为复现目标。若上游更新，先建立 ADR 再决定是否升级规格快照。

---

# 3. 许可证与 clean-room 约束

MM-Final-Skill README 当前说明其主体许可证尚未补充、保留权利。因此：

- 可以研究公开行为、架构、状态机、阶段划分、契约、故障经验；
- 可以做功能兼容重实现；
- **不要直接复制其 Python / Shell 源码进入产品仓库；**
- **不要整段复制 17 个角色 Prompt；**
- Prompt 要依据角色职责、输入、输出、约束重新编写；
- 新代码必须采用自己的模块结构与接口；
- `docs/spec/SOURCE_MAP.md` 记录“观察到的行为 → 新实现位置”，而不是拷贝源码。

为了防止实施模型偷懒，项目建立：

```text
docs/spec/SOURCE_MAP.md
docs/spec/FIDELITY_MATRIX.md
docs/spec/KNOWN_DEVIATIONS.md
```

`KNOWN_DEVIATIONS.md` 任何时候都必须真实记录“与参考 Skill 不同的地方”。

---

# 4. 产品级 Architecture Freeze

除非出现 P0 级工程证据，否则不得反复推翻以下决定。

## 4.1 Desktop

```text
Tauri 2
React
TypeScript
```

职责：

- 项目创建/打开
- 输入导入
- Provider / 模型设置
- 流水线状态可视化
- 当前 Agent / Tool Call / Log
- 暂停 / 恢复 / 停止 / 重试
- Artifact 浏览
- PDF 预览
- 审稿台账查看
- 最终导出

GUI **不承载业务状态机真相**，仅调用 Backend API。

---

## 4.2 Backend / Core

```text
Python 3.11
Pydantic
SQLite
asyncio
```

Python 3.11 作为产品受管 runtime 默认版本，避免依赖用户现有 Python。

开发仓库：

```text
.venv/
```

最终客户端：

```text
%LOCALAPPDATA%\MM-Agent\
  runtime\
    python\
    venv\
  config\
  cache\
  logs\
  projects\
```

推荐用 `uv` 创建/维护环境；如果采用别的方式，需 ADR 说明。

---

## 4.3 State

**SQLite 是唯一 authoritative mutable state。**

原 Skill 的：

```text
状态.json
日志/*.done
日志/*.pid
```

不得继续作为核心真相源。

它们可以为了可读性导出，但运行恢复必须依赖 SQLite + append-only events。

核心表至少：

```text
projects
runs
stages
tasks
task_dependencies
agent_invocations
messages
tool_calls
artifacts
contracts
issues
issue_history
checkpoints
events
providers
model_profiles
usage_records
settings
```

状态枚举必须显式：

```text
PENDING
READY
QUEUED
RUNNING
WAITING_TOOL
SUCCEEDED
FAILED
CANCEL_REQUESTED
CANCELLED
BLOCKED
DEFERRED
```

不得用模糊布尔值替代。

---

## 4.4 Provider

按**协议**抽象，而不是按品牌硬编码。

```text
core/providers/
  base.py
  capabilities.py
  normalized.py
  openai_responses.py
  openai_chat.py
  anthropic_messages.py
  gemini.py
  openai_compatible.py
```

所有 Adapter 归一化为：

```text
NormalizedMessage
NormalizedContentPart
NormalizedTool
NormalizedToolCall
NormalizedToolResult
NormalizedResponse
Usage
ProviderError
CapabilitySet
```

必须至少支持：

- tool calling
- text
- image input（协议支持时）
- streaming（协议支持时）
- max output
- reasoning / thinking 参数（有则声明，无则不能伪装支持）
- usage
- retry-after
- rate-limit
- cancellation

用户设置的：

```text
base_url
api_key
model
protocol
reasoning level
timeout
```

不能写死。

### Secret 存储

Windows 正式版优先使用：

```text
Windows Credential Manager / OS Keychain
```

SQLite 只保存 secret reference，不保存明文 key。

禁止 API Key 进入：

- Git
- prompt
- event payload
- debug log
- crash dump
- review packet
- exported project

---

# 5. Windows 环境固定约定

## 5.1 XeLaTeX

用户机器根目录：

```text
D:\Apps\texlive
```

不要硬编码年份。

发现逻辑：

```text
D:\Apps\texlive\*\bin\windows\xelatex.exe
```

若多个版本：

1. 优先最新可解析版本；
2. 执行 `xelatex --version`；
3. 把实际路径记录到本机 capability cache；
4. UI 显示“已发现”；
5. 不改变用户安装。

工具层统一暴露：

```text
latex.compile
latex.inspect_log
latex.page_count
latex.render_pages
```

Agent 不自己猜路径。

---

## 5.2 MATLAB

用户机器根目录：

```text
D:\Apps\Matlab
```

发现：

```text
D:\Apps\Matlab\R*\bin\matlab.exe
```

统一工具：

```text
matlab.run_script
matlab.run_command
matlab.list_toolboxes
matlab.probe
```

执行尽量使用：

```text
matlab.exe -batch "..."
```

禁止 Agent 自己找 exe。

---

## 5.3 Python 科学栈

受管 venv 初始至少安装：

```text
numpy
pandas
scipy
matplotlib
scikit-learn
sympy
statsmodels
openpyxl
xlrd
python-docx
pypdf
PyMuPDF
Pillow
networkx
pydantic
```

可加入其他依赖，但：

- 统一记录 lockfile；
- 运行中的 Model Agent 默认无权任意 `pip install`；
- 缺依赖由 Environment Manager 处理；
- 每次新增运行依赖要有测试。

---

# 6. 仓库结构：代码应该放在哪里

必须以此为基线，允许细节调整，不允许把所有东西堆在一个 Python 文件。

```text
MM-Agent-Desktop/
│
├─ AGENTS.md
├─ README.md
├─ pyproject.toml
├─ uv.lock
├─ package.json / pnpm-workspace.yaml
├─ .gitignore
│
├─ apps/
│   └─ desktop/
│       ├─ src/                         # React UI
│       │   ├─ pages/
│       │   ├─ components/
│       │   ├─ features/
│       │   ├─ stores/
│       │   └─ api/
│       └─ src-tauri/                   # Tauri shell / bridge
│
├─ mmagent/
│   ├─ api/                             # Desktop 与 Python Core 的稳定 API
│   │   ├─ projects.py
│   │   ├─ runs.py
│   │   ├─ providers.py
│   │   └─ artifacts.py
│   │
│   ├─ agent/                           # 通用 Agent Runtime
│   │   ├─ loop.py
│   │   ├─ context.py
│   │   ├─ session.py
│   │   ├─ tool_protocol.py
│   │   ├─ budget.py
│   │   └─ errors.py
│   │
│   ├─ providers/
│   │   ├─ base.py
│   │   ├─ normalized.py
│   │   ├─ capabilities.py
│   │   ├─ openai_responses.py
│   │   ├─ openai_chat.py
│   │   ├─ anthropic_messages.py
│   │   ├─ gemini.py
│   │   └─ openai_compatible.py
│   │
│   ├─ runtime/
│   │   ├─ process.py                   # Windows 进程树/Job Object/超时
│   │   ├─ cancellation.py
│   │   ├─ environment.py
│   │   ├─ concurrency.py
│   │   └─ rate_limit.py
│   │
│   ├─ workspace/
│   │   ├─ root.py
│   │   ├─ path_policy.py
│   │   ├─ permissions.py
│   │   ├─ snapshot.py
│   │   └─ artifacts.py
│   │
│   ├─ tools/
│   │   ├─ registry.py
│   │   ├─ filesystem.py
│   │   ├─ python.py
│   │   ├─ matlab.py
│   │   ├─ latex.py
│   │   ├─ pdf.py
│   │   ├─ spreadsheet.py
│   │   ├─ document.py
│   │   ├─ image.py
│   │   └─ shell.py                     # 仅高级角色/受限使用
│   │
│   ├─ state/
│   │   ├─ db.py
│   │   ├─ models.py
│   │   ├─ repositories.py
│   │   ├─ events.py
│   │   ├─ checkpoints.py
│   │   └─ migrations/
│   │
│   ├─ orchestration/
│   │   ├─ engine.py
│   │   ├─ scheduler.py
│   │   ├─ dag.py
│   │   ├─ node.py
│   │   ├─ gate.py
│   │   ├─ retry.py
│   │   └─ resume.py
│   │
│   └─ mm/                              # 数模领域层：复现 Skill 的核心
│       ├─ config/
│       │   ├─ profiles.py
│       │   ├─ thresholds.py
│       │   └─ role_routing.py
│       │
│       ├─ contracts/                   # schema 唯一事实来源
│       │   ├─ problem_contract.py
│       │   ├─ data_archive.py
│       │   ├─ plan.py
│       │   ├─ assumptions.py
│       │   ├─ result_declaration.py
│       │   ├─ red_team.py
│       │   ├─ arbitration.py
│       │   ├─ experiment_record.py
│       │   ├─ change_manifest.py
│       │   ├─ review.py
│       │   └─ retrospective.py
│       │
│       ├─ roles/                       # 17 个角色，清洁重写
│       │   ├─ reader/
│       │   ├─ answer_predictor/
│       │   ├─ planner/
│       │   ├─ modeler/
│       │   ├─ red_team/
│       │   ├─ interpreter/
│       │   ├─ plotter/
│       │   ├─ figure_reviewer/
│       │   ├─ writer/
│       │   ├─ chapter_reviewer/
│       │   ├─ blind_reader/
│       │   ├─ integrator/
│       │   ├─ reviewer/
│       │   ├─ defect_hunter/
│       │   ├─ judge_simulator/
│       │   ├─ beautifier/
│       │   └─ retrospector/
│       │
│       ├─ pipeline/
│       │   ├─ s0_understand.py
│       │   ├─ s1_tournament.py
│       │   ├─ s2_model.py
│       │   ├─ s3_figures.py
│       │   ├─ s4_paper.py
│       │   ├─ s5_review.py
│       │   ├─ g5_publish.py
│       │   └─ s6_finalize.py
│       │
│       ├─ gates/
│       │   ├─ g0.py
│       │   ├─ g1.py
│       │   ├─ g2.py
│       │   ├─ g3.py
│       │   ├─ g4.py
│       │   └─ g5.py
│       │
│       ├─ guards/
│       │   ├─ change_guard.py
│       │   ├─ structure_guard.py
│       │   ├─ page_guard.py
│       │   └─ stale_value_guard.py
│       │
│       ├─ ledger/
│       │   ├─ issue_ledger.py
│       │   ├─ repair_receipt.py
│       │   ├─ verdict_merge.py
│       │   └─ fuse.py
│       │
│       └─ templates/
│           ├─ paper/
│           ├─ reports/
│           └─ project/
│
├─ tests/
│   ├─ unit/
│   ├─ integration/
│   ├─ contracts/
│   ├─ pipeline/
│   ├─ failure_injection/
│   ├─ provider_mocks/
│   └─ e2e/
│
├─ fixtures/
│   ├─ synthetic_problem/
│   └─ provider_responses/
│
├─ docs/
│   ├─ PROJECT_PLAN.md
│   ├─ ARCHITECTURE.md
│   ├─ CURRENT_STATE.md
│   ├─ spec/
│   │   ├─ SOURCE_SNAPSHOT.md
│   │   ├─ SOURCE_MAP.md
│   │   ├─ FIDELITY_MATRIX.md
│   │   └─ KNOWN_DEVIATIONS.md
│   ├─ decisions/
│   ├─ runs/
│   ├─ reviews/
│   ├─ learning/
│   ├─ releases/
│   ├─ security/
│   └─ user-guide/
│
└─ .reference/                         # gitignored
```

---

# 7. 一个实际项目运行后的工作区必须长这样

为了和原 Skill 的交付习惯保持接近，**项目产物目录保留原有中文逻辑名**：

```text
<ProjectRoot>/
│
├─ 输入/
│   ├─ 题目/
│   └─ 数据/
│
├─ 交接/
│   ├─ 题面契约.json
│   ├─ 数据档案.json
│   ├─ 需求追踪矩阵.json
│   ├─ 路线侦察.json
│   ├─ 计划.json
│   ├─ 假设台账_问题1.json
│   ├─ 结果声明_问题1.json
│   ├─ 红队_问题1.json
│   ├─ 仲裁_问题1.json
│   ├─ 实验记录.json
│   ├─ 换版清单_问题1.json
│   └─ ...
│
├─ 求解/
│   ├─ 问题1/
│   │   ├─ 求解_问题1.py
│   │   ├─ 复算.py
│   │   ├─ 结果/
│   │   └─ 图片/
│   ├─ 问题2/
│   └─ 成图.ps1 / 成图.py
│
├─ 红队结果/
│
├─ 论文/
│   ├─ 论文.tex
│   ├─ *.tex
│   ├─ figures/
│   └─ 论文.pdf
│
├─ 审稿/
│   ├─ 图评R*.json
│   ├─ 章评R*.json
│   ├─ 读者R*.json
│   ├─ 审稿意见_轮*.json
│   ├─ 硬伤_轮*.json
│   ├─ 评委模拟_轮*.json
│   ├─ 回执_*.json
│   └─ 复盘报告.json
│
├─ 台账/
│   ├─ 审稿台账.json
│   ├─ 章评台账.json
│   └─ 美化台账.json
│
├─ 日志/
│
├─ 快照/
│
├─ 交付/
│   ├─ 论文.pdf
│   ├─ 论文源码/
│   ├─ 求解源码/
│   ├─ 图/
│   ├─ 交付报告.md
│   └─ 复盘报告.json
│
└─ .mmagent/
    ├─ project.db                    # 真状态
    ├─ run.lock
    ├─ config_snapshot.json
    └─ checkpoints/
```

规则：

- SQLite 是运行真相；
- `交接/*.json` 是跨角色机器可读契约；
- `台账/*.json` 是给人看/导出的 carrier，内部权威状态在 SQLite；
- Agent 不能直接编辑 SQLite；
- 只能通过 Runtime/Repository 层变更状态。

---

# 8. 原 Skill → 新 Agent 的逐项映射

| MM-Final-Skill | 新实现 | 说明 |
|---|---|---|
| `流水线/蜂群驾驶.py` | `mmagent/mm/pipeline/*` + `orchestration/engine.py` | 拆分 S0–S6，不再单文件 |
| `流水线/本地蜂巢.py` | `agent/*` + `runtime/*` | 由 API Tool Loop 代替 CLI 子进程 Agent |
| `调度器.py` | `orchestration/scheduler.py` + SQLite | 状态/断点/依赖 |
| `回路.py` | `mm/ledger/*` + `mm/guards/*` | 台账、裁定、守卫、熔断 |
| `角色/*.md` | `mm/roles/<role>/prompt.md + role.yaml` | 17 个角色 clean-room 重写 |
| `role.sh` | `agent/session.py` | 统一 Agent 运行入口 |
| `图片腿.sh` | Agent vision input + `tools/image.py` | 协议支持视觉时直接传图片 |
| `codex公共.sh` | Provider Adapter | 不再依赖 Codex CLI |
| `claude公共.sh` | Provider Adapter | 不再依赖 Claude Code CLI |
| `状态.json` | SQLite `runs/stages/tasks` | 真状态 |
| `*.done` | task transaction | 成功必须由 Runtime 提交 |
| `*.pid` | runtime process registry | 只针对工具进程 |
| `契约表.py` | Pydantic contract registry | schema 单一事实来源 |
| `契约核对.py` | contract tests | 消费字段必须由生产 schema 声明 |
| `门检.py` | `mm/gates/*` | G0–G5 |
| `审计.py` | audit service | 结果/论文一致性审计 |
| `统稿守卫.py` | `structure_guard.py` / `change_guard.py` | 语言修订不可破坏事实 |
| `体检.sh` | environment diagnostics page/service | Windows 原生 |
| `启动.sh` | Run API + UI Start | 单运行锁 |
| `停跑.sh` | Cancel API | 取消 + 清进程树 |
| `状态.sh` | UI dashboard + Run API | |
| `看守.sh` | health monitor + event stream | |
| `切换.sh` | checkpoint-bound configuration migration | |
| `跑后指标.py` | run metrics / retrospective service | |

---

# 9. 17 个角色：必须全部复现

每个角色目录：

```text
mmagent/mm/roles/<role>/
  role.yaml
  prompt.md
  contracts.py        # 如该角色有角色专属辅助 schema
  tests/
```

`role.yaml` 至少：

```yaml
id: modeler
display_name: 建模师
default_reasoning: xhigh
allowed_tools:
  - fs.read
  - fs.write
  - python.write
  - python.run
  - matlab.run_script
read_scopes:
  - 输入/**
  - 交接/计划.json
  - 交接/数据档案.json
write_scopes:
  - 求解/问题{question}/**
  - 交接/建模笔记_问题{question}.md
  - 交接/假设台账_问题{question}.json
  - 交接/换版清单_问题{question}.json
```

17 角色固定如下。

## 9.1 读题官 Reader

阶段：S0。

主要读：

```text
输入/题目/**
输入/数据/**
```

主要产出：

```text
交接/题面契约.json
交接/数据档案.json
交接/读题体检.md
```

必须做：

- 题目问题数量识别
- 逐问输入/输出/约束
- 单位/时间/索引/边界条件
- 附件清单
- sheet / 列 / 类型 / 缺失 / 异常
- 题面明确禁止或要求
- 不能自己补题面没有的硬条件

默认 reasoning：`xhigh`。

---

## 9.2 答卷预测官 Answer Predictor

阶段：S0。

读：

```text
题面契约
```

输出：

```text
答卷预测
需求追踪矩阵
```

目标：提前预测高质量答卷需要证明/结果/图/验证什么，并让驱动形成需求追踪矩阵。

---

## 9.3 规划师 Planner

阶段：S1。

输出：

```text
交接/路线侦察.json
交接/计划.json
```

职责：

- 每问候选路线
- 方法适配
- 依赖关系
- 风险
- 最终路线
- 结果/验证/图的预期

不能直接替建模师写完整求解。

---

## 9.4 建模师 Modeler

阶段：

- S1 小样原型
- S2 正式建模
- G2 返工
- 升格变体
- S5 算路回炉

产物：

```text
交接/建模笔记_问题N.md
求解/问题N/求解_问题N.py
交接/假设台账_问题N.json
交接/实验记录.json
交接/换版清单_问题N.json
```

新 Runtime 中建模师可以使用 `python.run` / `matlab.run_script`，但**最终结果必须结构化落盘**。

重算后必须生成换版清单：

- 哪些指标变了
- 哪些图必须重画
- 哪些论文段必须同步
- 旧值有哪些，供 stale-value guard 搜索

---

## 9.5 红队 Red Team

这是复现质量的关键角色。

必须通过 Runtime 权限真正实现：

允许读：

```text
输入/**
交接/题面契约.json
交接/数据档案.json
交接/结果声明_问题N.json（需要比较时）
```

默认禁止读：

```text
求解/问题N/求解_问题N.py
交接/建模笔记_问题N.md
交接/结果解读_问题N.md
```

红队自己生成：

```text
求解/问题N/复算.py
红队结果/**
交接/红队_问题N.json
```

报告至少包括：

```text
复算方式
复算指标
口径说明
口径对照
结论
分歧明细
```

不能只在 Prompt 里说“不要看建模代码”；权限层必须拒绝读取。

---

## 9.6 解读师 Interpreter

负责：

- 解读结果
- 建模/红队口径对齐
- 仲裁
- 锦标赛裁决
- 升格裁决
- 返工单

产物：

```text
交接/结果解读_问题N.md
交接/结果声明_问题N.json
交接/仲裁_问题N.json
```

结果声明是后续图/文的重要 Frozen Truth carrier。

---

## 9.7 绘图师 Plotter

阶段：

- S3
- S5 图路
- G5 图路
- S5b 美化图路

产物：

```text
求解/问题N/绘图_*.py
求解/问题N/图片/*.png
```

要求：

- 图必须由真实结果生成；
- 数据变化时按换版清单重画；
- 图代码可复现；
- 不允许手工伪造数据图。

---

## 9.8 图评师 Figure Reviewer

阶段：S3。

读：

```text
图片
结果声明
```

写：

```text
审稿/图评R{n}.json
```

重点：

- 图是否支持结论
- 可读性
- 单位
- 图例
- 轴
- 误导
- 信息量
- 与结果是否一致

---

## 9.9 撰稿师 Writer

阶段：

- S4 叙事底稿
- 正文
- 章修订
- 摘要变体
- S5 文路
- G5 文路
- S6 整改

只能写论文和明确授权的文档；不能擅自改算出来的事实。

产物：

```text
论文/*.tex
审稿/回执_*.json
```

必须遵守：

- 事实源引用
- 最小修订
- 数字同步
- 不虚构文献
- 不把 unresolved 科学问题写成已解决

---

## 9.10 章评师 Chapter Reviewer

阶段：S4。

按章/批评审，输出：

```text
审稿/章评R{n}_{k}.json
```

每章问题应限量、有严重度、明确定位和修改指令。

---

## 9.11 读者 Blind Reader

阶段：

- S4 闭卷读者
- 摘要复述门

闭卷意味着不给全部工程上下文，让其从论文自身判断：

- 能否理解
- 哪里卡住
- 自造词
- 摘要是否能复述核心方法/结果

---

## 9.12 统稿师 Integrator

阶段：S4。

职责仅限：

- 语言一致
- 术语一致
- 章节衔接
- 重复消除

不能：

- 改核心数值
- 改模型
- 改算法事实

必须经过统稿守卫。

---

## 9.13 审稿员 Reviewer

S5 每轮至少 A/B 两路独立评审。

输出：

```text
审稿/审稿意见_轮NA.json
审稿/审稿意见_轮NB.json
```

意见必须结构化：

```text
id
级别
目标: 算|图|文
定位
问题
指令
验收
对应
```

---

## 9.14 硬伤猎手 Defect Hunter

专查：

- 数值不一致
- 旧值残留
- 题面漏答
- 单位/索引错误
- 图文错配
- 自相矛盾
- 结果声明与论文冲突
- 编译/页图硬伤

必须查看换版清单。

---

## 9.15 评委模拟 Judge Simulator

主要看最终 PDF 页图，而不是工程源码。

模拟第一印象：

- 能否快速复述问题/方法/结果/验证
- 卡点
- 视觉与答卷印象
- 相对上一版是更好/持平/更差

不能对没看到的内容假装核实。

---

## 9.16 美化师 Beautifier

S5b / S6。

只针对页面呈现：

- 图
- 文
- 空白
- 浮动体
- 表格
- 层次
- 可读性

意见必须带：

```text
目标: 图|文
页
严重度
问题
修改指令
```

---

## 9.17 复盘官 Retrospector

最后阶段。

输出：

```text
审稿/复盘报告.json
```

必须量化：

- 红队↔仲裁次数
- 门 FAIL
- 返工
- 升格
- 降级
- 守卫回退
- 熔断
- tool failure
- provider failure
- 编译失败
- 总用时
- token/API usage（可得时）
- 瓶颈
- 下次规则库建议

---

# 10. 角色默认 reasoning 档位复现

默认配置：

```text
xhigh:
  读题官
  规划师
  建模师
  红队
  解读师
  答卷预测官

high:
  撰稿师
  审稿员
  硬伤猎手
  章评师
  统稿师
  绘图师

medium:
  图评师
  美化师
  评委模拟
  读者
  复盘官
```

Provider 不支持 reasoning level 时必须：

- 能力声明为 unsupported；
- 不伪造；
- 按普通请求执行；
- 日志记录该差异。

---

# 11. Pipeline 必须按以下语义实现

## S0 吃透题目

节点：

```text
S0.0 WorkspaceSeed
S0.1 InputInventory
S0.2 ProblemContract
S0.3 AnswerPrediction
S0.4 RequirementMatrix
G0
```

G0 最低检查：

- 有题面契约
- 问数可确定
- 每问需求可追踪
- 数据附件有档案
- 关键字段合法
- 无 schema violation

失败：回 S0，不进入 S1。

---

## S1 战略锦标赛

节点：

```text
S1.0 Reconnaissance
S1.1 RouteGeneration
S1.2 PrototypeRun
S1.3 RouteJudgement
S1.4 PlanFinalize
G1
```

深度/标准：

- 每问默认 3 路线。

快速：

- 只挑最复杂问；
- 2 路线；
- 目的为链路冒烟，不是交付高质量论文。

原型必须真的运行小样，不允许只写“预计有效”。

---

## S2 建模求解 + 红队

首先构造问题依赖 DAG。

每问：

```text
Modeler
  ↓
Execute solution
  ↓
Result declaration
  ↓
Red Team independent recomputation
  ↓
Execute red-team solver
  ↓
Compare
  ↓
if mismatch → Interpreter arbitration
  ↓
Interpreter result interpretation
  ↓
G2(question)
```

红队容差默认：

```text
relative tolerance = 0.01
```

但不能对所有指标机械使用同一数值比较；口径类差异先由 Interpreter 分类。

### G2

每问独立 Gate。

失败：

```text
普通返工 ≤ 2
    ↓
仍失败
    ↓
升格蜂群：3 个替代变体
    ↓
裁决
    ↓
解读
    ↓
仍失败
    ↓
降级放行 + 明确记录 unresolved issue
```

降级不是 PASS；UI/交付报告必须显示“带已知阻塞交付”。

禁止为了过门捏造数据。

---

## S3 图证

```text
Plotter
  ↓
run plot scripts
  ↓
Figure Reviewer
  ↓
revision if needed
  ↓
最多 N 轮
  ↓
G3
```

默认：

```text
图评轮数 = 2
图评阈值 = 7.0
```

G3 必须检查：

- 关键结果有图证
- 图存在
- 图由脚本生成
- 图引用的数据版本匹配
- 图评达到条件或有记录的降级理由

---

## S4 撰稿

节点顺序：

```text
Narrative Draft
  ↓
Argument Spine / Main Control
  ↓
Section Writing
  ↓
Chapter Review + Blind Reader
  ↓
Targeted Revision
  ↓
Change/Structure Guard
  ↓
Integrator
  ↓
Summary Swarm
  ↓
Summary Paraphrase Gate
  ↓
G4
```

### 章评

默认：

```text
2 轮
阈值 7.0
```

修订只能改点名位置及必要邻接内容。

### 摘要蜂群

深度：

```text
5 variants
```

标准/快速：

```text
3 variants
```

选摘要不能只按“文采”，必须能被 Blind Reader 复述：

- 问题
- 方法
- 关键结果
- 验证/结论

### G4

检查：

- 论文结构
- 事实溯源
- 术语一致
- 结果/图/文版本一致
- 未决问题没有被掩盖
- LaTeX 结构可编译

---

# 12. S5 审稿场：必须完整复现其“多路评审 → 台账 → 定向回炉”

每轮固定：

```text
1. compile paper
2. render PDF pages
3. audit
4. mechanical gate check
5. Reviewer A
6. Reviewer B
7. Defect Hunter
8. Judge Simulator
9. merge findings
10. merge into issue ledger
11. verdict on previous repair receipts
12. convergence check
13. fuse/escalation check
14. route issues by target
15. rework in order: 算 → 图 → 文
16. run guards
17. compile/fix
18. write round checkpoint
```

最后一轮默认：

```text
只评，不继续大规模修改
```

以 G5 做最终兜底。

默认审稿轮：

```text
深度 = 4
标准 = 3
快速 = 2
```

默认审稿达标：

```text
8.6
```

平台期：

```text
0.15
```

---

# 13. Issue Ledger 必须是真正状态机

状态至少：

```text
待改
待复核
已消解
未消解
搁置
```

Issue 字段：

```text
id
source
round
severity
target: 算|图|文
location
problem
instruction
acceptance
status
attempt_count
related_question
history[]
receipts[]
```

规则：

- 同一问题后续评审必须用 `对应` / identity merge，不应每轮换个措辞就生成新 issue；
- 修改腿写 repair receipt；
- Reviewer 根据**实际成品**裁定，不以回执自证；
- 待复核但评审漏裁不能默认 PASS；
- 两次修不掉进入 fuse。

---

# 14. 三大 Guard 必须实现

## 14.1 Change Guard

默认：

```text
普通上限 0.45
升格上限 0.70
```

不能只用简单 line diff。

至少结合：

- 正文句子级变化
- 被评审点名位置掩码
- 字符保留比例
- 非点名句变化率

目标：允许真正的定向修复，但阻止“借修一个问题把整章重写”。

---

## 14.2 Structure Guard

检查至少：

- 主控 `\input` 集合不可无故减少
- 章节不可变空
- 附录源码清单不可无故消失
- 核心结构文件必须存在
- 问题章节数量与题面问题数匹配

---

## 14.3 Page Guard

S5b 美化后记录 baseline pages。

G5 返工后若：

```text
new_pages > baseline + max(10%, 2 pages)
```

则触发回退/检查。

也记录骤降告警，避免丢章。

---

# 15. stale-value / 换版一致性

复现原 Skill “先算后图后文”。

任何重新计算改变核心结果：

```text
计算版本 +1
    ↓
生成换版清单
    ↓
受影响图失效
    ↓
受影响文失效
    ↓
先图
    ↓
后文
    ↓
Defect Hunter grep/semantic check 旧值
```

Artifact 表必须带：

```text
version
producer_task
input_versions
hash
created_at
```

论文/图引用旧计算版本时，G4/G5 必须能检测。

---

# 16. 熔断

默认：

```text
attempt_count >= 2
```

进入 fuse candidate。

策略：

- 正确性 / 硬伤：升格一次，换路线/换上下文重做；
- 叙述 / 版式：可搁置，必须留痕；
- 搁置阻塞不代表问题消失，只代表 pipeline 允许继续；交付报告必须列出。

禁止无限回流。

---

# 17. S5a / S5b / G5 / S6

## S5a 摘要定稿

摘要再次做闭卷复述门。

---

## S5b 美化

按 PDF 页图审查。

图问题：

```text
Plotter → regenerate figures
```

文问题：

```text
Writer → typography/layout fix
```

每轮：

```text
修改 → compile → page guard
```

默认：

```text
深度/标准 = 2 轮
快速 = 1 轮
美观阈值 = 8.5
```

---

## G5 出版门

严格顺序：

```text
final compile
  ↓
render ledger view
  ↓
audit
  ↓
gate
```

阻塞级返工：

```text
图问题：
Plotter → rerun figure → Writer sync text
                                  ↓
文问题：Writer -------------------┘
                                  ↓
compile BEFORE re-review
                                  ↓
page guard
                                  ↓
Defect Hunter verification
```

算类阻塞默认不能在出版门偷偷改核心计算。

若要支持 G5 算路，必须 ADR，并实现“重算 → 红队 → G2 → 图 → 文”完整级联，不能只改数字。

---

## S6 出版复盘

```text
逐页终审
  ↓
终审整改
  ↓
final compile
  ↓
publication harvest
  ↓
retrospective
```

最终输出：

- final PDF
- LaTeX
- solver scripts
- plotting scripts
- figures
- machine-readable results
- review ledger
- known unresolved items
- run metrics
- retrospective

---

# 18. 三个档位必须复现

| 配置 | 深度 | 标准 | 快速 |
|---|---:|---:|---:|
| 全问锦标赛 | 是 | 是 | 否，只最难问 |
| 每问路线 | 3 | 3 | 2 |
| 摘要变体 | 5 | 3 | 3 |
| 图评轮 | 2 | 2 | 2 |
| 章评轮 | 2 | 2 | 2 |
| 审稿轮 | 4 | 3 | 2 |
| 美化轮 | 2 | 2 | 1 |
| reasoning | 全局高档 | 角色分档 | 可配置 |
| 门/阈值/守卫 | 同 | 同 | 同 |

默认并发：

```text
4
```

429 / provider rate limit 时 Runtime 自动降低并发，但：

- 不低于安全下限；
- 写 event；
- 后续可逐步恢复；
- 不可把 rate-limit 当模型任务失败。

---

# 19. Agent Runtime：最低闭环

必须实现真正 tool loop：

```text
user/task
  ↓
assemble system + role + task context
  ↓
provider.generate()
  ↓
tool_call?
  ├─ no → validate final response / expected artifacts
  └─ yes
      ↓
permission check
      ↓
tool execute
      ↓
persist tool_call + result
      ↓
feed result back
      ↓
next model turn
```

每次 Agent Invocation 必须有：

```text
invocation_id
task_id
role_id
provider_profile
model
reasoning
context_manifest
started_at
ended_at
status
usage
```

不能让模型的自然语言“我完成了”直接等于任务成功。

成功条件是：

```text
expected artifacts exist
AND schemas validate
AND required tool executions succeeded
AND node-specific verifier passes
```

---

# 20. Context Manager

Agent 不应把整个项目无限塞入上下文。

必须有：

```text
context manifest
artifact summaries
targeted reads
tool output truncation
rolling conversation
stage handoff documents
```

原则：

```text
search → targeted read → reason → tool → persist
```

关键跨阶段信息进入：

```text
交接/
```

而不是依赖聊天记忆。

---

# 21. Capability / Workspace 权限

Default deny。

每个 role 明确：

```text
read scopes
write scopes
allowed tools
network permission
shell permission
```

路径检查：

- canonicalize
- reject `..`
- reject absolute path outside project
- detect Windows junction / reparse escape
- temp directory由 Runtime 提供
- shell cwd 固定 workspace

### 红队硬隔离

测试必须证明：

```text
red_team read 求解/问题1/求解_问题1.py
→ PermissionDenied
```

而不仅是 prompt 约束。

---

# 22. Windows 进程生命周期

任何 Python/MATLAB/LaTeX/Shell tool 进程必须可取消。

Runtime 要实现：

- process registry
- process tree ownership
- timeout
- cancellation
- hard kill fallback
- orphan detection

优先研究 Windows Job Objects；如果用 `psutil`/`pywin32`，记录依赖。

测试：

- 父进程起子进程
- cancel 父
- 子进程必须一起退出
- 不允许旧任务在 retry 后继续写同一产物

这复现原 Skill 对“双写/孤儿腿”的防护意图。

---

# 23. Contract Layer：schema 只有一个事实来源

原 Skill 的“契约表不复制 schema”思想必须保留。

Pydantic model 是唯一 schema authority。

消费者：

```text
Gate
Audit
Pipeline
Review merge
UI
```

只能 import 这些 model，不得自己复制字段定义。

建立 contract test：

```text
所有消费者访问字段 ⊆ producer schema 声明字段
```

任何 schema 修改：

```text
contract tests
migration tests
pipeline tests
```

必须通过。

---

# 24. Provider 配置 UX

设置页：

```text
Provider Name
Protocol
Base URL
API Key
Model
Reasoning
Timeout
Max output
```

按钮：

```text
Test Connection
```

高级：

```text
role routing
```

例如：

```text
Modeler → Provider A / model X
Red Team → Provider B / model Y
Writer → Provider A / model Z
```

默认可以全角色使用同一个用户配置模型。

不能要求用户安装 Codex CLI 或 Claude Code CLI。

---

# 25. UI 页面固定范围

## 首页

- 新建项目
- 最近项目
- 设置

## New Project

- 项目名
- 赛题 PDF
- 附件
- 比赛模板（可先 Generic）
- 档位
- Provider profile
- 开始

## Run Dashboard

左侧：

```text
S0
G0
S1
G1
S2
  Q1
  Q2
...
S3
S4
S5 R1/R2/...
G5
S6
```

中间：

- 当前节点
- 当前 Agent
- 当前 tool
- running/queued/failed
- elapsed

右侧：

- events/logs
- issue ledger
- artifacts

底部：

```text
Pause
Resume
Cancel
Retry Failed
Open Workspace
Open PDF
```

## Provider Settings

添加/编辑/测试。

## Artifact Viewer

分类显示：

- results
- figures
- paper
- reviews
- ledgers
- logs

---

# 26. 长任务自身的持久化开发纪律

开发 Agent 自己也必须可恢复。

仓库一直维护：

```text
AGENTS.md
docs/PROJECT_PLAN.md
docs/ARCHITECTURE.md
docs/CURRENT_STATE.md
docs/runs/RUN_LOG.md
docs/runs/vX.Y.0.md
docs/learning/vX.Y.0.md
docs/reviews/vX.Y.0-review-packet.md
docs/reviews/vX.Y.0-external-review.md
docs/releases/vX.Y.0.md
docs/decisions/ADR-*.md
```

`RUN_LOG.md` append-only。

上下文丢失/压缩/重启：

```text
1. read AGENTS.md
2. read docs/CURRENT_STATE.md
3. read docs/PROJECT_PLAN.md
4. read latest docs/runs/*
5. git status
6. inspect only files relevant to current TODO
7. continue
```

禁止“忘了以后重新从零设计”。

---

# 27. 什么时候问 GPT-5.6 Sol High

GLM-5.3-Flash 是实施者。

以下情况先自行：

```text
查代码
查文档
做最小实验
```

仍不确定再通过 ZCode 内置浏览器询问 GPT-5.6 Sol High：

- Agent loop 架构选择
- Provider protocol 语义
- tool-call normalization
- Windows process isolation/cancellation
- reparse/junction workspace escape
- SQLite transaction/recovery
- DAG cancellation race
- retry 双写
- issue merge
- guard 算法
- schema ownership
- secret storage
- Tauri ↔ Python backend 生命周期
- 任何可能导致之后多个版本返工的架构选择

咨询时不得只问：

> “哪个好？”

必须给：

```text
Context
Current design
Option A
Option B
Evidence
Constraints
Specific question
```

GPT 建议必须存入 ADR 或 run log 后再实现。

---

# 28. 每版本外审协议

每个版本完成后生成 self-contained：

```text
docs/reviews/vX.Y.0-review-packet.md
```

至少包含：

1. version goal
2. commit
3. changed files
4. architecture
5. public interfaces
6. state transitions
7. security boundary
8. tests
9. failure injection
10. known limitations
11. claimed invariants
12. focused questions
13. relevant source excerpts

然后通过内置浏览器发给 GPT-5.6 Sol High：

要求：

```text
Act as a security-minded OSS maintainer.
Classify findings:
P0 critical release blocker
P1 significant release blocker
P2 non-blocking
Check correctness, security, races, state integrity,
permission enforcement, provider honesty, failure recovery,
tests, maintainability, and whether claimed invariants are actually enforced.
```

保存完整结果：

```text
docs/reviews/vX.Y.0-external-review.md
```

P0/P1 全修后才能 tag。

若修复造成大改，再做 focused re-review。

禁止伪造外审。

---

# 29. 版本路线：每版具体做什么

## v0.1.0 — Specification + Agent Kernel

### 必做

- repo skeleton
- `.reference` 只读区
- source snapshot
- source map
- fidelity matrix
- SQLite schema v1
- event store
- normalized provider interface
- mock provider
- tool registry
- filesystem tool
- Python tool
- minimal agent loop
- artifact validation
- typed errors
- cancellation token 基础
- project workspace creation

### 验收

Mock Agent 能：

```text
write Python
→ run
→ see traceback
→ modify
→ rerun
→ create validated result artifact
```

并有完整事件记录。

### 不做

MM 具体 S0–S6 逻辑先不大规模实现。

---

## v0.2.0 — Windows Workspace / Process / Permission

### 必做

- path policy
- Windows path canonicalization
- junction/reparse escape defense
- role capability
- process registry
- timeout
- cancel
- process tree cleanup
- retry no-double-write
- environment diagnostics
- managed Python bootstrap
- detect XeLaTeX root
- detect MATLAB root

### Failure injection

- `..\` escape
- absolute escape
- junction escape
- hung process
- parent+child cancel
- timeout
- retry while old process alive
- concurrent writes

---

## v0.3.0 — Real Provider Layer

实现：

- OpenAI Responses
- OpenAI Chat
- Anthropic Messages
- Gemini
- OpenAI-Compatible

### 必做

- mock contract tests for all
- capabilities
- tool normalization
- streaming
- usage
- rate-limit
- retry hints
- secret redaction
- connection test API
- model profiles
- role routing

真实 API 未提供时：

```text
offline contract-tested
```

不能写：

```text
real-provider verified
```

---

## v0.4.0 — S0 + G0 + S1 + G1

实现完整：

- input import
- PDF parse/render fallback
- XLSX/CSV/DOCX inventory
- Reader
- Answer Predictor
- Planner
- prototype routes
- actual prototype execution
- route judgement
- plan
- G0/G1
- 深度/标准/快速差异

建立第一版项目 Run Dashboard API。

---

## v0.5.0 — S2 + G2 + Red Team + DAG

重点版本。

实现：

- question DAG
- Modeler
- real code execution
- Result Declaration
- Red Team hard isolation
- independent recomputation
- compare
- Interpreter
- arbitration
- G2
- ≤2 ordinary rework
- escalation swarm 3 variants
- downgrade release with known blockers
- change manifest
- stale artifact versioning

必须有 failure-injection。

---

## v0.6.0 — S3 + S4 + G3/G4 + Scientific Toolchain

实现：

- Plotter
- Figure Reviewer
- figure loop
- MATLAB tool full support
- XeLaTeX compile
- PDF page rendering
- Writer
- Chapter Reviewer
- Blind Reader
- Integrator
- summary swarm
- paraphrase gate
- change guard
- structure guard
- G3/G4

---

## v0.7.0 — S5 Review Arena + Ledgers + Guards

实现：

- compile per round
- audit
- Reviewer A/B
- Defect Hunter
- Judge Simulator
- merge
- issue identity
- receipt
- verdict
- convergence
- fuse
- route by 算/图/文
- rework cascade
- checkpoint each round
- last-round semantics
- page guard
- best snapshot / rollback

这是第二个重点版本。

---

## v0.8.0 — S5a/S5b + G5 + S6 + Delivery

实现：

- summary final
- Beautifier
- layout loop
- G5
- figure rework route
- compile-before-verification
- page guard
- final Defect Hunter verify
- page-by-page final review
- final correction
- harvest
- Retrospector
- run metrics
- final delivery report

至此后端能力应基本对齐 Skill。

---

## v0.9.0 — Desktop Product + Windows Packaging + Fidelity Run

实现完整 Tauri UI。

必须：

- project creation
- import
- provider settings
- run controls
- visual pipeline
- live events
- issue ledger
- artifact viewer
- PDF preview
- pause/resume
- crash reopen
- Windows installer

### Fidelity Matrix

逐条检查原 Skill：

```text
17 roles
S0-S6
G0-G5
three profiles
red team
arbitration
escalation
downgrade
figure review
chapter review
blind reader
summary swarm
review arena
issue ledger
guards
fuse
G5
retrospective
resume
metrics
```

每一项：

```text
MATCH
PARTIAL
DEVIATION
NOT IMPLEMENTED
```

不能靠印象。

---

## v1.0.0 — Hardening / Real End-to-End / Final Review

### 必做

- 完整 synthetic modeling problem
- 完整快速档 E2E
- 完整标准档 E2E（资源允许）
- crash recovery
- pause/resume
- provider failure
- rate-limit
- corrupted artifact
- malformed model output
- compile failure
- MATLAB absent degradation
- XeLaTeX absent diagnostics
- stale-value test
- red-team isolation test
- issue fuse test
- page guard test
- packaging install/uninstall
- final docs
- security docs
- provider guide
- user guide
- developer guide

### Final GPT Sol High Review

完整 v1.0 review packet。

只有：

```text
0 unresolved P0
0 unresolved P1
all release gates pass
```

才打：

```text
v1.0.0
```

---

# 30. 每个版本统一循环

严格：

```text
PLAN
↓
IMPLEMENT
↓
UNIT TEST
↓
INTEGRATION TEST
↓
FAILURE INJECTION
↓
SELF REVIEW
↓
UPDATE FIDELITY MATRIX
↓
UPDATE DOCS
↓
GENERATE REVIEW PACKET
↓
GPT-5.6 SOL HIGH EXTERNAL REVIEW
↓
TRIAGE
↓
FIX P0/P1
↓
REGRESSION TEST
↓
FINAL VERIFY
↓
COMMIT
↓
TAG
↓
UPDATE CURRENT_STATE
↓
NEXT VERSION
```

不需要用户输入“继续”。

---

# 31. 测试不是附属品

## Unit

- schema
- state transitions
- guard algorithms
- provider normalization
- path policy
- issue merge

## Integration

- agent→tool→agent
- provider→tool call
- Python execution
- MATLAB
- XeLaTeX
- PDF
- spreadsheet
- SQLite resume

## Pipeline

- G0 fail
- G1 fail
- G2 mismatch
- arbitration
- G2 escalation
- downgrade
- S3 replot
- S4 guard rollback
- S5 issue repair
- fuse
- G5 page guard

## Failure Injection

刻意注入：

- bad JSON
- missing artifact
- provider 429
- provider 500
- stream interruption
- tool timeout
- child process survives
- corrupt SQLite transaction attempt
- task cancelled while tool returns
- duplicate completion
- stale result
- old figure
- old number left in tex

## E2E

用仓库自带**合成题**，避免依赖版权赛题。

---

# 32. Honest Claims

必须区分：

```text
implemented
unit-tested
mock-provider-tested
integration-tested
E2E-tested
real-provider-tested
not-tested
```

禁止：

- fabricated benchmark
- fabricated provider verification
- fabricated “整炉通过”
- 模型自然语言声称成功就写 PASS

---

# 33. 质量阈值默认值

为了高保真，初始复制行为值：

```text
red_team_relative_tolerance = 0.01

figure_review_rounds = 2
figure_review_threshold = 7.0

chapter_review_rounds = 2
chapter_review_threshold = 7.0

review_score_target = 8.6
review_plateau = 0.15

beauty_threshold = 8.5

change_guard = 0.45
change_guard_escalated = 0.70

default_concurrency = 4
```

这些值放：

```text
mmagent/mm/config/thresholds.py
```

UI 可查看；v1 前不要随意允许用户乱改核心质量门。

---

# 34. Runtime 成功/失败原则

### LLM 输出不可信

所有：

- JSON
- path
- tool args
- status
- scores

都要 schema / policy 校验。

### declared != enforced

例如：

> “红队不会读模型代码”

若权限系统没拦，就是**未实现**。

> “API key 不会进日志”

必须有自动 redaction test。

---

# 35. Pause / Resume

Pause：

- 不启动新 Task；
- 正在执行的安全工具允许到边界或按策略取消；
- flush SQLite；
- 写 checkpoint。

Resume：

- 验证项目 root
- 验证 config snapshot
- 恢复 READY/PENDING
- RUNNING 残留任务根据 checkpoint 规则标 FAILED/RETRYABLE
- 绝不直接假定它们成功

S5 必须至少支持**轮级 checkpoint**。

---

# 36. 单运行锁

同一项目同时只允许一个 active driver/run owner。

SQLite + lock file 双层保护。

第二个实例：

```text
拒绝接管
```

除非明确执行 crash recovery 并确认旧 owner 不存在。

复现原 Skill “一个父目录只起一个驱动”的铁律。

---

# 37. 开发 Agent 的 Stop Conditions

GLM-5.3-Flash 只有以下情况可停：

1. 有数据破坏风险且无法安全规避；
2. 需要用户未提供的账号授权 / 付费 / secret；
3. 需求出现根本矛盾；
4. 必须推翻 Architecture Freeze 且会改变产品性质；
5. ZCode / GLM 无法继续；
6. Git 存在无法安全恢复的数据丢失；
7. GPT Reviewer 给出 P0，实施者无法安全修复。

普通：

- package 选择
- API 差异
- test failure
- UI 细节
- refactor
- lint
- type errors
- provider mock 问题

都不能停。

必须自己解决，必要时问 GPT Sol High。

停前写：

```text
docs/STOP_REPORT.md
```

---

# 38. 启动后的前 20 项动作——不得跳

GLM 收到启动指令后立刻：

1. `pwd` / 检查目录。
2. `git status`。
3. 若不是 repo，`git init`。
4. 创建 `.gitignore`。
5. 把 `.reference/` 放进 `.gitignore`。
6. clone MM-Final-Skill 到 `.reference/MM-Final-Skill`。
7. clone Mrite 到 `.reference/Mrite`。
8. 记录两个 HEAD SHA。
9. 读 MM `README.md`。
10. 读 MM `.claude/skills/paper-foundry/SKILL.md`。
11. 读 MM `references/流程与档位.md`。
12. 读 MM `references/角色与契约.md`。
13. 读 MM `references/铁律.md`。
14. 读 MM `流水线/蜂群驾驶.py` 的架构部分。
15. 读 MM `流水线/本地蜂巢.py`。
16. 读 `调度器.py`、`回路.py`。
17. 列出 17 个当前角色文件并记录，不需要一次把全文塞上下文。
18. 建 `SOURCE_SNAPSHOT / SOURCE_MAP / FIDELITY_MATRIX`。
19. 建项目骨架和持久化文档。
20. baseline commit，然后进入 v0.1.0。

---

# 39. 每次继续开发前的恢复序列

```text
read AGENTS.md
read docs/CURRENT_STATE.md
read docs/PROJECT_PLAN.md
read docs/spec/FIDELITY_MATRIX.md
read latest docs/runs/v*.md
git status
```

然后只读取当前版本涉及模块。

---

# 40. v1.0 最终验收矩阵

必须全部满足：

## Product

- [ ] Windows 启动
- [ ] 新建项目
- [ ] 导入题目/数据
- [ ] 自配 API
- [ ] connection test
- [ ] 选择档位
- [ ] Start
- [ ] Pause
- [ ] Resume
- [ ] Cancel
- [ ] Crash reopen
- [ ] Artifact viewer
- [ ] PDF
- [ ] export

## Runtime

- [ ] Provider-agnostic
- [ ] Tool loop
- [ ] permission
- [ ] workspace boundary
- [ ] timeout
- [ ] cancellation
- [ ] orphan cleanup
- [ ] retries
- [ ] SQLite recovery
- [ ] checkpoint

## Skill Fidelity

- [ ] 17 roles
- [ ] S0
- [ ] G0
- [ ] S1 tournament
- [ ] G1
- [ ] S2 DAG
- [ ] Red Team
- [ ] arbitration
- [ ] G2/rework/escalation/downgrade
- [ ] S3 figure loop
- [ ] G3
- [ ] S4 narrative/chapter/blind/integrator/summary
- [ ] G4
- [ ] S5 multi-review
- [ ] ledger
- [ ] receipts
- [ ] convergence
- [ ] fuse
- [ ] calc→fig→text rework
- [ ] S5a
- [ ] S5b
- [ ] G5
- [ ] S6
- [ ] retrospective
- [ ] three guards
- [ ] stale-value / change manifest
- [ ] profiles
- [ ] resume

## Scientific tools

- [ ] managed Python
- [ ] `D:\Apps\texlive` discovery
- [ ] XeLaTeX
- [ ] PDF render
- [ ] `D:\Apps\Matlab` discovery
- [ ] MATLAB batch
- [ ] spreadsheet
- [ ] DOCX
- [ ] image input

## Quality

- [ ] all tests
- [ ] failure injection
- [ ] E2E synthetic run
- [ ] no unresolved P0
- [ ] no unresolved P1
- [ ] final fidelity matrix
- [ ] known deviations honest
- [ ] final report
- [ ] tag v1.0.0

---

# 41. 最终定义

这个项目成功的标准不是：

> “有一个聊天窗口，模型能写论文。”

也不是：

> “把 MM-Final-Skill 包了一层 GUI。”

而是：

> **把 MM-Final-Skill 已经验证过的多角色论文铸造厂工作流，重新实现为独立、Provider-Agnostic、Windows-first、可暂停恢复、可审计、有真实权限边界的桌面 Agent。**

到 v1.0.0 时，用户不需要 Codex CLI 或 Claude Code CLI，只需要：

```text
安装客户端
→ 配 API
→ 放题目和附件
→ 点击开始
→ 等待流水线自行跑完
```

而内部仍保留 MM-Final-Skill 的核心质量机制：

```text
战略锦标赛
红队独立复算
口径仲裁
结果声明
图证
章评
闭卷读者
统稿
摘要蜂群
多路审稿
Issue Ledger
换版清单
变化/结构/页数守卫
熔断
定向回炉
出版门
逐页终审
复盘
```

**只有做到这一点，才能称为“MM-Final-Skill 客户端化复现”。**
