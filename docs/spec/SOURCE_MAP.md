# SOURCE_MAP — 原 Skill 行为 → 新实现位置映射

> 记录"观察到的上游行为/组件 → 本仓库哪个模块复现"。不复制源码，只登记行为归属。
> 每个版本实施时更新本表；fidelity 检查以本表为索引。

## 1. 驱动与编排

| 原 Skill 组件/行为 | 本仓库实现 | 状态 |
|---|---|---|
| `流水线/蜂群驾驶.py` 主流程（S0–S6 编排、31 节点） | `mmagent/mm/pipeline/s0..s6*.py` + `mmagent/orchestration/engine.py` | 计划 v0.4–v0.8 |
| `调度器.状态机`（状态.json：已完成节点/问题门/门失败计数/级联/降级放行） | SQLite `stages/tasks/issues/checkpoints` + `mmagent/state/`（JSON 导出仅为可读 carrier） | v0.1.0 起（schema） |
| `调度器.构建依赖图/拓扑分层/全部下游`（问题 DAG） | `mmagent/orchestration/dag.py` | 计划 v0.5 |
| `调度器.门`（检查→返工≤2→升格→降级放行） | `mmagent/orchestration/gate.py` | 计划 v0.4（框架）/ v0.5（G2） |
| `调度器.合并修订单`（级别 硬伤>正确性>叙述>版式；目标 算>图>文） | `mmagent/mm/ledger/order_merge.py` | 计划 v0.7 |
| `wave()`（异步腿 + done 轮询 + kill -0 判死 + 并发闸 4→2 + 429 降并发 + 重试一次 + 腿上限<波次超时防双写） | `mmagent/agent/session.py` + `mmagent/runtime/concurrency.py` + `runtime/process.py` | 计划 v0.2（进程）/ v0.3+（agent 层） |
| `本地蜂巢.LocalHive`（工作根 + env 口径 + setsid 进程组） | `mmagent/workspace/root.py` + `mmagent/runtime/process.py`（Windows Job Object 替代 setsid） | 计划 v0.2 |
| `get_json()`（JSON 校验失败带反馈派修复腿重写一次） | `mmagent/agent/loop.py` 的 artifact 修复回路 | 计划 v0.5 |
| `run_script()`（脚本失败派修复腿再跑一次） | `mmagent/tools/python.py` + `mmagent/orchestration/retry.py` | 计划 v0.5 |
| 预算护栏（MAX_LEGS / MAX_HOURS，S2 逐问检查） | `mmagent/agent/budget.py` | 计划 v0.5 |
| `节点()`（节点级断点：已完成节点跳过） | SQLite tasks + `orchestration/resume.py` | v0.1.0 起 |
| S5 轮级断点（`S5已完成轮`） | `orchestration/checkpoints.py`（round checkpoint） | 计划 v0.7 |
| `启动.sh` 双驱动拒绝 / `停跑.sh` 停净 / `看守.sh` / `状态.sh` | Run API 单运行锁（SQLite + run.lock）+ UI Dashboard | 计划 v0.9 |
| `切换.sh`（边界钩子切换） | checkpoint-bound config migration（v1.0 前暂以"停→改→续"语义覆盖，见 KNOWN_DEVIATIONS） | 计划 v0.9 评估 |
| `体检.sh` / `环境就绪.sh` | `mmagent/runtime/environment.py`（诊断 + 工具发现） | 计划 v0.2 |
| `跑后指标.py`（回流账 + P 检测 → 交付报告） | `mmagent/mm/pipeline/s6` 复盘服务 + metrics | 计划 v0.8 |

## 2. 门检（机械判据）

| 原门 | 核心判据（观察到的行为） | 本仓库实现 | 状态 |
|---|---|---|---|
| G0 | 题面契约顶层键（赛题/问题/硬约束清单/歧义裁定/附件清单）；每问 原文摘录/解读/需求条目；需求号 `N-序号` 连续；歧义裁定每条有裁定+理由；附件清单覆盖 数据/ 全部文件；需求矩阵条目数=需求条目数 | `mmagent/mm/gates/g0.py` | 计划 v0.4 |
| G1 | 计划存在、每问路线已裁决、原型真实跑过（判据在读 路线侦察/计划 + 实验记录） | `mmagent/mm/gates/g1.py` | 计划 v0.4 |
| G2:问N | 结果键存在且非空；红队结论对齐（容差 1%）；仲裁台账 应改方=建模 条目 消解状态 已消解/已解释；实验记录分流（科学尝试不含流程词）；核心指标非空（答案门） | `mmagent/mm/gates/g2.py` | 计划 v0.5 |
| G3 | 图数 16–22；机理/示意手绘 ≥3；柱状+折线占比 ≤1/2；同型图 ≤3；图注素材存在；图由脚本产出 | `mmagent/mm/gates/g3.py` | 计划 v0.6 |
| G4 | 编译 E=0；摘要恰 1 页；禁用词 0；有效数字小数 ≤4；内部术语密度；溯源核验；图表引用句式；段首开场词；`% src` 覆盖率 ≥0.6；表达密度/摘要画像/段首数字/段内数字硬线；自造缩写；标题缩写；图题对冲词；问题重述/总体分析要素；需求矩阵全销号；台账收敛（无阻塞级待改）；正文 ≤20 页；无 `\tableofcontents`；附录存在且外链有效；引用键 ∈ 文献卡片库 | `mmagent/mm/gates/g4.py` + `mmagent/mm/guards/*` | 计划 v0.6–v0.7 |
| G5 | G4 判据 + 台账视图收敛 + 阻塞级搁置必须清账或降级放行；页数守卫（美化后基线 +10% 且 ≥2 页）；复核前编译 | `mmagent/mm/gates/g5.py` | 计划 v0.8 |
| 叙事门 | 叙事底稿每问 `## 问题N` ≥150 字白话、五段小节标记、无公式/LaTeX/文件名/缩写/流程词/内部术语 | `mmagent/mm/gates/`（narrative gate，S4 内） | 计划 v0.6 |

