from __future__ import annotations


CN_ORDINALS = "甲乙丙丁戊己庚辛壬癸"


class TypeCounters:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def next(self, key: str) -> str:
        count = self._counts.get(key, 0) + 1
        self._counts[key] = count
        if count <= len(CN_ORDINALS):
            return CN_ORDINALS[count - 1]
        return f"{count}"

