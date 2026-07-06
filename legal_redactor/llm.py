from __future__ import annotations

import http.client
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any

from ._logging import get_logger
from .config import LocalLLMConfig




_logger = get_logger("llm")

def get_context_paragraphs(text: str, max_chars: int = 8000) -> str:
    """通过段落/行对齐提取上下文，防止中途断句、断词，自适应处理 OCR 换行。"""
    if len(text) <= max_chars:
        return text

    lines = text.splitlines(keepends=True)
    current_chars = 0
    selected_lines = []

    for line in lines:
        if current_chars + len(line) > max_chars:
            # 只有在已经收集了内容的情况下才提前中断，确保不为空
            if selected_lines:
                break
        selected_lines.append(line)
        current_chars += len(line)

    return "".join(selected_lines)


_ATOMIC_SENTENCE_RE = re.compile(r"[^。！？\n]+(?:[。！？]|(?=\n|$))")
_MAX_EFFECT_SENTENCE_BATCH_SIZE = 8
_BALANCED_SENTENCE_BATCH_SIZE = 4
_MAX_SINGLE_CALL_WINDOWS = 8
_MAX_EFFECT_CHUNK_CHARS = 1000
_MAX_EFFECT_TARGET_WINDOWS = 48
_BALANCED_TARGET_WINDOWS = 24
_SENTENCE_FEW_SHOT_EXAMPLES = 3
_PARALLEL_BATCH_WORKERS = 1
_BATCH_ATTEMPTS = 1
_SENTENCE_EXTRACTION_MAX_TOKENS = 1536
_SENTENCE_EXTRACTION_MIN_TOKENS = 768
_SENTENCE_EXTRACTION_BASE_TOKENS = 384
_SENTENCE_EXTRACTION_TOKENS_PER_WINDOW = 128
_AUDIT_MAX_TOKENS = 4096
_CONTRACT_NOISE_RE = re.compile(r"合同[一二三四五六七八九十百零\d]+")
_FALSE_ORG_CLAUSE_RE = re.compile(r"否认其与[^。！？\n，,、；;]{2,24}系关联公司")
_ORG_ACTION_CLAUSE_RE = re.compile(
    r"(?:否认|称|辩称|主张|认为|发送|出具|提交|告知|通知|转账|汇款|付款|支付|联系)"
    r"[^。！？\n，,、；;]{0,24}(?:公司|集团|银行|分行|支行|律所)$"
)
_ORG_RELATION_CLAUSE_RE = re.compile(
    r"^[\u4e00-\u9fa5]{2,6}(?:系|为|以|代表)[^。！？\n，,、；;]{2,16}(?:公司|集团|银行|分行|支行|律所)$"
)
_INVALID_COMPANY_VARIANT_RE = re.compile(
    r"(?:"
    r"^[我你他她其该此甲乙丙丁戊己庚辛壬癸][与和及向对给由从被把将]"
    r"|\d{4}年"
    r"|以下简称|下称|简称|原名称|曾用名|否认其"
    r")"
)
_CLAUSE_WRAPPED_ORG_RE = re.compile(
    r"(?:一审法院|二审法院|人民法院|上诉人|被上诉人|案外人|原告|被告|第三人|"
    r"答辩人|驳回|起诉|诉请|未厘清|仍然认|如果其|并未|代表|提交|告知|申请|"
    r"发送|原名|被指|认为|主张|银行)"
)
_COMPANY_ROLE_PREFIX_RE = re.compile(
    r"^(?:再审申请人|申请执行人|被申请人|被执行人|被上诉人|上诉人|申请人|"
    r"被告|原告|第三人|案外人|答辩人)[一二三四五六七八九十\d]*[：:、，,\s]*"
)
_COMPANY_LEGAL_SUFFIXES = (
    "有限责任公司",
    "股份有限公司",
    "集团有限公司",
    "有限公司",
    "公司",
    "集团",
)
_SHORT_ORG_TAIL_SEPARATORS = ("发送", "通知", "告知", "提交", "出具", "系", "为", "以", "代表", "转账至", "汇款至", "支付至")
_BANK_OR_FIRM_SUFFIXES = ("银行", "分行", "支行", "律所")
_PROJECT_SUFFIXES = (
    "风电场",
    "小区",
    "花园",
    "华府",
    "澜庭",
    "蓝庭",
    "公寓",
    "广场",
    "大厦",
    "产业园",
    "商业综合体",
    "小镇",
    "标段",
    "项目",
    "工程",
)
_PROJECT_DOCUMENT_NOISE_RE = re.compile(
    r"(?:合同|清单|报价单|报价|总款|价款|款项|费用|辅料费|采购单|发票|收据)"
)
_GENERIC_PROJECT_RE = re.compile(
    r"^(?:办公大厅|大厅|会议室|机房|楼面|整体|全部|一期|二期|三期|"
    r"[一二三四五六七八九十\d]+期)?"
    r"(?:整体)?(?:装饰|装修|施工|承包|安装|采购|开孔|空调|商厨|改造|维修|"
    r"装潢|水电|消防|弱电|土建|机电|幕墙|门窗|楼面|大厅|会议室|机房)*"
    r"(?:工程|施工|项目)$"
)
_PARTY_OR_PERSON_ROLE_RE = re.compile(
    r"(?:"
    r"再审申请人|申请执行人|被申请人|被执行人|被上诉人|上诉人|申请人|"
    r"原告|被告|第三人|案外人|答辩人|法定代表人|负责人|经营者|"
    r"委托诉讼代理人|诉讼代理人|代理人|联系人|经办人|证人"
    r")"
)
_ORG_TRIGGER_RE = re.compile(
    r"(?:"
    r"有限责任公司|股份有限公司|集团有限公司|有限公司|"
    r"律师事务所|会计师事务所|保险公司|商业银行|农村商业银行|"
    r"公司|集团|银行|分行|支行|信用社|合作社|商行|经营部|"
    r"医院|学校|幼儿园|委员会|村委会|居委会|公安局|税务局|管理局|法院|检察院"
    r")"
)
_ALIAS_RELATION_TRIGGER_RE = re.compile(
    r"(?:以下简称|下称|简称|简称为|原名称|原名|曾用名|后更名为|更名为|变更为|现名称|现名)"
)
_LOCATION_PROJECT_TRIGGER_RE = re.compile(
    r"(?:"
    r"[\u4e00-\u9fa5]{2,20}(?:省|市|区|县|镇|乡|村|街道|社区|小区|花园|华府|澜庭|蓝庭|公寓|广场|大厦|产业园|小镇)"
    r"|[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30}(?:风电场|商业综合体|标段|项目|工程)"
    r")"
)
_PERSON_LIST_TRIGGER_RE = re.compile(
    r"[\u4e00-\u9fa5·]{2,4}(?:、|与|和|及)[\u4e00-\u9fa5·]{2,4}"
)
_LOW_VALUE_PROCEDURE_RE = re.compile(
    r"(?:"
    r"本院认为|审理终结|依法组成合议庭|公开开庭|缺席审理|判决如下|裁定如下|"
    r"驳回|受理费|公告费|保全费|鉴定费|利息|违约金|合同款|工程款|"
    r"证据[一二三四五六七八九十\d]*|发票|收据|转账记录|银行流水|付款凭证"
    r")"
)


