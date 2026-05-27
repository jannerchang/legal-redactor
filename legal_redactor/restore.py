from __future__ import annotations

import difflib

from ._replace_text import replace_by_lookup
from .models import MappingEntry, RedactionMap, RestorePreview


def restore_text(redacted_text: str, redaction_map: RedactionMap, restore_all: bool = False) -> str:
    """还原脱敏文本：按映射表将占位符替换回原文。

    使用位置查找 + 字符数组倒序替换，避免全局 str.replace()
    可能的误匹配问题（例如某个占位符碰巧出现在不应还原的上下文中）。
    """
    entries = _entries_to_restore(redaction_map.mappings, restore_all)
    lookup = {entry.masked: entry.original for entry in entries if entry.masked}
    return replace_by_lookup(redacted_text, lookup)


def preview_restore(redacted_text: str, redaction_map: RedactionMap, restore_all: bool = False) -> RestorePreview:
    restored_entries = _entries_to_restore(redaction_map.mappings, restore_all)
    skipped_entries = [entry for entry in redaction_map.mappings if entry not in restored_entries]
    restored_text = restore_text(redacted_text, redaction_map, restore_all)
    diff = "\n".join(
        difflib.unified_diff(
            redacted_text.splitlines(),
            restored_text.splitlines(),
            fromfile="redacted",
            tofile="restored",
            lineterm="",
        )
    )
    return RestorePreview(
        restored_text=restored_text,
        restored_entries=restored_entries,
        skipped_entries=skipped_entries,
        diff=diff,
    )


def _entries_to_restore(entries: list[MappingEntry], restore_all: bool) -> list[MappingEntry]:
    if restore_all:
        return list(entries)
    return [entry for entry in entries if entry.restore_by_default]

