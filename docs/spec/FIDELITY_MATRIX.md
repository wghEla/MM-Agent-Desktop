# FIDELITY_MATRIX — 复现保真矩阵

> 逐项对照 MM-Final-Skill（快照 5f507e0b）的核心机制。
> 状态取值：NOT IMPLEMENTED / PARTIAL / MATCH / DEVIATION（详见 KNOWN_DEVIATIONS）。
> "验证方式"必须是测试或机械检查，不允许"印象分"。每版本更新。

## A. 阶段与门

| # | 机制 | 上游行为摘要 | 状态 | 验证方式 |
|---|---|---|---|---|
| A1 | S0 吃透题目（播种/读题体检/预测与矩阵） | 节点 S0.0–S0.4 | NOT IMPLEMENTED | pipeline test（v0.4） |
| A2 | G0 契约门 | 顶层键/需求号连续/附件覆盖/矩阵条目数 | NOT IMPLEMENTED | gate test（v0.4） |
| A3 | S1 战略锦标赛（侦察/每问 N 路线原型/裁决/定稿） | 原型必须真跑小样 | NOT IMPLEMENTED | pipeline test（v0.4） |
| A4 | G1 | 计划/路线/原型证据 | NOT IMPLEMENTED | gate test（v0.4） |
| A5 | S2 建模求解 + 依赖 DAG 分层 | 拓扑分层并行、层间等待 | NOT IMPLEMENTED | dag unit + pipeline test（v0.5） |
| A6 | 红队独立复算 | 只写复算.py→驱动跑→比对→容差1%→口径行不计 | NOT IMPLEMENTED | pipeline + isolation test（v0.5） |
| A7 | 口径差/数值差区分 | 分歧明细 类型=口径 不触发仲裁 | NOT IMPLEMENTED | unit（v0.5） |
| A8 | 仲裁 | 解读师定责：建模错/红队错/口径成立；复核轮存档 | NOT IMPLEMENTED | pipeline test（v0.5） |
| A9 | G2 每问门 | 答案键非空+红队对齐+仲裁台账结清+实验记录分流 | NOT IMPLEMENTED | gate test（v0.5） |
| A10 | 普通返工 ≤2 | 门框架 最多返工=2 | NOT IMPLEMENTED | unit（v0.4 框架） |
| A11 | 升格蜂群（3 变体+裁决+红队复核+解读） | 连败触发 | NOT IMPLEMENTED | pipeline test（v0.5） |
| A12 | 降级放行保留 unresolved | 降级记录进状态+交付报告；R44 只复检 | NOT IMPLEMENTED | pipeline test（v0.5/v0.7） |
| A13 | S3 图证 + 图评循环（2 轮/阈值 7.0） | 图评 → 修订 → 再评 | NOT IMPLEMENTED | pipeline test（v0.6） |
| A14 | G3 | 图数 16–22 等 | NOT IMPLEMENTED | gate test（v0.6） |
| A15 | S4（叙事底稿→脊柱/主控→撰稿→章评+闭卷读者→定向修订→守卫→统稿→摘要蜂群→复述门） | 顺序固定 | NOT IMPLEMENTED | pipeline test（v0.6） |
| A16 | G4 | 机械判据清单（见 SOURCE_MAP §2） | NOT IMPLEMENTED | gate test（v0.6–v0.7） |
| A17 | S5 审稿场 18 步/轮 | 编译→…→轮级 checkpoint；末轮只评 | NOT IMPLEMENTED | pipeline test（v0.7） |
| A18 | Reviewer A/B + 硬伤猎手 + 评委模拟（页图） | 四路 + 机械门=第五路 | NOT IMPLEMENTED | pipeline test（v0.7） |
| A19 | S5a 摘要定稿 / S5b 美化 | 复述门；图/文分路 | NOT IMPLEMENTED | pipeline test（v0.8） |
| A20 | G5 出版门（终编→台账视图→审计→门检；图路/复核前编译/页数守卫/算条搁置） | R49/R50/R51/R52 | NOT IMPLEMENTED | gate test（v0.8） |
| A21 | S6（逐页终审→整改→收割→复盘） | 复盘含回流账 | NOT IMPLEMENTED | pipeline test（v0.8） |

