"""17 角色注册表：权限 / 工具 / reasoning 档的唯一配置来源（复现上游 角色与契约.md）。

设计约束：
- 每个角色一个 RoleSpec（id/display/分档/scopes/tools）；
- 红队隔离是**权限层事实**：red_team 的 read_scopes 不含 求解/**（建模代码）、
  建模笔记、结果解读（外审 P0-2/P0-3 之后由 PermissionChecker + PathPolicy 强制）；
- host_code 只授予"运行宿主任意代码等价能力"的角色（建模师：真正要跑求解脚本）；
  红队只写复算脚本（驱动执行），不授予；
- prompt.md 在 v0.4+ 各版本 clean-room 落地，本注册表只管权限与路由。
"""
from __future__ import annotations

from dataclasses import dataclass

from mmagent.mm.config.thresholds import ROLE_REASONING_TIERS
from mmagent.workspace.permissions import RolePermissions


@dataclass(frozen=True)
class RoleSpec:
    role_id: str
    display_name: str
    stage: str  # 主要阶段（S0..S6）
    read_scopes: tuple[str, ...]
    write_scopes: tuple[str, ...]
    allowed_tools: frozenset[str]
    host_code: bool = False
    network: bool = False
    shell: bool = False
    notes: str = ""

    @property
    def reasoning(self) -> str:
        return ROLE_REASONING_TIERS[self.role_id]

    def permissions(self, **vars: str) -> RolePermissions:
        return RolePermissions(
            role_id=self.role_id,
            read_scopes=self.read_scopes,
            write_scopes=self.write_scopes,
            allowed_tools=self.allowed_tools,
            network=self.network,
            shell=self.shell,
            host_code=self.host_code,
        ).with_vars(**vars)


_FS_RW = frozenset({"fs.read", "fs.write"})
_FS_PY = frozenset({"fs.read", "fs.write", "python.run"})

