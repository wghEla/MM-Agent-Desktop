"""Issue Ledger（意见台账）—— 状态机 + 身份合并 + 配对裁定（复现上游 回路.py 语义）。"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

# 状态
待改, 待复核, 已消解, 未消解, 搁置 = "待改", "待复核", "已消解", "未消解", "搁置"
阻塞级别 = ("硬伤", "正确性")
_级别序 = {"硬伤": 0, "正确性": 1, "叙述": 2, "版式": 3}


@dataclass
class Issue:
    """单条意见（有身份、有状态、跨轮存活）。"""
    id: str
    级别: str = "叙述"
    目标: str = "文"  # 算|图|文
    定位: str = ""
    问题: str = ""
    指令: str = ""
    验收: str = ""
    来源: str = ""
    轮次: int = 0
    状态: str = 待改
    尝试次数: int = 0
    重开次数: int = 0
    回执: list[dict] = field(default_factory=list)
    历史: list[dict] = field(default_factory=list)
    对应: str = ""  # 引用的上轮 id
    generation: int = 0  # 每次 reopen 递增（CAS 依据）


_PUNCT_CHARS = "，。；：、()（）【】"

def _net(s: str) -> str:
    for ch in _PUNCT_CHARS:
        s = s.replace(ch, "")
    return re.sub(r"[\s,.;:\"]+", "", str(s or "")).lower()


def _相似(a: str, b: str) -> float:
    a, b = _net(a), _net(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _位置键(定位: str) -> str:
    文件 = re.search(r"([\w.\-一-龥]+\.(?:tex|py|json|png|md))", 定位)
    数 = re.search(r"(\d+)", 定位.split("/")[-1] if "/" in 定位 else 定位)
    return ((文件.group(1) if 文件 else "") + ":" + (数.group(1) if 数 else "")).strip(":")


class IssueLedger:
    """意见台账：状态机 + 身份合并 + 回执/裁定 + 熔断。"""

    def __init__(self, *, 前缀: str = "意"):
        self.条目: list[Issue] = []
        self.轮次: int = 0
        self._前缀 = 前缀
        self._序号 = 0

    def 并入(self, 新条目: list[dict], 轮次: int) -> dict[str, int]:
        """把一轮评审的新意见并进台账。返回 {新增, 合并, 重开}。"""
        self.轮次 = max(self.轮次, 轮次)
        stats = {"新增": 0, "合并": 0, "重开": 0}
        for 新 in 新条目:
            if not isinstance(新, dict):
                新 = {"问题": str(新)}
            match = self._find_match(新)
            if match:
                stats["合并"] += 1
                match.历史.append({"轮次": 轮次, "来源": 新.get("来源", ""), "问题": 新.get("问题", "")[:200]})
                if match.状态 == 已消解:
                    match.状态 = 待改
                    match.重开次数 += 1
                    match.generation += 1  # generation 递增（round15 P1-1 CAS 依据）
                    stats["重开"] += 1
                # 级别只升不降
                if _级别序.get(新.get("级别", ""), 9) < _级别序.get(match.级别, 9):
                    match.级别 = 新["级别"]
                if 新.get("指令"):
                    match.指令 = 新["指令"]
                continue
            self._序号 += 1
            self.条目.append(Issue(
                id=f"{self._前缀}-{轮次}-{self._序号:02d}",
                级别=新.get("级别") if 新.get("级别") in _级别序 else "叙述",
                目标=新.get("目标") if 新.get("目标") in ("算", "图", "文") else "文",
                定位=str(新.get("定位", ""))[:200],
                问题=str(新.get("问题", ""))[:600],
                指令=str(新.get("指令", ""))[:600],
                验收=str(新.get("验收", ""))[:200],
                来源=str(新.get("来源", "")),
                轮次=轮次,
            ))
            stats["新增"] += 1
        return stats

    def _find_match(self, 新: dict) -> Issue | None:
        """身份合并（对应 > 位置键+相似 > 相似）。"""
        对应 = str(新.get("对应", "")).strip()
        if 对应:
            for x in self.条目:
                if x.id == 对应:
                    return x
        best: tuple[float, Issue] | None = None
        新问题 = str(新.get("问题", ""))
        新定位 = str(新.get("定位", ""))
        for x in self.条目:
            if x.状态 == 搁置:
                continue
            s = _相似(x.问题, 新问题)
            loc_key_old = _位置键(x.定位)
            loc_key_new = _位置键(新定位)
            if loc_key_old and loc_key_old == loc_key_new and s >= 0.45:
                score = s + 0.5
            elif s >= 0.75:
                score = s
            else:
                continue
            if best is None or score > best[0]:
                best = (score, x)
        return best[1] if best else None

    def 收回执(self, 回执们: list[dict], 腿名: str = "") -> dict[str, int]:
        """修改腿回执：→ 待复核。未知 id 忽略。"""
        stats = {"受理": 0, "未知id": 0}
        for r in 回执们 or []:
            x = self._get(str(r.get("id", "")).strip())
            if x is None:
                stats["未知id"] += 1
                continue
            new_change = str(r.get("改动", ""))[:300]
            import uuid as _uuid
            receipt_id = str(r.get("receipt_id", "")) or str(_uuid.uuid4())
            # 幂等（外审 round15 P1-2）：按 receipt_id 去重（非内容匹配）
            if any(rc.get("receipt_id") == receipt_id for rc in x.回执):
                continue
            x.回执.append({"腿": 腿名, "改动": new_change,
                           "证据": str(r.get("证据", ""))[:200],
                           "receipt_id": receipt_id})
            # generation CAS for receipt（round16 P1-2）
            receipt_gen = r.get("generation")
            if receipt_gen is not None and int(receipt_gen) != x.generation:
                continue  # stale receipt → 忽略
            x.尝试次数 += 1
            if x.状态 in (待改, 未消解):
                x.状态 = 待复核
            stats["受理"] += 1
        return stats

    def 收裁定(self, 裁定们: list[dict], 轮次: int | None = None) -> dict[str, int]:
        """评审腿裁定（外审 round16 P1-1）：per-item generation CAS + 状态迁移表。

        - 每条 verdict 必须携带 generation（与 issue 当前 generation 做 equality CAS）；
        - 只有 待复核 状态可以被裁定；
        - generation 不匹配 = stale，跳过。
        """
        stats = {"已消解": 0, "未消解": 0, "未知id": 0}
        for r in 裁定们 or []:
            x = self._get(str(r.get("id", "")).strip())
            if x is None:
                stats["未知id"] += 1
                continue
            # per-item generation CAS（外审 round16 P1-1：每条 verdict 必须携带）
            verdict_gen = r.get("generation")
            if verdict_gen is None or int(verdict_gen) != x.generation:
                stats["未知id"] += 1  # stale or missing generation → fail-closed
                continue
            # 状态迁移表（外审 round15 P1-2）
            if x.状态 not in (待复核,):
                stats["未知id"] += 1
                continue
            裁 = str(r.get("裁定", "")).strip()
            if 裁 == "已消解":
                x.状态 = 已消解
                stats["已消解"] += 1
            elif 裁 == "未消解":
                x.状态 = 未消解
                stats["未消解"] += 1
            else:
                # 未知裁定值 → 未消解（fail-closed，外审 round2 P1-3）
                x.状态 = 未消解
                stats["未消解"] += 1
            x.历史.append({"轮次": 轮次 or self.轮次, "裁定": 裁[:20]})
        return stats

    def 待复核未裁(self) -> int:
        """评审腿漏裁的待复核条目：不能默认通过。"""
        n = 0
        for x in self.条目:
            if x.状态 == 待复核:
                x.状态 = 待改
                x.历史.append({"轮次": self.轮次, "裁定": "评审未裁"})
                n += 1
        return n

    def 待改条目(self, 级别们: list[str] | None = None, 目标们: list[str] | None = None) -> list[Issue]:
        out = [x for x in self.条目 if x.状态 in (待改, 未消解)]
        if 级别们:
            out = [x for x in out if x.级别 in 级别们]
        if 目标们:
            out = [x for x in out if x.目标 in 目标们]
        out.sort(key=lambda x: (_级别序.get(x.级别, 9), x.id))
        return out

    def 收敛(self) -> tuple[bool, list[str]]:
        """收敛 = 没有阻塞级别的待改/待复核/未消解。"""
        阻 = [x for x in self.条目 if x.级别 in 阻塞级别 and x.状态 in (待改, 待复核, 未消解)]
        明细 = [f"{x.id} {x.级别} {x.状态}: {x.问题[:50]}" for x in 阻]
        return (not 阻), 明细

    def 熔断候选(self, 阈值: int = 2) -> list[Issue]:
        return [x for x in self.条目 if x.状态 in (待改, 未消解) and x.尝试次数 >= 阈值]

    def 搁置条目(self, id: str, 理由: str) -> bool:
        """搁置（外审 round15 P1-3）：必须是熔断候选且有非空理由。"""
        x = self._get(id)
        if x is None:
            return False
        if not 理由.strip():
            return False  # 理由不许为空
        if x.尝试次数 < 2:
            return False  # 未经两次修订不得搁置
        if x.状态 not in (待改, 未消解, 待复核):
            return False  # 活跃态+待复核可搁置（待复核时评审可能延迟）
        x.状态 = 搁置
        x.历史.append({"裁定": "搁置", "理由": 理由[:200]})
        return True

    def _get(self, id: str) -> Issue | None:
        return next((x for x in self.条目 if x.id == id), None)

    def 摘要(self) -> dict[str, int]:
        m: dict[str, int] = {}
        for x in self.条目:
            key = f"{x.级别}/{x.状态}"
            m[key] = m.get(key, 0) + 1
        return m