def _atomic_sentence_spans(text: str) -> list[tuple[str, int, int]]:
    """Split only on sentence-ending punctuation; keep commas inside spans."""
    spans: list[tuple[str, int, int]] = []
    for match in _ATOMIC_SENTENCE_RE.finditer(text):
        sentence = match.group(0).strip()
        if sentence:
            spans.append((sentence, match.start(), match.end()))
    if spans:
        return spans
    stripped = text.strip()
    return [(stripped, 0, len(stripped))] if stripped else []


def _merge_sentence_chunks(
    spans: list[tuple[str, int, int]],
    *,
    chunk_chars: int,
) -> list[tuple[str, int, int]]:
    if not spans:
        return []
    merged: list[tuple[str, int, int]] = []
    chunk_parts: list[str] = []
    chunk_start = spans[0][1]
    chunk_end = spans[0][2]
    for sentence, start, end in spans:
        projected_len = chunk_end - chunk_start + len(sentence)
        if chunk_parts and projected_len > chunk_chars:
            merged.append(("".join(chunk_parts), chunk_start, chunk_end))
            chunk_parts = [sentence]
            chunk_start = start
            chunk_end = end
            continue
        if not chunk_parts:
            chunk_start = start
        chunk_parts.append(sentence)
        chunk_end = end
    if chunk_parts:
        merged.append(("".join(chunk_parts), chunk_start, chunk_end))
    return merged


def build_sentence_windows(
    text: str,
    max_chars: int | None = 6000,
    max_windows: int | None = 40,
    *,
    chunk_chars: int = 800,
) -> list[dict[str, str]]:
    """Build LLM windows: one target sentence per window, context only in previous/next."""
    atomic_spans = _atomic_sentence_spans(text)
    if max_chars is not None:
        trimmed: list[tuple[str, int, int]] = []
        for sentence, start, end in atomic_spans:
            trimmed.append((sentence, start, end))
            if end >= max_chars:
                break
        atomic_spans = trimmed
    _ = chunk_chars  # Kept for backward-compatible callers; windows remain sentence-level.
    spans = atomic_spans
    if max_windows is not None:
        spans = spans[:max_windows]

    windows: list[dict[str, str]] = []
    for index, (sentence, start, end) in enumerate(spans):
        previous = spans[index - 1][0] if index > 0 else ""
        following = spans[index + 1][0] if index + 1 < len(spans) else ""
        windows.append(
            {
                "id": f"s{index + 1}",
                "previous": previous,
                "target": sentence,
                "next": following,
                "start": str(start),
                "end": str(end),
            }
        )
    return windows


def _target_sentence_score(sentence: str) -> int:
    text = sentence.strip()
    if not text:
        return 0

    score = 0
    if _ALIAS_RELATION_TRIGGER_RE.search(text):
        score += 8
    if _PARTY_OR_PERSON_ROLE_RE.search(text):
        score += 7
    if _ORG_TRIGGER_RE.search(text):
        score += 6
    if _PERSON_LIST_TRIGGER_RE.search(text):
        score += 4
    if _LOCATION_PROJECT_TRIGGER_RE.search(text):
        score += 3
    if _LOW_VALUE_PROCEDURE_RE.search(text) and score < 6:
        return 0
    return max(score, 0)


def select_entity_target_windows(
    windows: list[dict[str, str]],
    *,
    mode: str = "max-effect",
    max_windows: int | None = None,
) -> list[dict[str, str]]:
    """Pick complete sentence windows for LLM extraction; never slice inside a sentence."""
    if not windows:
        return []
    limit = max_windows
    if limit is None:
        limit = _BALANCED_TARGET_WINDOWS if mode == "balanced" else _MAX_EFFECT_TARGET_WINDOWS

    scored: list[tuple[int, int, dict[str, str]]] = []
    for index, window in enumerate(windows):
        score = _target_sentence_score(window.get("target", ""))
        if score <= 0:
            continue
        item = dict(window)
        item["_target_score"] = str(score)
        scored.append((score, index, item))

    if not scored:
        return []
    if limit is not None and len(scored) > limit:
        scored = sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]
    return [item for _, _, item in sorted(scored, key=lambda item: item[1])]


def _sentence_extraction_batch_size(window_count: int, *, mode: str) -> int:
    if window_count <= 0:
        return 1
    if mode == "max-effect" and window_count <= _MAX_SINGLE_CALL_WINDOWS:
        return window_count
    if mode == "balanced":
        return _BALANCED_SENTENCE_BATCH_SIZE
    return min(_MAX_EFFECT_SENTENCE_BATCH_SIZE, window_count)