## B. 回路与台账

| # | 机制 | 状态 | 验证方式 |
|---|---|---|---|
| B1 | Issue Ledger 状态机（待改/待复核/已消解/未消解/搁置） | NOT IMPLEMENTED | unit（v0.7） |
| B2 | 意见身份合并（对应/位置键+0.45/相似0.75/重开/级别只升不降） | NOT IMPLEMENTED | unit（v0.7） |
| B3 | 回执（修改腿不改台账；未知 id 忽略；尝试次数只在回执时加） | NOT IMPLEMENTED | unit（v0.7） |
| B4 | 配对裁定（先逐条后相对；只有评审能销号；漏裁→回待改） | NOT IMPLEMENTED | unit（v0.7） |
| B5 | 弃权票合并 R45 | NOT IMPLEMENTED | unit（v0.7） |
| B6 | 收敛判据=阻塞级清零（分数仅诊断；末轮/轮数上限退出留账） | NOT IMPLEMENTED | pipeline test |
| B7 | 熔断（≥2 次；硬伤/正确性升格一次再搁置；叙述/版式搁置） | NOT IMPLEMENTED | unit（v0.7） |
| B8 | Change Guard（句子单位/点名掩码三层/min(未点名比,字丢比)/0.45 与 0.70） | NOT IMPLEMENTED | unit（v0.7） |
| B9 | Structure Guard（\input 集/空章/附录源码清单/标题序列；代码章免检 R47） | NOT IMPLEMENTED | unit（v0.7） |
| B10 | Page Guard（基线+max(10%,2页)；骤降告警） | NOT IMPLEMENTED | unit（v0.8） |
| B11 | 统稿守卫（事实层逐文件指纹；% src 只增不减） | NOT IMPLEMENTED | unit（v0.6） |
| B12 | 换版清单/stale-value（重算→清单→图→文→猎手 grep 旧值） | NOT IMPLEMENTED | pipeline test |
| B13 | 最优保留/回退包（相对判断；噪声带 0.5） | NOT IMPLEMENTED | unit（v0.7） |
| B14 | 级联重算（下游全部作废，拓扑序重跑） | NOT IMPLEMENTED | dag test（v0.5） |

## C. 角色与腿

