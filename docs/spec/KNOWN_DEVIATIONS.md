# KNOWN_DEVIATIONS — 与参考 Skill 的已知差异（诚实台账）

> 任何时候发现"我们与上游行为不同"，必须在此登记：差异是什么、为什么、影响、是否计划消除。
> 规则：先登记，再实现；不允许悄悄偏离。

| # | 差异 | 原因 | 影响 | 计划 |
|---|---|---|---|---|
| 1 | 执行载体：CLI 腿（codex exec / claude -p 子进程 + bash 脚本）→ 自研 tool-calling Agent Runtime（进程内 asyncio + Provider API） | 总方案固定：移除 CLI 依赖 | 腿级行为语义对齐（done 标记→Task 事务；重试→retry 策略），但进程模型不同；上游的 shell 级坑（stdin、seatbelt）不适用，自有一套进程坑需自测 | 全量复现行为不变量（见 FIDELITY_MATRIX E 组） |
| 2 | 状态真相：状态.json + 日志/*.done/*.pid → SQLite + append-only event log | 总方案固定 | 断点/续跑/审计能力更强；JSON 文件变为导出 carrier（工作区仍产出同结构 交接/*.json 与 台账/*.json，保持交付习惯） | v0.1.0 起实现 |
| 3 | 平台：macOS（bash 3.2/setsid/seatbrew 路径）→ Windows 11（Job Object/pywin32/junction 防护） | 总方案固定首发 Windows | 进程回收、路径 canonicalize、沙箱语义全部重新实现并自测 | v0.2.0 |
| 4 | 沙箱：seatbelt workspace-write / acceptEdits（claude 版并非硬锁）→ 自研默认 deny 权限系统 | 总方案要求红队硬隔离优于上游 | 上游红队隔离靠提示词 + codex 工作根锁；新实现为 Runtime 强制 scopes，红队读建模代码在权限层被拒 | v0.2.0 权限系统 + v0.5 测试 |
| 5 | XeLaTeX 发现路径：上游环境就绪.sh 面向 macOS homebrew；本机实际布局 `D:\Apps\texlive\texlive\<年>\bin\windows\xelatex.exe`（比总方案初稿的 glob 多一层） | 本机真实安装结构 | 工具发现器用深度搜索 `**/bin/windows/xelatex.exe`，不硬编码年份 | v0.2.0 |
| 6 | MATLAB 发现路径：总方案初稿假设 `D:\Apps\Matlab\R*\bin\matlab.exe`；实际为直接根目录安装 `D:\Apps\Matlab\bin\matlab.exe`（v26.1） | 本机真实安装结构 | 发现器同时支持 `<root>/bin/matlab.exe` 与 `<root>/R*/bin/matlab.exe` 两种布局 | v0.2.0 |
| 7 | HMML 方法库 / 范文卡片库 / 文献卡片库 / 表达锚点原文不复制 | 许可证未明（保留所有权利）+ clean-room 约束 | 规划师/撰稿师/审计的上下文资产以自有精简版本实现，行为目标（方法选择有依据、文风有锚点、引用可核验）不变；表达判据阈值代码化 | v0.6–v0.7；若行为差异影响质量门，在 ADR 决定补建 |
| 8 | 词表资产（禁用词/对冲词/流程词/内部术语/缩写白名单/表达阈值.json）不逐词复制 | clean-room 约束 | 门检/审计的机械判据保留（覆盖率、密度、硬线等数值复现），词表以自有等价集起步；判掉的具体词可能不同 | v0.6–v0.7，用户可自行扩充词表 |
| 9 | 模型：上游对照跑用 gpt-6-astra（api.timoz.me）；新实现 Provider 无关，用户自配 | 总方案固定 Provider 抽象 | 量级数据（机时/腿数/分数）不可直接对照；不承诺复现上游分数，只复现流程与质量机制 | 长期 |
| 10 | `切换.sh`（运行中边界钩子切换链路）暂不实现 | 桌面客户端语义下"停→改→续"已覆盖主要场景；边界钩子属高级运维 | 需要时以 checkpoint + 配置迁移实现 | v0.9 评估，如不实现将在产品文档说明 |
| 11 | 上游快速档把 MAX_LEGS 保持 600；总方案要求快速档"冒烟"语义 | 遵循总方案 | 快速档继承上游全部参数（轮数/变体/路线），预算上限跟随档位（20h） | v0.4 profiles |
| 12 | 上游 Claude 引擎从未整炉实跑（401/未登录），其腿级行为数据缺失 | 上游事实 | 对齐以 codex 引擎行为为准；工具链差异坑（stdin 必须关等）不适用 | 无 |
| 13 | 参考仓库 6 个文件名含 `:` 的样例 JSON 未检出（NTFS 非法） | Windows 文件系统限制 | 无影响：均为历史样例产物，非规格 | 无 |

## 行为不变量清单（从上游事故复盘提炼，必须保持）

以下不是差异，是必须复现的"军规"（来源：铁律.md / 病根台账 / 监督清单）：

1. 腿成功不由模型自宣告：done/产物/校验由 Runtime 判（R0 教训、答案门事件）。
2. schema 单一事实来源：复制 schema = 第二事实来源 = 必漂移（契约表开头三例）。
3. 修订有机械边界（变化/结构/页数守卫），不靠模型自觉（R2/R36/R47/R52）。
4. 任何守卫豁免配一把体量尺（R47→R52 铁律 17）。
5. 意见必须有身份：identity merge，禁止换措辞开新条（回路.py 五病根①）。
6. 回执不自证：只有评审看实物能销号；漏裁不默认 PASS。
7. 修不掉的必须有出口：熔断升格/搁置留痕，绝不静默丢弃、不逼腿造假过门（G5 自造硬伤教训）。
8. 先算后图后文；重算必产换版清单；旧值必须被猎手 grep（P3）。
9. 红队禁读建模代码——权限层强制，不靠提示词。
10. 腿上限 < 波次超时；重派前回收旧副本（双写防护）。
11. 限流不是任务失败：降并发、写事件、可恢复。
12. 降级放行不是 PASS：必须高亮进交付报告。
13. 同类回流超预算即病根：每跑必算回流账（P10）。
14. 评审指令最小改动 + 引用源码只许 路径+SHA+片段 ≤60 行（P4/R38 教训）。
# KNOWN_DEVIATIONS — 与参考 Skill 的已知差异（诚实台账）

> 任何时候发现"我们与上游行为不同"，必须在此登记：差异是什么、为什么、影响、是否计划消除。
> 规则：先登记，再实现；不允许悄悄偏离。

| # | 差异 | 原因 | 影响 | 计划 |
|---|---|---|---|---|
| 1 | 执行载体：CLI 腿（codex exec / claude -p 子进程 + bash 脚本）→ 自研 tool-calling Agent Runtime（进程内 asyncio + Provider API） | 总方案固定：移除 CLI 依赖 | 腿级行为语义对齐（done 标记→Task 事务；重试→retry 策略），但进程模型不同；上游的 shell 级坑（stdin、seatbelt）不适用，自有一套进程坑需自测 | 全量复现行为不变量（见 FIDELITY_MATRIX E 组） |
| 2 | 状态真相：状态.json + 日志/*.done/*.pid → SQLite + append-only event log | 总方案固定 | 断点/续跑/审计能力更强；JSON 文件变为导出 carrier（工作区仍产出同结构 交接/*.json 与 台账/*.json，保持交付习惯） | v0.1.0 起实现 |
| 3 | 平台：macOS（bash 3.2/setsid/seatbrew 路径）→ Windows 11（Job Object/pywin32/junction 防护） | 总方案固定首发 Windows | 进程回收、路径 canonicalize、沙箱语义全部重新实现并自测 | v0.2.0 |
| 4 | 沙箱：seatbelt workspace-write / acceptEdits（claude 版并非硬锁）→ 自研默认 deny 权限系统 | 总方案要求红队硬隔离优于上游 | 上游红队隔离靠提示词 + codex 工作根锁；新实现为 Runtime 强制 scopes，红队读建模代码在权限层被拒 | v0.2.0 权限系统 + v0.5 测试 |
| 5 | XeLaTeX 发现路径：上游环境就绪.sh 面向 macOS homebrew；本机实际布局 `D:\Apps\texlive\texlive\<年>\bin\windows\xelatex.exe`（比总方案初稿的 glob 多一层） | 本机真实安装结构 | 工具发现器用深度搜索 `**/bin/windows/xelatex.exe`，不硬编码年份 | v0.2.0 |
| 6 | MATLAB 发现路径：总方案初稿假设 `D:\Apps\Matlab\R*\bin\matlab.exe`；实际为直接根目录安装 `D:\Apps\Matlab\bin\matlab.exe`（v26.1） | 本机真实安装结构 | 发现器同时支持 `<root>/bin/matlab.exe` 与 `<root>/R*/bin/matlab.exe` 两种布局 | v0.2.0 |
| 7 | HMML 方法库 / 范文卡片库 / 文献卡片库 / 表达锚点原文不复制 | 许可证未明（保留所有权利）+ clean-room 约束 | 规划师/撰稿师/审计的上下文资产以自有精简版本实现，行为目标（方法选择有依据、文风有锚点、引用可核验）不变；表达判据阈值代码化 | v0.6–v0.7；若行为差异影响质量门，在 ADR 决定补建 |
| 8 | 词表资产（禁用词/对冲词/流程词/内部术语/缩写白名单/表达阈值.json）不逐词复制 | clean-room 约束 | 门检/审计的机械判据保留（覆盖率、密度、硬线等数值复现），词表以自有等价集起步；判掉的具体词可能不同 | v0.6–v0.7，用户可自行扩充词表 |
| 9 | 模型：上游对照跑用 gpt-6-astra（api.timoz.me）；新实现 Provider 无关，用户自配 | 总方案固定 Provider 抽象 | 量级数据（机时/腿数/分数）不可直接对照；不承诺复现上游分数，只复现流程与质量机制 | 长期 |
| 10 | `切换.sh`（运行中边界钩子切换链路）暂不实现 | 桌面客户端语义下"停→改→续"已覆盖主要场景；边界钩子属高级运维 | 需要时以 checkpoint + 配置迁移实现 | v0.9 评估，如不实现将在产品文档说明 |
| 11 | 上游快速档把 MAX_LEGS 保持 600；总方案要求快速档"冒烟"语义 | 遵循总方案 | 快速档继承上游全部参数（轮数/变体/路线），预算上限跟随档位（20h） | v0.4 profiles |
| 12 | 上游 Claude 引擎从未整炉实跑（401/未登录），其腿级行为数据缺失 | 上游事实 | 对齐以 codex 引擎行为为准；工具链差异坑（stdin 必须关等）不适用 | 无 |
| 13 | 参考仓库 6 个文件名含 `:` 的样例 JSON 未检出（NTFS 非法） | Windows 文件系统限制 | 无影响：均为历史样例产物，非规格 | 无 |

## 行为不变量清单（从上游事故复盘提炼，必须保持）

以下不是差异，是必须复现的"军规"（来源：铁律.md / 病根台账 / 监督清单）：

1. 腿成功不由模型自宣告：done/产物/校验由 Runtime 判（R0 教训、答案门事件）。
2. schema 单一事实来源：复制 schema = 第二事实来源 = 必漂移（契约表开头三例）。
3. 修订有机械边界（变化/结构/页数守卫），不靠模型自觉（R2/R36/R47/R52）。
4. 任何守卫豁免配一把体量尺（R47→R52 铁律 17）。
5. 意见必须有身份：identity merge，禁止换措辞开新条（回路.py 五病根①）。
6. 回执不自证：只有评审看实物能销号；漏裁不默认 PASS。
7. 修不掉的必须有出口：熔断升格/搁置留痕，绝不静默丢弃、不逼腿造假过门（G5 自造硬伤教训）。
8. 先算后图后文；重算必产换版清单；旧值必须被猎手 grep（P3）。
9. 红队禁读建模代码——权限层强制，不靠提示词。
10. 腿上限 < 波次超时；重派前回收旧副本（双写防护）。
11. 限流不是任务失败：降并发、写事件、可恢复。
12. 降级放行不是 PASS：必须高亮进交付报告。
13. 同类回流超预算即病根：每跑必算回流账（P10）。
14. 评审指令最小改动 + 引用源码只许 路径+SHA+片段 ≤60 行（P4/R38 教训）。

## GPT Review Blocker (2026-09-27)

Cloudflare security challenge blocks automated browser access to ChatGPT.
The fidelity rebuild (v0.7.0-v1.0.0 delta) has been self-reviewed against the
pinned upstream snapshot. GPT review will be performed when browser access
is restored. Prior v0.1.0-v0.5.0 received 27+ rounds of GPT-5.6 Sol High review.

### Self-review summary for v0.7.0-v1.0.0 delta

| Area | Self-review finding |
|---|---|
| Issue Ledger | generation CAS, receipt_id idempotency, state transition table implemented; 10 tests |
| Guards | change/structure/page guards with sentence-level granularity; 8 tests |
| S5 review arena | five-leg review, R45 abstention, convergence, rework 算→图→文; pipeline tests |
| G5 rework | R49 figure route, R50 calc shelve, R51 compile-before-recheck, R52 page guard; 3 tests |
| S6 retrospective | RetrospectiveReport/RunMetrics schemas; 4 tests |
| Provider failure | auth/network/429/5xx at AgentLoop level; 6 tests |
| Tool env security | provider/cloud secrets excluded from xelatex/matlab subprocesses; 10 tests |
