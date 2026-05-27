"""文本替换工具 —— 对原文进行位置精确的多模式替换。

避免使用 str.replace() 全局替换带来的误匹配问题：
例如 "张三" 不应替换 "张三科技有限公司" 中的 "张三" 子串。
"""

from __future__ import annotations


def replace_by_lookup(
    text: str,
    lookup: dict[str, str],
) -> str:
    """根据查找表替换文本中所有匹配位置。

    按 key 长度降序查找（长的优先），收集所有位置后倒序替换，
    确保短 key 不会截断长 key 的部分匹配。
    """
    if not lookup:
        return text

    # 按 key 长度降序排列：长的先占位，短的发现重叠就跳过
    sorted_keys = sorted(lookup.keys(), key=len, reverse=True)

    replacements: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []

    for search in sorted_keys:
        replace = lookup[search]
        start = 0
        while True:
            idx = text.find(search, start)
            if idx < 0:
                break
            end = idx + len(search)
            # 检查是否与已占用的范围重叠（长 match 已占住此位置）
            if not any(not (end <= occ_start or idx >= occ_end) for occ_start, occ_end in occupied):
                replacements.append((idx, end, replace))
                occupied.append((idx, end))
            start = idx + 1

    if not replacements:
        return text

    # 倒序替换保证索引不偏移
    replacements.sort(key=lambda r: r[0], reverse=True)

    chars = list(text)
    for start, end, replacement in replacements:
        chars[start:end] = list(replacement)

    return "".join(chars)