| # | 机制 | 状态 | 验证方式 |
|---|---|---|---|
| C1–C17 | 17 个角色（读题官/答卷预测官/规划师/建模师/红队/解读师/绘图师/图评师/撰稿师/章评师/读者/统稿师/审稿员/硬伤猎手/评委模拟/美化师/复盘官），各有 role.yaml + clean-room prompt + read/write scopes + tools + reasoning 档 + schema + tests | NOT IMPLEMENTED | 每角色 contract test + role smoke |
| C18 | 角色分档（算证裁 xhigh；写审 high；看图/读者/复盘 medium） | NOT IMPLEMENTED | config test（v0.4） |
| C19 | 红队硬隔离（权限层拒绝读 求解/**、建模笔记、解读） | NOT IMPLEMENTED | permission test（v0.2/v0.5） |
| C20 | 腿成功不由模型自宣告（产物存在+schema+verifier+事务） | MATCH (v0.1.0) | test_kernel_acceptance + test_model_cannot_declare_success_without_artifact |

## D. 档位与阈值（复现值）

| # | 项 | 上游值 | 状态 | 落点 |
|---|---|---|---|---|
| D1 | 红队相对容差 | 0.01 | NOT IMPLEMENTED | `mm/config/thresholds.py` |
| D2 | 图评 2 轮 / 阈值 7.0 | 同 | NOT IMPLEMENTED | 同 |
| D3 | 章评 2 轮 / 阈值 7.0 | 同 | NOT IMPLEMENTED | 同 |
| D4 | 审稿达标 8.6 / 平台期 0.15 | 同 | NOT IMPLEMENTED | 同 |
| D5 | 美观阈值 8.5 | 同 | NOT IMPLEMENTED | 同 |
| D6 | 变化守卫 0.45 / 升格 0.70 | 同 | NOT IMPLEMENTED | 同 |
| D7 | 默认并发 4（429→降，下限 2） | 同 | NOT IMPLEMENTED | runtime config |
| D8 | 深度档（路线3/摘要5/审稿4/美化2/MAX_LEGS600/MAX_HOURS40/全员高档） | 同 | NOT IMPLEMENTED | profiles |
| D9 | 标准档（摘要3/审稿3/角色分档/MAX_HOURS30） | 同 | NOT IMPLEMENTED | profiles |
| D10 | 快速档（只最难问/路线2/摘要3/审稿2/美化1/MAX_HOURS20） | 同 | NOT IMPLEMENTED | profiles |
| D11 | 正文 ≤20 页、图 16–22、`% src` 覆盖率 ≥0.6、小数 ≤4 位 | 同 | NOT IMPLEMENTED | gates |

## E. 运行时与韧性

| # | 机制 | 状态 | 验证方式 |
|---|---|---|---|
| E1 | 单运行锁（一父目录一驱动） | MATCH (v0.1.0 基础版：run.lock + pid 存活检查；v0.2 强化) | test_run_lock_prevents_second_owner + test_stale_lock_allows_takeover |
| E2 | 断点续跑（节点级 + S5 轮级；RUNNING 残留不得假定成功） | PARTIAL（v0.1.0：事件/事务/崩溃恢复 reset_interrupted_tasks；轮级断点 v0.7） | test_crash_recovery_marks_running_failed |
| E3 | 暂停/恢复/取消 + 进程树回收 | PARTIAL（v0.1.0：CancellationToken + python.run 进程树终止；Job Object v0.2） | test_cancel_mid_run + test_tool_timeout_kills_process |
| E4 | 超时分级（腿上限 < 波次超时，防双写；重派前回收旧副本 R60） | PARTIAL（工具级超时已实现；波次/重派语义属编排层 v0.5+） | test_tool_timeout_kills_process |
| E5 | 429 限流降并发（不是任务失败） | PARTIAL（v0.1.0：RateLimitError → QUEUED 可重试语义；并发调节 v0.5） | test_rate_limit_is_retryable_not_failure |
| E6 | 预算护栏（MAX_LEGS/MAX_HOURS；S2 逐问检查；转应急出版） | PARTIAL（v0.1.0：Budget 类骨架；编排层接入 v0.5） | budget unit（随 v0.5 补） |
| E7 | JSON 修复回路（校验失败带反馈重写一次） | PARTIAL（工具参数 JSON 错误回填模型可自愈；产物级修复回路 v0.5） | test_bad_tool_args_json_does_not_crash |
| E8 | 编译修复循环（E 不归零重试 ≤N；连续失败插手语义） | NOT IMPLEMENTED（v0.6） | pipeline test |
| E9 | 回流账（跑后统计；预算对照） | NOT IMPLEMENTED（v0.8） | metrics test |
| E10 | 契约核对（消费字段 ⊆ 生产声明） | MATCH (v0.1.0 框架：Pydantic 单一权威 + artifacts schema 校验；完整 contract tests 随角色落地) | test_kernel_acceptance（schema_id 校验） |

## F. 明确不复制（有意偏差，详见 KNOWN_DEVIATIONS）

| 项 | 理由 |
|---|---|
| codex exec / claude -p 腿引擎、role.sh/图片腿.sh | 自研 tool-calling Runtime 替代 |
| macOS bash 3.2 脚本族（启动/停跑/状态/看守/切换/体检） | Windows 桌面客户端 API/UI 替代 |
| 状态.json / 日志/*.done / *.pid 作为状态真相 | SQLite + append-only events 为真相，JSON 导出为 carrier |
| seatbelt / acceptEdits 沙箱 | 自研 workspace 权限系统（默认 deny + scopes + reparse 防护） |
| HMML/范文/文献卡片库原文 | 不复制文本；以精简自有资产替代（行为目标不变：规划师有方法库、撰稿有范文锚点、引用可核验） |
| 词表原文（禁用词等） | 行为目标复现，词表内容以自有等价集起步并允许用户扩展 |