def _sentence_extraction_batches(windows: list[dict[str, str]], *, mode: str) -> list[list[dict[str, str]]]:
    if not windows:
        return []
    batch_size = _sentence_extraction_batch_size(len(windows), mode=mode)
    return [windows[index : index + batch_size] for index in range(0, len(windows), batch_size)]


def _sentence_extraction_max_tokens(window_count: int) -> int:
    budget = _SENTENCE_EXTRACTION_BASE_TOKENS + window_count * _SENTENCE_EXTRACTION_TOKENS_PER_WINDOW
    return max(_SENTENCE_EXTRACTION_MIN_TOKENS, min(_SENTENCE_EXTRACTION_MAX_TOKENS, budget))


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _item_texts(item: dict[str, Any], *keys: str) -> list[str]:
    texts: list[str] = []
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            texts.append(value.strip())
    variants = item.get("variants")
    if isinstance(variants, list):
        for value in variants:
            if isinstance(value, str) and value.strip():
                texts.append(value.strip())
    return _dedupe_preserve_order(texts)


def _prune_substring_texts(texts: list[str]) -> list[str]:
    ordered = sorted(_dedupe_preserve_order(texts), key=len, reverse=True)
    kept: list[str] = []
    for text in ordered:
        if any(text != longer and text in longer for longer in kept):
            continue
        kept.append(text)
    return kept


def _orchestrate_locations(items: list[Any]) -> list[dict[str, Any]]:
    records = [item for item in items if isinstance(item, dict)]
    by_full: dict[str, dict[str, Any]] = {}
    for item in records:
        full = item.get("full") or item.get("name") or item.get("text")
        if not isinstance(full, str) or not full.strip():
            continue
        full = full.strip()
        core = item.get("core")
        if not isinstance(core, str) or not core.strip():
            core = full
        previous = by_full.get(full)
        if previous is None or len(str(core)) > len(str(previous.get("core", ""))):
            by_full[full] = {
                "window": item.get("window"),
                "full": full,
                "core": core.strip(),
            }
    return list(by_full.values())