## 3. 回路协议（`回路.py` → ledger/）

| 原 行为 | 本仓库实现 | 状态 |
|---|---|---|
| 台账（id/级别/目标/定位/问题/指令/验收/来源/轮次/状态/尝试次数/重开次数/回执/历史） | `mmagent/mm/ledger/issue_ledger.py`（SQLite issues + issue_history） | schema v0.1.0；逻辑 v0.7 |
| 意见身份合并（对应 显式引用；位置键+相似≥0.45；相似≥0.75；合并到已消解=重开；级别只升不降） | `issue_ledger.merge()` | 计划 v0.7 |
| 回执（修改腿只报改动+证据，不许改台账；未知 id 忽略） | `ledger/repair_receipt.py` | 计划 v0.7 |
| 裁定（评审先逐条已消解/未消解 + 相对判断 更好/持平/更差；只有评审能置已消解；待复核未裁→回待改） | `ledger/verdict_merge.py` | 计划 v0.7 |
| 弃权票合并 R45（评委模拟 + 未核实词 → 弃权不算否决） | `verdict_merge.abstain()` | 计划 v0.7 |
| 修订守卫 R36（句子单位；点名掩码：句级/范围"从A到B"/段级结构动词；比例=min(未点名句改动比, 字符丢失比)；上限 0.45/升格 0.70） | `mmagent/mm/guards/change_guard.py` | 计划 v0.7 |
| 结构守卫（\input 集不减、空章、附录源码清单不减、标题序列锁定） | `guards/structure_guard.py` | 计划 v0.7 |
| 页数守卫（美化后基线 +max(10%,2页)；骤降告警） | `guards/page_guard.py` | 计划 v0.7–v0.8 |
| 最优保留（轮快照；相对判断 更差→回退；持平看分数跌破噪声带 0.5 才回退） | `orchestration/` snapshot + rollback | 计划 v0.7 |
| 熔断（尝试≥2；硬伤/正确性→升格一次再搁置；叙述/版式→搁置留痕） | `ledger/fuse.py` | 计划 v0.7 |
| 条目涉及问 R46（问题N/问N/问题一二三/章号 4.N. 8.N.） | `issue_ledger.related_questions()` | 计划 v0.7 |
| 代码章免检 R47（文件名含 源码/代码；lstinputlisting/inputminted；≥半数行在 lstlisting/verbatim/minted） | `structure_guard.is_code_chapter()` | 计划 v0.7 |
| 统稿守卫（事实层逐文件相等：数字多重集合/label/ref/cite 集/公式数/插图数/标题序列/`% src` 只增不减） | `guards/` 统稿守卫（事实层指纹） | 计划 v0.6 |
| stale-value（换版清单：键/旧值/新值/出现处；猎手 grep 旧值） | `mm/contracts/change_manifest.py` + `guards/stale_value_guard.py` | 计划 v0.5（契约）/v0.7（守卫） |

## 4. S2 / 红队语义

