# SOURCE_SNAPSHOT — 规格快照（固定复现目标）

> 本文件记录参考仓库的固定快照。整个 v0.x 的复现目标以本快照为准。
> 上游更新不自动跟进；升级快照需要先写 ADR。

## MM-Final-Skill（业务规格主要来源）

- URL: https://github.com/qybaihe/MM-Final-Skill
- 快照 HEAD commit SHA: `5f507e0bea0cc1d2f75e60a55fa264c436e2e52d`
- 克隆日期: 2026-09-19
- 本地路径: `.reference/MM-Final-Skill`（gitignored，只读）
- 检出方式备注: Windows git 无法检出 6 个文件名含 `:` 的样例产物
  （`参考论文/2025国赛B_对照版/审稿/门检_G2:{1,2,3}.json`、
  `真题测试/归档_第一次全开跑/蜂巢镜像/审稿/门检_G2:{1,2,3}.json`）。
  该仓库以 `core.protectNTFS=false` + no-cone sparse-checkout 检出，
  上述 6 个文件不在工作树中。它们是历史样例输出，不是规格来源；不影响复现。

## Mrite（仅产品形态参考）

- URL: https://github.com/Rzna-5559/Mrite
- 快照 HEAD commit SHA: `72f87c78b3de3ae5d117f2ff89ea363ea3d7173e`
- 克隆日期: 2026-09-19
- 本地路径: `.reference/Mrite`（gitignored，只读）
- 用途: 仅参考"一键导入题目/数据 → 自动求解 → 论文"的客户端产品体验。
  其 `App/` 当前不是可复用实现，不作为工程依赖。

## 被视为规格来源的文件清单（MM-Final-Skill）

主要规格（已完整阅读）：
- `README.md` — 全景、量级、许可状态
- `.claude/skills/paper-foundry/SKILL.md` — 操盘手册（开炉/续跑/监督/切换/收尾）
- `.claude/skills/paper-foundry/references/流程与档位.md` — 31 节点流程表、三档差异、角色分档、机时参考
- `.claude/skills/paper-foundry/references/铁律.md` — 20 条铁律（每条对应真实事故）
- `.claude/skills/paper-foundry/references/角色与契约.md` — 17 角色读写范围、契约所有权、腿-驱动约定
- `.claude/skills/paper-foundry/references/提示词与回流.md` — P1–P10 条款、回流预算、质量军规清单
- `.claude/skills/paper-foundry/references/监督清单.md` — 日志事件语义、回流预算表

核心实现（行为不变量来源；按结构+关键段阅读）：
- `流水线/调度器.py` — 状态机 / 依赖 DAG / 门框架 / 修订单合并（全文）
- `流水线/回路.py` — 台账 / 回执 / 裁定 / 修订守卫 / 最优保留 / 熔断（全文）
- `流水线/本地蜂巢.py` — 腿拉起 / 进程组 / env 口径（全文）
- `流水线/蜂群驾驶.py` — 配置 / wave / get_json / 红队复算 / G2 门 / 级联重算 / S5 审稿场等（结构 + 关键段）
- `流水线/运行时/契约表.py` — 契约所有权登记（全文）
- `流水线/运行时/统稿守卫.py` — 事实层守卫（全文）
- `流水线/运行时/门检.py` — G0/G2/G3/G4/G5/叙事门全部机械判据（结构 + 判据清单）
- `流水线/运行时/审计.py` — 溯源核验 / 表达画像 / 数字一致性（结构）
- `流水线/运行时/表达阈值.json`、`禁用词.txt`、`对冲词.txt`、`流程词.txt`、`内部术语.txt`、`缩写白名单.txt` — 词表类阈值

辅助参考（按需阅读）：
- `流水线/角色/*.md`（17 个正式角色文件；`_备份_*` 非现行规格）
- `流水线/验证/*.py` — 契约核对、驱动干跑 10 场景、各类单测
- `.claude/skills/paper-foundry/references/故障手册.md`、`切换手册.md`、`经验沉淀.md`、`交付报告模板.md`
- `病根台账.md`、`施工日志.md` — 53 条链路病根（R 系列）+ 10 条提示词病根（P 系列）

## 许可证状态

- MM-Final-Skill：README §9 声明"本仓库其余代码与文档由作者完成；许可证待补充，在此之前保留所有权利"。
  仓库内无 LICENSE 文件。**因此本仓库（MM-Agent Desktop）不复制其任何源码 / 提示词文本，
  只做 clean-room 功能兼容重实现；行为不变量记录在 SOURCE_MAP / FIDELITY_MATRIX。**
  其中 `参考项目/MM-Agent关键源码` 节选自 usail-hkust/LLM-MM-Agent（CC BY-NC 4.0），同样不复制。
- Mrite：未作为代码来源，仅产品思路参考。