def _orchestrate_companies(items: list[Any]) -> list[dict[str, Any]]:
    records = [item for item in items if isinstance(item, dict)]
    if not records:
        return []

    texts_by_idx: list[list[str]] = []
    for record in records:
        values: list[str] = []
        for value in _item_texts(record, "name", "full", "brand"):
            values.extend(_company_variant_texts(value))
        texts_by_idx.append(_dedupe_preserve_order(values))
    parent = list(range(len(records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_left] = root_right

    for left in range(len(records)):
        left_texts = set(texts_by_idx[left])
        for right in range(left + 1, len(records)):
            right_texts = set(texts_by_idx[right])
            if left_texts & right_texts:
                union(left, right)
                continue
            linked = False
            for left_name in left_texts:
                for right_name in right_texts:
                    if _should_link_company_names(left_name, right_name):
                        union(left, right)
                        linked = True
                        break
                if linked:
                    break

    groups: dict[int, list[int]] = {}
    for index in range(len(records)):
        groups.setdefault(find(index), []).append(index)

    merged: list[dict[str, Any]] = []
    for group_indexes in groups.values():
        combined_texts: list[str] = []
        window: str | None = None
        for index in group_indexes:
            combined_texts.extend(texts_by_idx[index])
            candidate_window = records[index].get("window")
            if isinstance(candidate_window, str) and candidate_window:
                window = window or candidate_window
        variants = _dedupe_preserve_order(combined_texts)
        if not variants:
            continue
        primary = max(variants, key=len)
        merged.append({"window": window, "name": primary, "variants": variants})
    return merged


def _orchestrate_named_items(items: list[Any], name_key: str) -> list[dict[str, Any]]:
    records = [item for item in items if isinstance(item, dict)]
    by_name: dict[str, dict[str, Any]] = {}
    for item in records:
        name = item.get(name_key) or item.get("text")
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        previous = by_name.get(name)
        if previous is None:
            by_name[name] = dict(item)
            by_name[name][name_key] = name
            continue
        if len(name) >= len(str(previous.get(name_key, ""))):
            merged = dict(previous)
            merged.update(item)
            merged[name_key] = name
            by_name[name] = merged

    kept: list[dict[str, Any]] = []
    for name in sorted(by_name.keys(), key=len, reverse=True):
        if any(name != longer and name in longer for longer in by_name if longer != name):
            continue
        kept.append(by_name[name])
    return kept


def _analysis_entity_texts(analysis: dict[str, Any]) -> set[str]:
    texts: set[str] = set()
    for key, fields in (
        ("locations", ("full", "name", "text", "core")),
        ("companies", ("name", "full", "brand", "text")),
        ("persons", ("name", "text")),
        ("projects", ("name", "full", "text")),
    ):
        items = analysis.get(key, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for field in fields:
                value = item.get(field)
                if isinstance(value, str) and value.strip():
                    texts.add(value.strip())
            variants = item.get("variants")
            if isinstance(variants, list):
                for value in variants:
                    if isinstance(value, str) and value.strip():
                        texts.add(value.strip())
    return texts


def is_noise_entity_text(text: str) -> bool:
    return _is_noise_entity_text(text)


def _is_clause_wrapped_org(text: str) -> bool:
    stripped = text.strip()
    if not any(
        stripped.endswith(suffix)
        for suffix in (*_COMPANY_LEGAL_SUFFIXES, "银行")
    ):
        return False
    if (
        "代表" in stripped
        and not stripped.startswith("法定代表人")
        and not stripped.startswith("诉讼代表人")
    ):
        return True
    if len(stripped) <= 12:
        return False
    return bool(_CLAUSE_WRAPPED_ORG_RE.search(stripped))


def _is_noise_entity_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if _is_clause_wrapped_org(stripped):
        return True
    if _ORG_ACTION_CLAUSE_RE.search(stripped):
        return True
    if _ORG_RELATION_CLAUSE_RE.search(stripped):
        return True
    if _CONTRACT_NOISE_RE.fullmatch(stripped):
        return True
    if _CONTRACT_NOISE_RE.search(stripped):
        remainder = _CONTRACT_NOISE_RE.sub("", stripped)
        remainder = re.sub(r"[\s，,、；;：:的之与和及]", "", remainder)
        if len(remainder) <= 4:
            return True
    if _FALSE_ORG_CLAUSE_RE.fullmatch(stripped):
        return True
    return False


def is_noise_project_text(text: str) -> bool:
    stripped = text.strip(" ：:，,。；;\n\t")
    if not stripped:
        return True
    if len(stripped) < 3:
        return True
    if _PROJECT_DOCUMENT_NOISE_RE.search(stripped):
        return True
    if not stripped.endswith(_PROJECT_SUFFIXES):
        return True
    if stripped in {"建设工程", "工程", "项目", "施工工程", "装修工程", "装饰工程", "安装工程", "整体工程"}:
        return True
    if _GENERIC_PROJECT_RE.fullmatch(stripped):
        return True
    return False


def _company_match_stem(text: str) -> str:
    for suffix in _COMPANY_LEGAL_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def _core_matches_org_name(core: str, org_name: str) -> bool:
    stem = _company_match_stem(core)
    return len(stem) >= 2 and stem in org_name


def _is_valid_company_variant(text: str) -> bool:
    stripped = text.strip()
    if not stripped or _is_noise_entity_text(stripped):
        return False
    if _COMPANY_ROLE_PREFIX_RE.match(stripped):
        return False
    if _INVALID_COMPANY_VARIANT_RE.search(stripped):
        return False

    from .lexicon import ORG_FULL_RE

    match = ORG_FULL_RE.search(stripped)
    if match and match.group(0) == stripped:
        return _is_valid_org_capture(stripped)

    if any(stripped.endswith(suffix) for suffix in _COMPANY_LEGAL_SUFFIXES):
        return len(stripped) <= 10
    if any(stripped.endswith(suffix) for suffix in _BANK_OR_FIRM_SUFFIXES):
        return len(stripped) <= 12
    return 2 <= len(stripped) <= 8


def _salvage_company_tail_from_clause(text: str) -> str:
    stripped = text.strip()
    for separator in _SHORT_ORG_TAIL_SEPARATORS:
        if separator not in stripped:
            continue
        tail = stripped.rsplit(separator, 1)[1].strip(" ：:，,。；;、\n\t")
        if tail and _is_valid_company_variant(tail):
            return tail
    return ""


def _company_variant_texts(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    variants: list[str] = []
    candidates = _dedupe_preserve_order(
        [
            stripped,
            _COMPANY_ROLE_PREFIX_RE.sub("", stripped).strip(),
            _salvage_company_tail_from_clause(stripped),
        ]
    )

    from .lexicon import ORG_FULL_RE

    for candidate in candidates:
        if _is_valid_company_variant(candidate):
            variants.append(candidate)
        for match in ORG_FULL_RE.finditer(candidate):
            value = match.group(0).strip()
            if value and _is_valid_company_variant(value):
                variants.append(value)
    return _dedupe_preserve_order(variants)


def _should_link_company_names(left: str, right: str) -> bool:
    if left == right:
        return True
    short, long = (left, right) if len(left) <= len(right) else (right, left)
    if short not in long:
        return False
    if not _is_valid_company_variant(short) or not _is_valid_company_variant(long):
        return False
    return len(long) - len(short) <= 12


def _regex_noise_rejects(source_text: str) -> list[str]:
    if not source_text:
        return []
    rejects: list[str] = []
    for pattern in (_CONTRACT_NOISE_RE, _FALSE_ORG_CLAUSE_RE):
        for match in pattern.finditer(source_text):
            value = match.group(0).strip()
            if value and value not in rejects:
                rejects.append(value)
    return rejects


def _filter_noise_company_records(companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in companies:
        variants: list[str] = []
        for value in _item_texts(item, "name", "full", "brand"):
            variants.extend(_company_variant_texts(value))
        variants = _dedupe_preserve_order(variants)
        if not variants:
            continue
        suffixed = [
            value
            for value in variants
            if value.endswith(("有限责任公司", "股份有限公司", "集团有限公司", "有限公司", "公司", "集团"))
        ]
        primary = max(suffixed or variants, key=len)
        filtered.append(
            {
                "window": item.get("window"),
                "name": primary,
                "variants": variants,
            }
        )
    return filtered


def _filter_noise_named_items(items: list[dict[str, Any]], name_key: str) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get(name_key) or item.get("text")
        if not isinstance(name, str) or _is_noise_entity_text(name):
            continue
        cleaned = dict(item)
        cleaned[name_key] = name.strip()
        filtered.append(cleaned)
    return filtered


def _filter_noise_project_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("text")
        if not isinstance(name, str) or is_noise_project_text(name):
            continue
        cleaned = dict(item)
        cleaned["name"] = name.strip()
        filtered.append(cleaned)
    return filtered


def _company_match_cores(names: list[str]) -> list[str]:
    cores: list[str] = []
    for name in names:
        if len(name) < 2:
            continue
        cores.append(name)
        for suffix in _COMPANY_LEGAL_SUFFIXES:
            if name.endswith(suffix) and len(name) > len(suffix):
                core = name[: -len(suffix)]
                if len(core) >= 2:
                    cores.append(core)
                break
    return _dedupe_preserve_order(cores)


def _is_valid_org_capture(name: str) -> bool:
    if any(
        noise in name
        for noise in ("以下简称", "下称", "简称", "原名称", "曾用名", "否认其", "合同")
    ):
        return False
    return len(name) >= 4


def _expand_companies_from_text(source_text: str, companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not source_text or not companies:
        return companies

    from .lexicon import ORG_FULL_RE

    org_names = _dedupe_preserve_order(
        match.group(0).strip()
        for match in ORG_FULL_RE.finditer(source_text)
        if match.group(0).strip() and _is_valid_org_capture(match.group(0).strip())
    )
    expanded: list[dict[str, Any]] = []
    for item in companies:
        anchors: list[str] = []
        for value in _item_texts(item, "name", "full", "brand"):
            anchors.extend(_company_variant_texts(value))
        anchors = _dedupe_preserve_order(anchors)
        if not anchors:
            expanded.append(item)
            continue
        cores = _company_match_cores(anchors)
        matched_orgs: list[str] = []
        for org_name in org_names:
            if any(_core_matches_org_name(core, org_name) for core in cores):
                matched_orgs.append(org_name)
        variants = _dedupe_preserve_order([*anchors, *matched_orgs])
        expanded.append(
            {
                "window": item.get("window"),
                "name": max(variants, key=len),
                "variants": variants,
            }
        )
    return expanded


def _orchestrate_reject(analysis: dict[str, Any], source_text: str = "") -> list[str]:
    rejects: list[str] = []
    for value in [*analysis.get("reject", []), *_regex_noise_rejects(source_text)]:
        if isinstance(value, str) and value.strip() and value not in rejects:
            rejects.append(value.strip())

    entity_texts = _analysis_entity_texts(analysis)
    rejects = [
        value
        for value in rejects
        if value not in entity_texts or _is_noise_entity_text(value)
    ]
    return _prune_substring_texts(rejects)


def orchestrate_sentence_extractions(
    analysis: dict[str, Any],
    *,
    source_text: str = "",
) -> dict[str, Any]:
    """Merge batched LLM entity lists into one deduplicated extraction."""
    companies = _filter_noise_company_records(
        _expand_companies_from_text(
            source_text,
            _orchestrate_companies(analysis.get("companies", [])),
        )
    )
    persons = _filter_noise_named_items(
        _orchestrate_named_items(analysis.get("persons", []), "name"),
        "name",
    )
    projects = _filter_noise_project_items(_orchestrate_named_items(analysis.get("projects", []), "name"))
    reject_basis = {
        **analysis,
        "companies": companies,
        "persons": persons,
        "projects": projects,
    }
    orchestrated = {
        "locations": _orchestrate_locations(analysis.get("locations", [])),
        "companies": companies,
        "persons": persons,
        "projects": projects,
        "reject": _orchestrate_reject(reject_basis, source_text),
        "calibrate": {
            key: value
            for key, value in (analysis.get("calibrate", {}) or {}).items()
            if isinstance(key, str) and isinstance(value, str)
        },
    }
    for meta_key in (
        "_sentence_windows",
        "_batch_count",
        "_batch_failures",
        "_total_sentence_windows",
        "_target_sentence_count",
        "_no_target_windows",
    ):
        if meta_key in analysis:
            orchestrated[meta_key] = analysis[meta_key]
    return orchestrated


@dataclass
class LegalEntityAuditor:
    config: LocalLLMConfig

    def audit_and_verify(self, text: str, candidates: list[dict], enable_samples: bool = True) -> dict[str, Any]:
        """合并审计提取与疑似候选词验证，单次调用 LLM。

        Args:
            text: 原文
            candidates: 待验证的正则/启发式候选列表，每项含 {"text", "type", "context"}
            enable_samples: 是否注入历史样本作为 few-shot
        """
        if not self.config.enabled:
            return {"locations": [], "companies": [], "persons": [], "reject": []}

        # Candidate review only needs nearby evidence, not a full-document extraction.
        audit_text = get_context_paragraphs(text, max_chars=4000)
        prompt = self._build_merged_prompt(audit_text, candidates, enable_samples=enable_samples)

        try:
            payload = self._call_local_model(prompt)
            return self._normalize_candidate_review_payload(payload, candidates)
        except Exception as exc:
            import sys
            _logger.warning("语义审计与验证联合调用失败：%s", exc)
            # 联合调用失败时，返回空提取，并采用 fail-open（空拒绝列表）以保留所有规则候选
            return {"locations": [], "companies": [], "persons": [], "reject": [], "error": str(exc)}

    def extract_sentence_entities(self, text: str, enable_samples: bool = True) -> dict[str, Any]:
        """Extract entities from sentence windows; context is previous/next sentence only."""
        empty = {
            "locations": [],
            "companies": [],
            "persons": [],
            "projects": [],
            "reject": [],
            "calibrate": {},
        }
        if not self.config.enabled:
            return empty

        if self.config.mode == "balanced":
            all_windows = build_sentence_windows(text, max_chars=4500, max_windows=80, chunk_chars=650)
        else:
            all_windows = build_sentence_windows(
                text,
                max_chars=None,
                max_windows=None,
                chunk_chars=_MAX_EFFECT_CHUNK_CHARS,
            )
        windows = select_entity_target_windows(all_windows, mode=self.config.mode)
        batches = _sentence_extraction_batches(windows, mode=self.config.mode)
        if not batches:
            return {
                **empty,
                "_sentence_windows": [],
                "_total_sentence_windows": len(all_windows),
                "_target_sentence_count": 0,
                "_no_target_windows": True,
            }

        import sys

        _logger.info(
            "整句语义识别：总计 %d 句，筛选 %d 句，%d 批，%d 路并发。",
            len(all_windows), len(windows), len(batches),
            min(_PARALLEL_BATCH_WORKERS, len(batches)),
        )
        merged, batch_count, batch_failures = self._extract_sentence_batches(
            batches,
            enable_samples=enable_samples,
        )

        if batch_count == 0:
            detail = "; ".join(batch_failures) or "no batches succeeded"
            _logger.warning("整句语义识别全部批次失败：%s", detail)
            return {**empty, "error": detail}
        if batch_failures:
            detail = "; ".join(batch_failures)
            _logger.warning("整句语义识别存在失败批次，已保留成功批次结果：%s", detail)
            merged["_batch_failures"] = batch_failures

        merged["_sentence_windows"] = windows
        merged["_total_sentence_windows"] = len(all_windows)
        merged["_target_sentence_count"] = len(windows)
        merged["_batch_count"] = batch_count
        return orchestrate_sentence_extractions(merged, source_text=text)

    def _extract_sentence_batches(
        self,
        batches: list[list[dict[str, str]]],
        *,
        enable_samples: bool,
    ) -> tuple[dict[str, Any], int, list[str]]:
        empty = {
            "locations": [],
            "companies": [],
            "persons": [],
            "projects": [],
            "reject": [],
            "calibrate": {},
        }
        total_batches = len(batches)
        if total_batches == 1:
            payload, failures = self._extract_windows_batch(
                batches[0],
                enable_samples=enable_samples,
                label="batch 1/1",
            )
            if payload is None:
                return empty, 0, failures
            return payload, 1, failures

        merged = empty.copy()
        batch_count = 0
        batch_failures: list[str] = []

        def run_batch(index: int) -> tuple[int, dict[str, Any] | None, list[str]]:
            payload, failures = self._extract_windows_batch(
                batches[index],
                enable_samples=enable_samples and index == 0,
                label=f"batch {index + 1}/{total_batches}",
            )
            return index, payload, failures

        workers = min(_PARALLEL_BATCH_WORKERS, total_batches)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(run_batch, range(total_batches)))

        for _, payload, failures in sorted(results, key=lambda item: item[0]):
            batch_failures.extend(failures)
            if payload is None:
                continue
            merged = self._merge_sentence_extractions(merged, payload)
            batch_count += 1
        return merged, batch_count, batch_failures

    def _extract_windows_batch(
        self,
        batch: list[dict[str, str]],
        *,
        enable_samples: bool,
        label: str,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        failures: list[str] = []
        prompt = self._build_sentence_extraction_prompt(batch, enable_samples=enable_samples)
        max_tokens = _sentence_extraction_max_tokens(len(batch))
        payload: dict[str, Any] = {}
        for attempt in range(_BATCH_ATTEMPTS):
            started_at = time.monotonic()
            try:
                payload = self._call_local_model(
                    prompt,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                payload = {"error": str(exc)}
                if attempt + 1 < _BATCH_ATTEMPTS:
                    continue
                break
            if not payload.get("error"):
                elapsed = time.monotonic() - started_at
                _logger.info(
                    "%s 完成：%d 句，max_tokens=%d，用时 %.1fs。",
                    label, len(batch), max_tokens, elapsed,
                )
                return payload, failures
            if attempt + 1 < _BATCH_ATTEMPTS:
                _logger.warning("%s JSON 解析失败，重试中…", label)
        if not payload.get("error"):
            return payload, failures
        failures.append(f"{label}: {payload.get('error', 'unknown error')}")
        _logger.warning(
            "%s JSON 解析失败，跳过该批次：%s", label, payload.get("error"),
        )
        return None, failures

    @staticmethod
    def _merge_sentence_extractions(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        merged = {
            "locations": [*left.get("locations", []), *right.get("locations", [])],
            "companies": [*left.get("companies", []), *right.get("companies", [])],
            "persons": [*left.get("persons", []), *right.get("persons", [])],
            "projects": [*left.get("projects", []), *right.get("projects", [])],
            "reject": [],
            "calibrate": dict(left.get("calibrate", {})),
        }
        reject: list[str] = []
        for value in [*left.get("reject", []), *right.get("reject", [])]:
            if isinstance(value, str) and value and value not in reject:
                reject.append(value)
        merged["reject"] = reject
        calibrate = merged["calibrate"]
        if isinstance(calibrate, dict):
            for key, value in right.get("calibrate", {}).items():
                if isinstance(key, str) and isinstance(value, str):
                    calibrate[key] = value
        return merged

    def _call_local_model(self, prompt: str, *, max_tokens: int = _AUDIT_MAX_TOKENS) -> dict[str, Any]:
        if self.config.backend == "mlx":
            return self._call_mlx(prompt, max_tokens=max_tokens)
        return self._call_ollama(prompt)

    def _call_mlx(self, prompt: str, *, max_tokens: int = _AUDIT_MAX_TOKENS) -> dict[str, Any]:
        return self._call_mlx_model(prompt, self.config.model, max_tokens=max_tokens)

    def _call_mlx_model(self, prompt: str, model: str, *, max_tokens: int = _AUDIT_MAX_TOKENS) -> dict[str, Any]:
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "temperature": self.config.temperature,
                "max_tokens": max_tokens,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        conn = http.client.HTTPConnection(
            self.config.mlx_host,
            self.config.mlx_port,
            timeout=self.config.timeout_seconds,
        )
        try:
            conn.request(
                "POST",
                "/v1/chat/completions",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            data = response.read().decode("utf-8", errors="replace")
        finally:
            conn.close()

        if response.status >= 400:
            raise RuntimeError(f"MLX HTTP {response.status}: {data[:200]}")

        raw = json.loads(data)
        choices = raw.get("choices", [])
        if not choices:
            raise RuntimeError(f"MLX empty response: {data[:200]}")
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        response_text = message.get("content", "") if isinstance(message, dict) else ""
        return self._parse_json(response_text)

    def _call_ollama(self, prompt: str) -> dict[str, Any]:
        models = []
        if self.config.model:
            models.append(self.config.model)
        for m in self.config.fallback_models:
            if m not in models:
                models.append(m)

        errors = []
        for model in models:
            try:
                return self._call_ollama_model(prompt, model)
            except Exception as e:
                errors.append(f"{model}: {e}")
        raise RuntimeError("LLM 调用失败: " + "; ".join(errors))

    def _call_ollama_model(self, prompt: str, model: str) -> dict[str, Any]:
        body = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "think": False,
                "keep_alive": "1m",
                "options": {
                    "temperature": self.config.temperature,
                    "num_ctx": self.config.context_window,
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")
        conn = http.client.HTTPConnection(
            self.config.ollama_host,
            self.config.ollama_port,
            timeout=self.config.timeout_seconds,
        )
        try:
            conn.request(
                "POST",
                "/api/generate",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            data = response.read().decode("utf-8", errors="replace")
        finally:
            conn.close()

        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status}: {data[:200]}")

        raw = json.loads(data)
        response_text = raw.get("response", "") or raw.get("thinking", "")
        return self._parse_json(response_text)

    @staticmethod
    def _repair_json_text(value: str) -> str:
        trimmed = value.rstrip()
        while trimmed.endswith(","):
            trimmed = trimmed[:-1].rstrip()
        stack: list[str] = []
        in_string = False
        escape = False
        for char in trimmed:
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                stack.append("}")
            elif char == "[":
                stack.append("]")
            elif char in "}]" and stack and stack[-1] == char:
                stack.pop()
        return trimmed + "".join(reversed(stack))

    def _parse_json(self, value: str) -> dict[str, Any]:
        value = value.strip()
        if value.startswith("```"):
            value = value.strip("`")
            value = value.replace("json\n", "", 1).replace("JSON\n", "", 1)
        start = value.find("{")
        fragment = value[start:] if start >= 0 else value
        end = fragment.rfind("}")
        candidates: list[str] = []
        if end >= 0:
            candidates.append(fragment[: end + 1])
        repaired = self._repair_json_text(fragment)
        if repaired not in candidates:
            candidates.append(repaired)
        data: dict[str, Any] | None = None
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                data = parsed
                break
        try:
            if data is None:
                raise JSONDecodeError("JSON decode failed", value, 0)
            if not isinstance(data, dict):
                data = {}
            for key in ("locations", "companies", "persons", "projects"):
                items = data.get(key, [])
                data[key] = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
            reject = data.get("reject", [])
            data["reject"] = self._string_list(reject, include_numbers=False) if isinstance(reject, list) else []
            reject_ids = data.get("reject_ids", [])
            data["reject_ids"] = self._string_list(reject_ids, include_numbers=True) if isinstance(reject_ids, list) else []
            calibrate = data.get("calibrate", {})
            data["calibrate"] = {
                key: item
                for key, item in calibrate.items()
                if isinstance(key, str) and isinstance(item, str)
            } if isinstance(calibrate, dict) else {}
            calibrate_ids = data.get("calibrate_ids", {})
            data["calibrate_ids"] = {
                str(key): item
                for key, item in calibrate_ids.items()
                if isinstance(item, str)
            } if isinstance(calibrate_ids, dict) else {}
            return data
        except JSONDecodeError:
            return {"locations": [], "companies": [], "persons": [], "projects": [], "reject": [], "calibrate": {}, "error": "JSON decode failed"}

    @staticmethod
    def _string_list(items: list[Any], *, include_numbers: bool) -> list[str]:
        values: list[str] = []
        for item in items:
            if isinstance(item, str):
                values.append(item)
            elif include_numbers and isinstance(item, (int, float)):
                values.append(str(int(item)) if isinstance(item, float) and item.is_integer() else str(item))
            elif isinstance(item, dict):
                for key in ("candidate", "text", "name", "id"):
                    value = item.get(key)
                    if isinstance(value, str):
                        values.append(value)
                        break
                    if include_numbers and isinstance(value, (int, float)):
                        values.append(str(int(value)) if isinstance(value, float) and value.is_integer() else str(value))
                        break
        return values

    def _normalize_candidate_review_payload(self, payload: dict[str, Any], candidates: list[dict]) -> dict[str, Any]:
        """Map ID-based candidate review output back to the existing text-based contract."""
        id_to_text: dict[str, str] = {}
        candidate_texts: set[str] = set()
        for index, candidate in enumerate(candidates, 1):
            text = candidate.get("text")
            if not isinstance(text, str) or not text:
                continue
            candidate_texts.add(text)
            id_to_text[str(candidate.get("id") or index)] = text

        reject: list[str] = []
        for item in payload.get("reject", []):
            if item in candidate_texts and item not in reject:
                reject.append(item)
            elif item in id_to_text and id_to_text[item] not in reject:
                reject.append(id_to_text[item])
        for item in payload.get("reject_ids", []):
            text = id_to_text.get(str(item))
            if text and text not in reject:
                reject.append(text)

        calibrate: dict[str, str] = {}
        raw_calibrate = payload.get("calibrate", {})
        if isinstance(raw_calibrate, dict):
            for key, value in raw_calibrate.items():
                if not isinstance(value, str):
                    continue
                text_key = id_to_text.get(str(key), key)
                if isinstance(text_key, str) and text_key:
                    calibrate[text_key] = value
        raw_calibrate_ids = payload.get("calibrate_ids", {})
        if isinstance(raw_calibrate_ids, dict):
            for key, value in raw_calibrate_ids.items():
                text_key = id_to_text.get(str(key))
                if text_key and isinstance(value, str):
                    calibrate[text_key] = value

        payload["reject"] = reject
        payload["calibrate"] = calibrate
        return payload

    def _build_sentence_extraction_prompt(self, windows: list[dict[str, str]], enable_samples: bool = True) -> str:
        from ._samples import get_few_shot_examples

        few_shot_str = (
            get_few_shot_examples(max_examples=_SENTENCE_FEW_SHOT_EXAMPLES)
            if enable_samples
            else ""
        )
        few_shot_part = f"\n{few_shot_str}\n\n" if few_shot_str else ""
        previous_context = windows[0].get("previous", "") if windows else ""
        next_context = windows[-1].get("next", "") if windows else ""
        window_lines: list[str] = []
        for item in windows:
            window_lines.append(
                "窗口 {id} 目标句：{target}".format(
                    id=item["id"],
                    target=item.get("target", ""),
                )
            )
        windows_str = "\n\n".join(window_lines)

        return (
            "/no_think\n"
            "你是法律文书脱敏实体识别器。只输出一个紧凑 JSON 对象，不解释、不复述输入。\n"
            "每个窗口是一句完整目标句；同批次窗口按原文顺序连续排列。\n"
            "上一句/下一句只提供批次边界上下文；上下文仅供理解，实体必须逐字来自【目标句】。\n\n"
            f"{few_shot_part}"
            "规则摘要：\n"
            "- 机构优先完整名称；以下简称/简称/原名称/曾用名指向同一机构时，全称与简称都写入 companies。\n"
            "- 机构名不要包含原告、被告、第三人、上诉人、案外人等诉讼地位前缀。\n"
            "- 2 字人名若是更长人名/机构名/案号片段，不要输出。\n"
            "- reject 写目标句中像实体但实际不是的逐字子串：签约、银行流水、甲方、合同一/二/三、"
            "否认其与某公司系关联公司等程序性长句。\n"
            "- 无实体则返回空数组；JSON 尽量短，不要多余字段。\n\n"
            "输出格式：\n"
            '{"locations":[{"window":"s1","full":"示例地名","core":"示例地名"}],'
            '"companies":[{"window":"s1","name":"示例公司","variants":["示例公司"]}],'
            '"persons":[{"window":"s1","name":"张三","surname":"张"}],'
            '"projects":[{"window":"s1","name":"示例项目"}],'
            '"reject":[],"calibrate":{}}\n\n'
            "=== 批次边界上下文 ===\n"
            f"上一句：{previous_context}\n"
            f"下一句：{next_context}\n\n"
            f"=== 句子窗口 ===\n{windows_str}\n"
        )

    def _build_merged_prompt(self, text: str, candidates: list[dict], enable_samples: bool = True) -> str:
        from ._samples import get_few_shot_examples
        few_shot_str = get_few_shot_examples() if enable_samples else ""
        few_shot_part = f"\n{few_shot_str}\n\n" if few_shot_str else ""

        candidate_lines = []
        for i, c in enumerate(candidates, 1):
            ctx = c.get("context", "")
            candidate_lines.append(
                f'ID={i} 类型={c["type"]}, 文本=「{c["text"]}」, 上下文=「...{ctx}...」'
            )
        candidates_str = "\n".join(candidate_lines) if candidate_lines else "暂无需要校验的候选词"

        return (
            "/no_think\n"
            "你是法律文书脱敏候选审核器。只做候选分类，禁止解释任务、禁止复述输入。\n"
            "最终回复只能是一个 JSON 对象，顶层只能有 reject_ids、calibrate_ids 两个键。\n"
            "正确候选不要输出，禁止输出保留理由，禁止输出 companies/persons/locations，禁止输出候选原文列表。\n\n"
            f"{few_shot_part}"
            "你可以在内部按分词、候选实体、边界和类型做判断，但最终不要输出思考、分词或解释。\n"
            "法律文书边界规则：完整机构名优先于短字号；`原名称/曾用名/简称/以下简称/下称` 是同一机构关系的强证据；"
            "2 字人名如果落在更长人名、机构名、项目名或案号内，应 reject 或校准为完整实体。\n\n"
            "## 任务 1：校验疑似实体候选列表\n"
            "下面是脱敏系统通过正则/启发式规则匹配到的【候选列表】。请你逐一审核，将其中【明显的误识别】的 ID 放入 reject_ids 数组。\n"
            "判断标准：\n"
            "- 应该【保留】（不要放入 reject）：真实的省市区县地名、真实存在的公司/机构名/律所、公司简称、真实的人名。\n"
            "- 应该【剔除】（放入 reject_ids）：包含“公司”但不是公司名的普通表述（如：来我去公司、如果你们公司、严重阻碍我公司、导致公司办公区）、"
            "非行政区划的类似表述（如：合理区、办公区、广场东区）、完整公司名的残余子串、无品牌名的纯法律后缀（如：有限责任公司、家具有限公司）、"
            "明显不是人名的短语（如：一审法院、请求已无、合同无效、配合协助等）。\n"
            "- 候选是短片段时要从上下文判断：如果它只是更长公司名、人名、项目名或案号的一部分，必须 reject。"
            "例如「路达」出现在「江苏路达电力工程有限公司」内不是人名；「王文」出现在「王文其」内不是独立人名；"
            "「（2024」是案号/日期片段，不是地名。\n"
            "- 公司简称只有在上下文明确表示公司/机构时才保留，如「大唐公司」「拓欧公司」。"
            "孤立品牌词或被 HanLP 误标成人名/地点的公司字号，应 reject 或校准为上下文中的公司简称。\n\n"
            "## 任务 2：候选实体边界校准（非必填）\n"
            "如果【候选列表】中的某些项目包含真实的实体，但在提取或匹配切片时出现了以下问题，请在 JSON 的 `calibrate_ids` 字典中以 `\"ID\": \"校准后的正确纯净实体\"` 的键值对进行输出：\n"
            "1. **前缀/后缀混入杂质**：夹带多余动作词、连词、介词或人名。例如「某人无权代表星河公司」应校准为「星河公司」。示例名称均为虚构。\n"
            "2. **前导括号/标点残留**：例如「）示例省星河药业有限公司」应校准为「示例省星河药业有限公司」。\n"
            "3. **严重切片或截断**：结合原文恢复完整实体，但校准结果必须逐字存在于原文中。\n"
            "如果候选词已经很纯净或完全不需保留，不要放入 `calibrate_ids`，而是应该放入 `reject_ids`。\n\n"
            "每个候选必须做出处理：正确候选完全不输出；错误候选 ID 放入 reject_ids；"
            "含有真实实体但边界错误的候选 ID 放入 calibrate_ids。不要新增候选列表以外的项目。\n\n"
            "## 输出格式\n"
            "输出严格 JSON。只填写 reject_ids 和可选 calibrate_ids：\n"
            "{\n"
            '  "reject_ids": [2, 5],\n'
            '  "calibrate_ids": {\n'
            '    "3": "星河公司",\n'
            '    "4": "示例省星河药业有限公司"\n'
            '  }\n'
            "}\n\n"
            "例如：候选是人名「林甲明」、非地名「办公区」、边界错误「某人无权代表星河公司」时，"
            '假设它们的 ID 分别是 1、2、3，必须输出 {"reject_ids":[2],"calibrate_ids":{"3":"星河公司"}}。\n\n'
            f"=== 候选列表 ===\n{candidates_str}\n\n"
            f"=== 文书原文（部分）===\n{text}\n"
        )