| 原 行为 | 本仓库实现 | 状态 |
|---|---|---|
| 红队独立复算流程（红队腿只写复算.py → 驱动跑 → 比对报告腿 → 逐键容差 1% → 口径行不计入不齐 → 仲裁 → 应改建模 → 返工+重跑+声明刷新+红队复核（深度1，不递归）） | `mm/mm/pipeline/s2_model.py` + 权限系统 | 计划 v0.5 |
| 红队信息隔离（任务文本"严禁读"） | **升级为 Runtime 权限硬隔离**：`workspace/permissions.py` 默认 deny，红队角色 read_scopes 不含 求解/** 与建模笔记；测试断言 PermissionDenied | 计划 v0.2（权限）/ v0.5（测试） |
| 冻结合成输入包（数据/问题N_冻结合成输入/ + 输入清单.json 含 SHA256） | `mm/contracts/data_archive.py` 语义 | 计划 v0.5 |
| G2 返工指纹跳过（求解脚本+结果 SHA 不变 → 跳过声明刷新与红队复核） | `pipeline/s2` 优化 | 计划 v0.5 |
| 升格蜂群（3 变体并行写 + 驱动跑 + 裁决腿 + 红队复核 + 解读） | `pipeline/s2` escalation | 计划 v0.5 |
| 级联重算（全部下游取消完成 → 拓扑序重跑） | `orchestration/` + dag | 计划 v0.5 |
| R44 只复检（已降级问回炉后只复检一次） | `pipeline/s2` | 计划 v0.7 |

## 5. S5 审稿场

| 原 行为 | 本仓库实现 | 状态 |
|---|---|---|
| 每轮 18 步（编译→渲染页→审计→机械门→审A/审B/硬伤/评委页图→五路意见并台账→上轮回执裁定→相对判断回退→收敛判定→熔断→按 算图文 回炉→变化守卫→编译修复→轮级 checkpoint→末轮只评） | `mm/mm/pipeline/s5_review.py` | 计划 v0.7 |
| 需求矩阵销号进台账 / 机械审计发现逐条进台账（溯源存疑/禁用词/表达超线/缩写/图题对冲） | s5 意见源 | 计划 v0.7 |
| S5a 摘要定稿（复述门：四要素逐条复述） | `pipeline/s5a` | 计划 v0.8 |
| S5b 美化（页图审查；目标=图 → 绘图师+成图脚本；目标=文 → 排版执行；每轮 编译+页数守卫） | `pipeline/s5b` | 计划 v0.8 |
| G5 返工图路 R49 / 复核前编译 R51 / 页数守卫 R52 / 算条搁置 R50 | `pipeline/g5_publish.py` | 计划 v0.8 |
| S6（逐页终审→终审整改→final compile→出版收割→复盘官） | `pipeline/s6_finalize.py` | 计划 v0.8 |

## 6. 角色与腿

| 原 | 本仓库 | 状态 |
|---|---|---|
| `角色/*.md` 17 个提示词（围栏 schema） | `mmagent/mm/roles/<role>/{prompt.md, role.yaml}` — clean-room 重写；schema 以 Pydantic 为唯一权威（`mm/contracts/*`），prompt 只引用字段名 | 计划 v0.4–v0.8 |
| `role.sh` / `图片腿.sh` / `codex公共.sh` / `claude公共.sh` | `mmagent/agent/session.py`（tool-calling loop 替代 CLI 子进程） | 计划 v0.3–v0.5 |
| 契约表 + 契约核对（生产方声明 ⊆/⊇ 消费方读取） | `mm/contracts/`（Pydantic 单一事实来源）+ contract tests | v0.1.0 起框架 |
| 腿-驱动约定（done 标记/AUTO、回执格式、对应/目标/级别、推断目标词表兜底） | Task 状态机 + SUCCEEDED 判据（expected artifacts + schema + verifier） | v0.1.0 起（语义），v0.7（意见条目） |
| 词表/阈值资产（禁用词/对冲词/流程词/内部术语/缩写白名单/表达阈值.json） | `mm/config/`（数值阈值代码化）+ `fixtures/`（词表数据文件，记录来源为行为观察） | 计划 v0.6–v0.7 |
| HMML 方法库 / 方法卡片库 / 范文卡片库 / 优秀论文标准 | 规划师/撰稿师上下文资产；v1 内以精简自有版本实现（不复制文本），KNOWN_DEVIATIONS 记录 | 计划 v0.6 评估 |

## 7. P1–P10 提示词病根（复现为角色约束，不复制文本）

| P | 病根 | 新实现承载点 |
|---|---|---|
| P1 | 红队/建模口径不一致 | 红队 role.yaml 约束 + 结果声明 contract 的 口径说明 四段 + 仲裁 contract |
| P2 | 返工单不分实现/方法级 | 返工 contract `level: implementation\|methodical`；同项 FAIL≤2 |
| P3 | 重算后旧值残留 | 换版清单 contract + stale_value_guard |
| P4 | 指令无边界、体量失控 | 审稿意见 contract 指令字段校验 + change_guard + 撰稿 role 约束 |
| P5 | 版式混入正确性 | 意见 `severity_class: correctness\|layout` |
| P6 | 美化图类意见派错人 | 意见 `target: figure\|text` |
| P7 | 章评不限量不分级 | 章评 contract 每章 ≤5 条 + severity + 轮≥2 只评改动段（pipeline 控制） |
| P8 | 脚本自检致死/裸 python | tool 层：受管解释器唯一入口；自检非致命写 JSON |
| P9 | 猎手按旧 PDF 判 | 硬伤 contract 必填 依据版本（PDF mtime+页码）；G5 复核前强制编译 |
| P10 | 复盘不量回流 | 复盘 contract 必含回流账（metrics 从事件流统计） |
