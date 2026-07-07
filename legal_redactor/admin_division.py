"""SQLite-backed administrative division detector shared by regional datasets."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .models import Candidate


ADDRESS_CONTEXT_MARKERS = (
    "住",
    "住所地",
    "户籍地",
    "经常居住地",
    "位于",
    "地址",
    "所在地",
    "登记",
    "户籍",
)


@dataclass(frozen=True)
class AdminTerm:
    text: str
    canonical_name: str
    division_code: str
    level: str
    entity_type: str
    confidence: float
    source: str




class _TrieNode:
    """Minimal trie node for multi-pattern matching of admin division terms."""

    __slots__ = ("children", "term_key")

    def __init__(self) -> None:
        self.children: dict[str, _TrieNode] = {}
        self.term_key: str | None = None


def _build_trie(terms: list[AdminTerm]) -> _TrieNode | None:
    """Build a character trie from all term texts. Returns root or None if empty."""
    root = _TrieNode()
    has_entries = False
    for term in terms:
        node = root
        for char in term.text:
            child = node.children.get(char)
            if child is None:
                child = _TrieNode()
                node.children[char] = child
            node = child
        node.term_key = term.text
        has_entries = True
    return root if has_entries else None


def _trie_find_all(text: str, root: _TrieNode) -> list[tuple[int, int, str]]:
    """Scan *text* once through the trie, returning (start, end, term_key) for all matches.

    Complexity is O(len(text) * max_term_length), compared to the previous
    O(num_terms * len(text)) approach which called str.find per term.
    """
    matches: list[tuple[int, int, str]] = []
    text_len = len(text)
    for i in range(text_len):
        node = root
        j = i
        while j < text_len:
            char = text[j]
            child = node.children.get(char)
            if child is None:
                break
            node = child
            j += 1
            if node.term_key is not None:
                matches.append((i, j, node.term_key))
    return matches

class AdminDivisionDetector:
    def __init__(
        self,
        db_path: str | Path,
        *,
        source: str = "admin_division_db",
        region_label: str = "行政区划",
        max_level: str | None = None,
        require_canonical_substring: bool = False,
    ) -> None:
        self.db_path = Path(db_path)
        self.source = source
        self.region_label = region_label
        self.max_level = max_level
        self.require_canonical_substring = require_canonical_substring
        self._terms: list[AdminTerm] | None = None
        self._trie_root: _TrieNode | None | bool = False  # False = not built yet

    def detect(self, text: str) -> list[Candidate]:
        terms = self._load_terms()
        if not terms:
            return []

        root = self._get_trie()
        if root is None:
            return []

        term_map: dict[str, AdminTerm] = {term.text: term for term in terms}

        # Scan text once through the trie — O(len(text) * max_term_length)
        raw_matches = _trie_find_all(text, root)
        if not raw_matches:
            return []

        # Sort by (term_text length desc, confidence desc) to preserve
        # the same processing order as the previous term-sorted loop.
        raw_matches.sort(
            key=lambda m: (-len(m[2]), -term_map[m[2]].confidence),
        )

        candidates: list[Candidate] = []
        occupied: list[tuple[int, int, str]] = []
        for index, end, term_key in raw_matches:
            term = term_map[term_key]
            if any(
                used_start == index
                and end <= used_end
                and end < used_end
                and _level_rank(term.level) >= _level_rank(used_level)
                for used_start, used_end, used_level in occupied
            ):
                continue
            if any(
                not (end <= used_start or index >= used_end)
                and not _can_overlap_admin_terms(term, used_level)
                for used_start, used_end, used_level in occupied
            ):
                continue
            if _is_short_local_name(term) and not _has_address_context(text, index, end):
                continue
            if self.require_canonical_substring and term.level in {"city", "county", "county_city"}:
                if term.canonical_name not in text:
                    continue
            occupied.append((index, end, term.level))
            candidates.append(
                Candidate(
                    type=term.entity_type,
                    text=term.text,
                    start=index,
                    end=end,
                    source=self.source,
                    confidence=term.confidence,
                    risk_level="medium",
                    auto_redact=True,
                    reason=f"{self.region_label}地名库：{term.canonical_name}",
                    metadata={
                        "division_code": term.division_code,
                        "level": term.level,
                        "canonical_name": term.canonical_name,
                        "context": text[max(0, index - 40) : min(len(text), end + 40)],
                    },
                )
            )
        return candidates

    def _load_terms(self) -> list[AdminTerm]:
        if self._terms is not None:
            return self._terms
        if not self.db_path.exists():
            self._terms = []
            return self._terms

        terms: dict[str, AdminTerm] = {}
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            with conn:
                for row in conn.execute(
                    """
                    SELECT code, name, full_name, level, entity_type
                    FROM admin_divisions
                    WHERE is_active = 1
                    """
                ):
                    level = row["level"]
                    if self.max_level and _level_rank(level) > _level_rank(self.max_level):
                        continue
                    if _should_add_full_name_term(level, row["name"], row["full_name"]):
                        self._add_term(
                            terms,
                            text=row["full_name"],
                            canonical_name=row["full_name"] or row["name"],
                            division_code=row["code"],
                            level=level,
                            entity_type=row["entity_type"],
                            confidence=0.98,
                        )
                    self._add_term(
                        terms,
                        text=row["name"],
                        canonical_name=row["full_name"] or row["name"],
                        division_code=row["code"],
                        level=level,
                        entity_type=row["entity_type"],
                        confidence=0.92,
                    )
                    for short_alias in _direct_admin_short_aliases(level, row["name"]):
                        self._add_term(
                            terms,
                            text=short_alias,
                            canonical_name=row["full_name"] or row["name"],
                            division_code=row["code"],
                            level=level,
                            entity_type=row["entity_type"],
                            confidence=0.9,
                        )
                for row in conn.execute(
                    """
                    SELECT alias, canonical_name, division_code, confidence
                    FROM admin_aliases
                    """
                ):
                    level, entity_type = self._division_meta(conn, row["division_code"])
                    if self.max_level and _level_rank(level) > _level_rank(self.max_level):
                        continue
                    if not _should_add_alias_term(level, row["alias"], row["canonical_name"]):
                        continue
                    self._add_term(
                        terms,
                        text=row["alias"],
                        canonical_name=row["canonical_name"],
                        division_code=row["division_code"],
                        level=level,
                        entity_type=entity_type,
                        confidence=float(row["confidence"] or 0.9),
                    )
        except sqlite3.Error:
            self._terms = []
            return self._terms
        finally:
            if conn is not None:
                conn.close()

        self._terms = sorted(
            terms.values(),
            key=lambda item: (len(item.text), item.confidence),
            reverse=True,
        )
        return self._terms

    def _get_trie(self) -> _TrieNode | None:
        """Return the cached trie built from loaded terms (built once, reused)."""
        if self._trie_root is False:
            terms = self._load_terms()
            self._trie_root = _build_trie(terms) if terms else None
        assert self._trie_root is not False
        return self._trie_root if self._trie_root is not None else None

    def _add_term(
        self,
        terms: dict[str, AdminTerm],
        text: str | None,
        canonical_name: str,
        division_code: str,
        level: str,
        entity_type: str,
        confidence: float,
    ) -> None:
        value = (text or "").strip()
        if not value or len(value) < 2:
            return
        if _is_generic_grassroots_term(value):
            return
        previous = terms.get(value)
        if previous is not None and previous.confidence >= confidence:
            return
        terms[value] = AdminTerm(
            text=value,
            canonical_name=canonical_name,
            division_code=division_code,
            level=level,
            entity_type=entity_type or _entity_type_for_level(level, value),
            confidence=confidence,
            source=self.source,
        )

    def _division_meta(self, conn: sqlite3.Connection, code: str) -> tuple[str, str]:
        row = conn.execute(
            "SELECT level, entity_type FROM admin_divisions WHERE code = ? LIMIT 1",
            (code,),
        ).fetchone()
        if row is None:
            return "unknown", "location"
        return row["level"], row["entity_type"] or "location"


def _level_rank(level: str) -> int:
    return {
        "province": 1,
        "city": 2,
        "county": 3,
        "county_city": 3,
        "township": 4,
        "village": 5,
        "community": 5,
    }.get(level, 9)


def _entity_type_for_level(level: str, name: str) -> str:
    if level in {"village", "community"} or name.endswith(("村民委员会", "居民委员会", "村委会", "居委会")):
        return "grassroots_org"
    return "location"


def _should_add_full_name_term(level: str, name: str | None, full_name: str | None) -> bool:
    value = (full_name or "").strip()
    if not value:
        return False
    if value == (name or "").strip():
        return True
    return level in {"village", "community", "county", "county_city", "city", "province"}


def _should_add_alias_term(level: str, alias: str | None, canonical_name: str | None) -> bool:
    value = (alias or "").strip()
    if not value:
        return False
    if level in {"village", "community"}:
        return True
    canonical_leaf = (canonical_name or "").strip().split("/")[-1]
    if value == canonical_leaf:
        return True
    return _admin_suffix_count(value) <= 1


def _admin_suffix_count(text: str) -> int:
    return sum(text.count(suffix) for suffix in ("省", "市", "区", "县", "镇", "乡", "街道"))


def _direct_admin_short_aliases(level: str, name: str | None) -> list[str]:
    value = (name or "").strip()
    if level == "province":
        for suffix in ("省", "自治区", "特别行政区"):
            if value.endswith(suffix) and len(value) - len(suffix) >= 2:
                return [value[: -len(suffix)]]
    if level == "city" and value.endswith(("市", "自治州", "地区", "盟")) and len(value) >= 3:
        return [value[:-1]] if value.endswith("市") else []
    if level in {"county", "county_city"} and value.endswith(("区", "县", "市", "旗")) and len(value) >= 3:
        return [value[:-1]]
    return []


def _is_short_local_name(term: AdminTerm) -> bool:
    if term.level in {"county", "county_city"}:
        return not term.text.endswith(("区", "县", "市", "旗")) and len(term.text) <= 3
    if term.level not in {"village", "community"}:
        return False
    if term.text.endswith(("村民委员会", "居民委员会", "村委会", "居委会")):
        return False
    return len(term.text) <= 2


def _is_generic_grassroots_term(value: str) -> bool:
    return value in {
        "省", "市", "区", "县", "镇", "乡", "街道", "社区", "村",
        "市辖区", "村村民委员会", "村村委会", "社区居民委员会", "社区居委会",
    }


def _can_overlap_admin_terms(term: AdminTerm, used_level: str) -> bool:
    direct_levels = {"province", "city", "county", "county_city", "township"}
    return term.level in direct_levels and used_level in direct_levels


def _has_address_context(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 20) : start]
    window = text[max(0, start - 20) : min(len(text), end + 20)]
    if any(marker in before for marker in ADDRESS_CONTEXT_MARKERS):
        return True
    if "镇" in window and "村" in window:
        return True
    if "街道" in window and "社区" in window:
        return True
    return False