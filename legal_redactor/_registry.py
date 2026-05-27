"""统一实体注册表 EntityRegistry。

核心原则：同一主体的全称、简称、去后缀形式共用同一占位符。
- 河南省 / 河南 → [某省1]
- 北京某某科技有限公司 / 某某科技公司 / 被告公司 → [公司1]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── 行政区划全称→简称映射 ────────────────────────────────────────

_ADMIN_SHORT_MAP: dict[str, str] = {
    # 直辖市
    "北京市": "北京", "上海市": "上海", "天津市": "天津", "重庆市": "重庆",
    # 省会及主要城市（去"市"后缀即为简称）
    "石家庄市": "石家庄", "太原市": "太原", "呼和浩特市": "呼和浩特",
    "沈阳市": "沈阳", "长春市": "长春", "哈尔滨市": "哈尔滨",
    "南京市": "南京", "杭州市": "杭州", "合肥市": "合肥",
    "福州市": "福州", "南昌市": "南昌", "济南市": "济南",
    "郑州市": "郑州", "武汉市": "武汉", "长沙市": "长沙",
    "广州市": "广州", "南宁市": "南宁", "海口市": "海口",
    "成都市": "成都", "贵阳市": "贵阳", "昆明市": "昆明",
    "拉萨市": "拉萨", "西安市": "西安", "兰州市": "兰州",
    "西宁市": "西宁", "银川市": "银川", "乌鲁木齐市": "乌鲁木齐",
    "大连市": "大连", "青岛市": "青岛", "宁波市": "宁波",
    "厦门市": "厦门", "深圳市": "深圳", "苏州市": "苏州",
    "无锡市": "无锡", "佛山市": "佛山", "东莞市": "东莞",
    "珠海市": "珠海", "中山市": "中山", "惠州市": "惠州",
    "温州市": "温州", "绍兴市": "绍兴", "嘉兴市": "嘉兴",
    "徐州市": "徐州", "南通市": "南通", "常州市": "常州",
    "烟台市": "烟台", "潍坊市": "潍坊", "洛阳市": "洛阳",
    "唐山市": "唐山", "邯郸市": "邯郸", "保定市": "保定",
    # 自治区/自治州
    "内蒙古自治区": "内蒙古", "广西壮族自治区": "广西",
    "西藏自治区": "西藏", "宁夏回族自治区": "宁夏",
    "新疆维吾尔自治区": "新疆",
    "延边朝鲜族自治州": "延边",
}

# 构建反向查找：简称→全称
_SHORT_TO_FULL: dict[str, str] = {}
for _full, _short in _ADMIN_SHORT_MAP.items():
    _SHORT_TO_FULL[_short] = _full
    # 也注册带后缀的简称变体
    _suffix = _full[-1] if _full.endswith(("省", "市", "区")) else ""
    if _suffix and _short + _suffix not in _SHORT_TO_FULL:
        pass  # 简称已存在于 map


@dataclass
class EntityEntry:
    """注册表中的一条实体记录。"""

    canonical: str
    entity_type: str
    aliases: set[str] = field(default_factory=set)
    placeholder: str = ""
    role: str | None = None
    source: str = ""
    confidence: float = 1.0
    locked: bool = False

    def all_forms(self) -> set[str]:
        return {self.canonical} | self.aliases

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical": self.canonical,
            "type": self.entity_type,
            "aliases": sorted(self.aliases),
            "placeholder": self.placeholder,
            "role": self.role,
            "source": self.source,
            "confidence": self.confidence,
            "locked": self.locked,
        }


class EntityRegistry:
    """全局实体注册表。每个独立主体一条记录，所有变体指向同一占位符。"""

    def __init__(self) -> None:
        self._entries: list[EntityEntry] = []
        self._form_to_entry: dict[str, EntityEntry] = {}  # 任何变体→条目

    def register(
        self,
        canonical: str,
        entity_type: str,
        aliases: set[str] | None = None,
        placeholder: str = "",
        role: str | None = None,
        source: str = "",
        confidence: float = 1.0,
        locked: bool = False,
    ) -> EntityEntry:
        """注册实体。如果已有同名实体则返回已有条目。"""
        if canonical in self._form_to_entry and self._form_to_entry[canonical].entity_type == entity_type:
            existing = self._form_to_entry[canonical]
            if aliases:
                existing.aliases.update(aliases)
                for a in aliases:
                    self._form_to_entry.setdefault(a, existing)
            return existing

        entry = EntityEntry(
            canonical=canonical,
            entity_type=entity_type,
            aliases=aliases or set(),
            placeholder=placeholder,
            role=role,
            source=source,
            confidence=confidence,
            locked=locked,
        )
        self._entries.append(entry)
        self._form_to_entry[canonical] = entry
        for a in entry.aliases:
            self._form_to_entry.setdefault(a, entry)
        return entry

    def resolve(self, text: str) -> EntityEntry | None:
        """查找文本对应的实体条目。"""
        return self._form_to_entry.get(text)

    def generate_admin_aliases(self) -> None:
        """为已注册的行政区划实体自动生成简称别名。"""
        for entry in self._entries:
            if entry.entity_type != "location":
                continue
            short = _ADMIN_SHORT_MAP.get(entry.canonical)
            if short and short not in entry.aliases:
                entry.aliases.add(short)
                self._form_to_entry.setdefault(short, entry)

    def get_lookup(self) -> dict[str, str]:
        """生成 original → placeholder 查找表。最长 canonical 优先。"""
        result: dict[str, str] = {}
        for entry in sorted(self._entries, key=lambda e: len(e.canonical), reverse=True):
            if entry.placeholder:
                result[entry.canonical] = entry.placeholder
                for a in sorted(entry.aliases, key=len, reverse=True):
                    if a not in result:
                        result[a] = entry.placeholder
        return result

    def __len__(self) -> int:
        return len(self._entries)

    def entries(self) -> list[EntityEntry]:
        return list(self._entries)