_ROLES: tuple[RoleSpec, ...] = (
    RoleSpec(
        role_id="reader",
        display_name="读题官",
        stage="S0",
        read_scopes=("输入/**",),
        write_scopes=("交接/题面契约.json", "交接/数据档案.json", "交接/读题体检.md"),
        allowed_tools=_FS_RW,
        notes="不自己补题面没有的硬条件；输出围栏 schema 由 contracts 定义",
    ),
    RoleSpec(
        role_id="answer_predictor",
        display_name="答卷预测官",
        stage="S0",
        read_scopes=("输入/**", "交接/题面契约.json", "交接/数据档案.json"),
        write_scopes=("交接/答卷预测.json", "交接/典型答卷预测.md"),
        allowed_tools=_FS_RW,
        notes="预测高质量答卷需证明/结果/图/验证什么，驱动据此生成需求追踪矩阵",
    ),
    RoleSpec(
        role_id="planner",
        display_name="规划师",
        stage="S1",
        read_scopes=("输入/**", "交接/题面契约.json", "交接/数据档案.json", "交接/典型答卷预测.md", "交接/路线侦察.json", "交接/原型结果.json", "资产/**"),
        write_scopes=("交接/路线侦察.json", "交接/计划.json"),
        allowed_tools=_FS_RW,
        notes="不能替建模师写完整求解；原型执行由驱动编排",
    ),
    RoleSpec(
        role_id="modeler",
        display_name="建模师",
        stage="S1/S2/G2/S5",
        read_scopes=(
            "输入/**",
            "交接/题面契约.json",
            "交接/数据档案.json",
            "交接/计划.json",
            "求解/**",
            "审稿/**",
            "台账/**",
        ),
        write_scopes=(
            "求解/问题{question}/**",
            "交接/建模笔记_问题{question}.md",
            "交接/假设台账_问题{question}.json",
            "交接/实验记录.json",
            "交接/换版清单_问题{question}.json",
            "交接/升格笔记_问题{question}_*.md",
            "审稿/回执_*.json",
        ),
        allowed_tools=_FS_PY,
        host_code=True,  # 真正运行求解脚本的角色（host_code 语义见 permissions.py）
        notes="只写不跑由编排层执行；回炉必写换版清单（P3）；方法级返工必须换法（P2）",
    ),
    RoleSpec(
        role_id="red_team",
        display_name="红队",
        stage="S2/S5",
        # 硬隔离：禁读建模代码（求解/*.py）、建模笔记、结果解读——权限层拒绝，非提示词
        read_scopes=(
            "输入/**",
            "交接/题面契约.json",
            "交接/数据档案.json",
            "交接/结果声明_问题{question}.json",
            "求解/问题{question}/红队结果/**",
        ),
        write_scopes=(
            "求解/问题{question}/复算.py",
            "求解/问题{question}/红队结果/**",
            "交接/红队_问题{question}.json",
        ),
        allowed_tools=_FS_RW,  # 只写复算脚本；执行由驱动（Runtime）完成
        host_code=False,
        notes="两套口径（P1）；脚本自检不致命（P8）；信息隔离是权限层事实",
    ),
    RoleSpec(
        role_id="interpreter",
        display_name="解读师",
        stage="S2/S5",
        read_scopes=(
            "输入/**",
            "交接/题面契约.json",
            "交接/数据档案.json",
            "交接/计划.json",
            "求解/**",
            "交接/红队_问题{question}.json",
            "交接/仲裁_问题{question}.json",
            "交接/实验记录.json",
        ),
        write_scopes=(
            "交接/结果解读_问题{question}.md",
            "交接/结果声明_问题{question}.json",
            "交接/仲裁_问题{question}.json",
            "交接/返工单_问题{question}.md",
            "交接/升格裁决_问题{question}.json",
        ),
        allowed_tools=_FS_RW,
        notes="五项正确性协议一票否决；口径说明四段（P1）；返工单带层级（P2）",
    ),
    RoleSpec(
        role_id="plotter",
        display_name="绘图师",
        stage="S3/S5/G5/S5b",
        read_scopes=(
            "输入/**",
            "交接/**",
            "求解/**/结果/**",
            "审稿/**",
        ),
        write_scopes=(
            "求解/问题{question}/绘图_*.py",
            "求解/成图*.sh",
            "求解/问题{question}/图片/*.png",
            "交接/图注素材_问题{question}.json",
            "审稿/回执_*.json",
        ),
        allowed_tools=_FS_RW,
        notes="图必须由真实结果生成；成图脚本纪律（P8）；按换版清单同步（P3）",
    ),
    RoleSpec(
        role_id="figure_reviewer",
        display_name="图评师",
        stage="S3",
        read_scopes=("求解/**/图片/*.png", "交接/结果声明_问题*.json", "交接/图注素材*.json"),
        write_scopes=("审稿/图评R*.json",),
        allowed_tools=_FS_RW,
        notes="图是否支持结论/可读性/单位/图例/误导",
    ),
    RoleSpec(
        role_id="writer",
        display_name="撰稿师",
        stage="S4/S5/G4/G5/S6",
        read_scopes=(
            "输入/**",
            "交接/**",
            "求解/**/结果/**",
            "论文/**",
            "审稿/**",
            "台账/**",
            "资产/**",
        ),
        write_scopes=(
            "论文/*.tex",
            "交接/叙事底稿.md",
            "交接/论点脊柱.json",
            "交接/需求覆盖.json",
            "审稿/回执_*.json",
        ),
        allowed_tools=_FS_RW,
        notes="不能擅改算出的事实；最小修订（P4）；体量纪律：源码引用=路径+SHA+片段≤60行",
    ),
    RoleSpec(
        role_id="chapter_reviewer",
        display_name="章评师",
        stage="S4",
        read_scopes=("论文/**", "交接/**", "审稿/**", "资产/**"),
        write_scopes=("审稿/章评R*.json",),
        allowed_tools=_FS_RW,
        notes="每章≤5条、[严重度N]、轮≥2只评改动段（P7）",
    ),
    RoleSpec(
        role_id="blind_reader",
        display_name="读者",
        stage="S4/S5a",
        read_scopes=("论文/**",),  # 闭卷：不给工程上下文
        write_scopes=("审稿/读者R*.json", "审稿/摘要复述*.json"),
        allowed_tools=_FS_RW,
        notes="能否理解/卡住/自造词；摘要复述门四要素",
    ),
    RoleSpec(
        role_id="integrator",
        display_name="统稿师",
        stage="S4",
        read_scopes=("论文/**", "交接/计划.json"),
        write_scopes=("论文/*.tex", "审稿/统稿回执.json"),
        allowed_tools=_FS_RW,
        notes="只动语言层；事实层由统稿守卫机械回退（数字/label/cite/公式/标题/%src）",
    ),
    RoleSpec(
        role_id="reviewer",
        display_name="审稿员",
        stage="S5",
        read_scopes=("论文/**", "审稿/**", "交接/**", "台账/**"),
        write_scopes=("审稿/审稿意见_轮*.json", "交接/需求追踪矩阵.json"),
        allowed_tools=_FS_RW,
        notes="A/B 独立评审；指令写法纪律（P4）；版式标级（P5）；意见带 对应/目标/级别",
    ),
    RoleSpec(
        role_id="defect_hunter",
        display_name="硬伤猎手",
        stage="S5/G5",
        read_scopes=(
            "论文/**",
            "交接/**",
            "求解/**/结果/**",
            "审稿/**",
            "台账/**",
        ),
        write_scopes=(
            "审稿/硬伤_轮*.json",
            "审稿/裁定_*.json",
            "审稿/G5复核*.json",
            "审稿/S6终审复核*.json",
        ),
        allowed_tools=_FS_RW,
        notes="必查换版清单（P3）；写明依据的 PDF 版本与页（P9）",
    ),
    RoleSpec(
        role_id="judge_simulator",
        display_name="评委模拟",
        stage="S5",
        read_scopes=("论文/页/*.png", "论文/0.摘要.tex"),
        write_scopes=("审稿/评委模拟_轮*.json",),
        allowed_tools=_FS_RW,
        notes="只评看到的页；未核实=弃权不算否决（R45）；建议带级别（P5）",
    ),
    RoleSpec(
        role_id="beautifier",
        display_name="美化师",
        stage="S5b/S6",
        read_scopes=("论文/页/*.png",),
        write_scopes=("审稿/美*.json", "审稿/终审_*.json"),
        allowed_tools=_FS_RW,
        notes="页问题带 目标:图|文（P6）；图条派绘图师、文条派撰稿师",
    ),
    RoleSpec(
        role_id="retrospector",
        display_name="复盘官",
        stage="S6",
        read_scopes=("日志/**", "台账/**", "审稿/**", "交接/**", "快照/**"),
        write_scopes=("审稿/复盘报告.json",),
        allowed_tools=_FS_RW,
        notes="必须量化回流账（P10）；瓶颈与规则库建议",
    ),
)

_ROLE_BY_ID: dict[str, RoleSpec] = {r.role_id: r for r in _ROLES}


def get_role(role_id: str) -> RoleSpec:
    return _ROLE_BY_ID[role_id]


def all_roles() -> tuple[RoleSpec, ...]:
    return _ROLES


def role_ids() -> tuple[str, ...]:
    return tuple(_ROLE_BY_ID.keys())
