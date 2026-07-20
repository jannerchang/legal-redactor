from __future__ import annotations

import re
import random
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from .candidate_collector import (
    CandidateCollectionContext,
    CandidateCollector,
    candidate_needs_llm_review,
    CandidateCollectionResult,
)
from .config import HIGH_RISK_TYPES, PipelineConfig, RedactionProfile
from .entity_registry import FullDocumentEntityRegistry, RegistryMaterialization, materialize_registry_candidates
from .counters import TypeCounters
from .detectors import (
    detect_standard_regex_candidates,
    remove_court_signatures,
)
from .admin_division import AdminDivisionDetector
from .china_admin_rules import detect_china_admin_rule_candidates
from .hebei_admin import HebeiAdminDivisionDetector
from .linear_engine import LinearRuleEngine
from .location_utils import get_location_core
from .models import BatchRedactionResult, Candidate, Leak, MappingEntry, RecognitionRunStats, RedactedDocument, RedactionMap, RedactionResult
from .postprocess import PostprocessConfig, apply_postprocess
from .recognition_audit import audit_recognition


_COMPANY_SUFFIXES_FOR_ALIAS_BOUNDARY = (
    "有限责任公司",
    "股份有限公司",
    "集团有限公司",
    "有限公司",
    "公司",
    "集团",
)
_ORG_ALIAS_LONGER_COMPANY_RE = re.compile(
    r"^[\u4e00-\u9fa5A-Za-z0-9·]{1,16}(?:"
    + "|".join(re.escape(suffix) for suffix in _COMPANY_SUFFIXES_FOR_ALIAS_BOUNDARY)
    + r")"
)



# 全国法院省份及兵团简称
PROVINCE_ABBRS = [
    "京", "津", "冀", "晋", "蒙", "辽", "吉", "黑", "沪", "苏", "浙", "皖",
    "闽", "赣", "鲁", "豫", "鄂", "湘", "粤", "桂", "琼", "渝", "川", "贵",
    "云", "藏", "陕", "甘", "青", "宁", "新", "兵"
]


def map_case_number(case_num: str, prov_mapping: dict[str, str]) -> str:
    """对案号进行脱敏：最高法院案号原样保留；其他地区案号的省份简称进行随机且一致的映射替换。"""
    if "最高法" in case_num or "最高院" in case_num:
        return case_num

    for abbr in PROVINCE_ABBRS:
        if abbr in case_num:
            if abbr not in prov_mapping:
                # 随机选择一个不同的简称进行一致性映射
                choices = [p for p in PROVINCE_ABBRS if p != abbr]
                prov_mapping[abbr] = random.choice(choices)
            mapped_abbr = prov_mapping[abbr]
            return case_num.replace(abbr, mapped_abbr)
    return case_num


def mask_hebei_text(text: str, get_loc_prefix=None) -> str:
    """对河北政区库提取出的地名/基层组织路径进行级联动态脱敏。"""
    if get_loc_prefix is None:
        def get_loc_prefix(name):
            return "某"

    pattern = re.compile(
        r"^(?:(?P<prov>[\u4e00-\u9fa5]+?(?:省|自治区)))?"
        r"(?:(?P<city>[\u4e00-\u9fa5]+?(?:市|自治州)))?"
        r"(?:(?P<county>[\u4e00-\u9fa5]+?(?:(?<!社)区|县)))?"
        r"(?:(?P<town>[\u4e00-\u9fa5]+?(?:街道|镇|乡)))?"
        r"(?:(?P<village>[\u4e00-\u9fa5]+?(?:居民委员会|居委会|村民委员会|村委会|社区|村)))?$"
    )
    m = pattern.match(text)
    if not m:
        return text
    parts = []
    if m.group("prov"):
        p = m.group("prov")
        prefix = get_loc_prefix(p)
        if p.endswith("省"):
            parts.append(f"{prefix}省")
        else:
            parts.append(f"{prefix}自治区")
    if m.group("city"):
        p = m.group("city")
        prefix = get_loc_prefix(p)
        if p.endswith("市"):
            parts.append(f"{prefix}市")
        else:
            parts.append(f"{prefix}自治州")
    if m.group("county"):
        p = m.group("county")
        prefix = get_loc_prefix(p)
        if p.endswith("区"):
            parts.append(f"{prefix}区")
        else:
            parts.append(f"{prefix}县")
    if m.group("town"):
        p = m.group("town")
        prefix = get_loc_prefix(p)
        if p.endswith("街道"):
            parts.append(f"{prefix}街道")
        elif p.endswith("镇"):
            parts.append(f"{prefix}镇")
        else:
            parts.append(f"{prefix}乡")
    if m.group("village"):
        p = m.group("village")
        prefix = get_loc_prefix(p)
        if p.endswith("居民委员会"):
            parts.append(f"{prefix}社区居民委员会")
        elif p.endswith("居委会"):
            parts.append(f"{prefix}社区居委会")
        elif p.endswith("村民委员会"):
            parts.append(f"{prefix}村民委员会")
        elif p.endswith("村委会"):
            parts.append(f"{prefix}村委会")
        elif p.endswith("社区"):
            parts.append(f"{prefix}社区")
        elif p.endswith("村"):
            parts.append(f"{prefix}村")
        else:
            parts.append(f"{prefix}基层组织")
    res = "".join(parts)
    return res if res else text


def _levels_allow_admin_overlap(level: str, used_level: str) -> bool:
    # A full database path supplies its component mappings itself. Same-level
    # candidates may represent separate occurrences and therefore coexist.
    return level == used_level and level in {"province", "city", "county", "county_city", "township"}


def _admin_candidate_contains_used_spans(
    candidate: Candidate,
    spans: list[tuple[int, int, str]],
) -> bool:
    return any(
        candidate.start <= used_start and candidate.end >= used_end and candidate.start != used_start
        for used_start, used_end, _used_level in spans
    )

def _span_overlaps_admin(
    spans: list[tuple[int, int, str]],
    start: int,
    end: int,
    level: str = "",
) -> bool:
    for used_start, used_end, used_level in spans:
        if end <= used_start or start >= used_end:
            continue
        if _levels_allow_admin_overlap(level, used_level):
            continue
        return True
    return False



_AUTOMATIC_ADMIN_LEVELS = frozenset({"province", "city", "county", "county_city"})


def _automatic_admin_candidate(candidate: Candidate) -> bool:
    """Keep automatic location redaction to province, city, district, and county."""
    return candidate.type == "location" and str(candidate.metadata.get("level", "")) in _AUTOMATIC_ADMIN_LEVELS


def _append_admin_detection(
    candidate: Candidate,
    *,
    profile: RedactionProfile,
    mappings: list[MappingEntry],
    admin_spans: list[tuple[int, int, str]],
    get_location_prefix,
    get_admin_prefix,
) -> None:
    if not _automatic_admin_candidate(candidate):
        return
    if not _candidate_allowed(candidate.type, profile):
        return
    level = str(candidate.metadata.get("level", "") or "")
    if _span_overlaps_admin(admin_spans, candidate.start, candidate.end, level):
        return
    if _admin_candidate_contains_used_spans(candidate, admin_spans):
        return
    admin_spans.append((candidate.start, candidate.end, level))
    mappings.append(
        MappingEntry(
            type=candidate.type,
            original=candidate.text,
            masked=_admin_candidate_mask(candidate, get_location_prefix, get_admin_prefix),
            role=None,
            source=candidate.source,
            confidence=candidate.confidence,
            restore_by_default=True,
        )
    )


def _admin_candidate_mask(
    candidate: Candidate,
    get_loc_prefix,
    get_admin_prefix,
) -> str:
    """Mask one admin-db candidate, keeping full and short aliases aligned by code."""
    text = candidate.text
    if _hebei_path_part_count(text) > 1:
        return mask_hebei_text(text, get_loc_prefix)

    level = str(candidate.metadata.get("level", "") or "")
    canonical_name = str(candidate.metadata.get("canonical_name", "") or "")
    division_code = str(candidate.metadata.get("division_code", "") or "")
    prefix = get_admin_prefix(division_code, text, canonical_name or text)
    suffix = _admin_mask_suffix(level, text, canonical_name)
    return f"{prefix}{suffix}" if suffix else mask_hebei_text(text, get_loc_prefix)


def _hebei_path_part_count(text: str) -> int:
    pattern = re.compile(
        r"^(?:(?P<prov>[\u4e00-\u9fa5]+?(?:省|自治区)))?"
        r"(?:(?P<city>[\u4e00-\u9fa5]+?(?:市|自治州)))?"
        r"(?:(?P<county>[\u4e00-\u9fa5]+?(?:(?<!社)区|县)))?"
        r"(?:(?P<town>[\u4e00-\u9fa5]+?(?:街道|镇|乡)))?"
        r"(?:(?P<village>[\u4e00-\u9fa5]+?(?:居民委员会|居委会|村民委员会|村委会|社区|村)))?$"
    )
    match = pattern.match(text)
    if not match:
        return 0
    return sum(1 for value in match.groupdict().values() if value)


def _admin_suffix_for_text(text: str) -> str:
    suffixes = (
        "居民委员会", "村民委员会", "居委会", "村委会", "自治区",
        "自治州", "街道", "社区", "省", "市", "区", "县", "旗", "镇", "乡", "村",
    )
    for suffix in suffixes:
        if text.endswith(suffix):
            return suffix
    return ""


def _admin_suffix_for_level(level: str, canonical_name: str) -> str:
    if level == "province":
        return "自治区" if canonical_name.endswith("自治区") else "省"
    if level == "city":
        return "自治州" if canonical_name.endswith("自治州") else "市"
    if level in {"county", "county_city"}:
        return _admin_suffix_for_text(canonical_name) or ("市" if level == "county_city" else "县")
    if level == "township":
        return _admin_suffix_for_text(canonical_name) or "镇"
    if level == "community":
        return _admin_suffix_for_text(canonical_name) or "社区"
    if level == "village":
        return _admin_suffix_for_text(canonical_name) or "村"
    return _admin_suffix_for_text(canonical_name)


def _admin_mask_suffix(level: str, text: str, canonical_name: str) -> str:
    if text.endswith("村民委员会"):
        return "村民委员会"
    if text.endswith("村委会"):
        return "村委会"
    if text.endswith("居民委员会"):
        return "社区居民委员会"
    if text.endswith("居委会"):
        return "社区居委会"
    if level == "community":
        return "社区"
    if level == "village":
        return "村"
    return _admin_suffix_for_text(text) or _admin_suffix_for_text(canonical_name) or _admin_suffix_for_level(level, canonical_name)







def _candidate_allowed(entity_type: str, config: RedactionProfile) -> bool:
    if entity_type == "person":
        return config.redact_persons
    if entity_type == "location":
        return config.redact_locations
    if entity_type == "organization":
        return config.redact_organizations
    if entity_type == "project":
        return config.redact_projects
    if entity_type == "id_number":
        return config.redact_id_numbers
    if entity_type == "phone":
        return config.redact_phones
    if entity_type == "bank_account":
        return config.redact_bank_accounts
    if entity_type == "unified_social_credit_code":
        return config.redact_uscc
    if entity_type == "email":
        return config.redact_emails
    if entity_type == "case_number":
        return config.redact_case_numbers
    if entity_type == "court_name":
        return config.redact_court_names
    if entity_type == "address":
        return config.redact_addresses
    return True







def _as_project_candidate_if_needed(candidate: Candidate) -> Candidate:
    if candidate.type != "location":
        return candidate
    if candidate.text.endswith(("风电场", "项目", "工程", "小区", "花园", "公寓", "广场", "大厦", "产业园", "标段")):
        return replace(candidate, type="project", reason=f"{candidate.reason}; NER 地名按项目后缀转为项目")
    return candidate


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered




def _should_skip_short_org_alias_replacement(
    text: str,
    start: int,
    end: int,
    mapping: MappingEntry,
) -> bool:
    """Avoid replacing a stated short org alias inside a different longer company name."""
    if mapping.type not in {"organization", "individual_business"}:
        return False
    original = mapping.original.strip()
    if not original or len(original) > 6:
        return False
    if any(original.endswith(suffix) for suffix in _COMPANY_SUFFIXES_FOR_ALIAS_BOUNDARY):
        return False
    following = text[end : end + 24]
    if following.startswith(("公司", "集团")):
        return True
    return bool(_ORG_ALIAS_LONGER_COMPANY_RE.match(following))




class _RecognitionState(str, Enum):
    NOT_REQUESTED = "not_requested"
    SUCCESS = "success"
    PARTIAL = "partial"
    NO_TARGETS = "no_targets"
    FALLBACK = "fallback"
    HARD_FAILURE = "hard_failure"


@dataclass
class _RedactionContext:
    """Mutable state for the linear redaction path.

    Holds cross-step accumulators (mappings, counters, prefix registries, LLM
    analysis, etc.) so the orchestration in ``RedactionPipeline._redact_linear``
    can remain decomposed into single-responsibility step functions. Step-local
    state stays local to each step function; only state needed across step
    boundaries lives here.
    """

    text: str
    source_file: str | None
    profile: RedactionProfile
    counters: TypeCounters
    warnings: list[str] = field(default_factory=list)
    mappings: list[MappingEntry] = field(default_factory=list)
    prov_mapping: dict[str, str] = field(default_factory=dict)
    scan_text: str = ""
    base_mappings: list[MappingEntry] = field(default_factory=list)
    location_prefixes: dict[str, str] = field(default_factory=dict)
    admin_prefixes: dict[str, str] = field(default_factory=dict)
    analysis: dict[str, Any] = field(default_factory=dict)
    # linear-only
    fixed_regex_mappings: list[MappingEntry] = field(default_factory=list)
    admin_candidates: list[Candidate] = field(default_factory=list)
    admin_spans: list[tuple[int, int, str]] = field(default_factory=list)
    hanlp_candidates: list[Candidate] = field(default_factory=list)
    review_candidates: list[Candidate] = field(default_factory=list)
    recognition_state: _RecognitionState = _RecognitionState.NOT_REQUESTED
    registry_materialization: RegistryMaterialization | None = None
    registry_constraints: FullDocumentEntityRegistry | None = None
    recognition_stats: RecognitionRunStats | None = None

    def get_location_prefix(self, name: str) -> str:
        core = get_location_core(name)
        if core not in self.location_prefixes:
            self.location_prefixes[core] = self.counters.next("location")
        return self.location_prefixes[core]

    def get_admin_prefix(self, division_code: str, surface_name: str, canonical_name: str = "") -> str:
        core = get_location_core(surface_name)
        if division_code in self.admin_prefixes:
            return self.admin_prefixes[division_code]
        if core in self.location_prefixes:
            self.admin_prefixes[division_code] = self.location_prefixes[core]
            return self.admin_prefixes[division_code]
        prefix = self.get_location_prefix(surface_name)
        if division_code:
            self.admin_prefixes[division_code] = prefix
        return prefix



# ── Linear path steps ──────────────────────────────────────────

def _linear_init_ctx(pipeline, text, source_file, prov_mapping, base_redaction_map) -> _RedactionContext:
    profile = pipeline._profile
    ctx = _RedactionContext(text=text, source_file=source_file, profile=profile, counters=TypeCounters())
    ctx.prov_mapping = prov_mapping if prov_mapping is not None else {}

    boundary_match = re.search(r"本院(?:经审理|经审查|审理)?认为", text)
    ctx.scan_text = text[: boundary_match.start()] if boundary_match else text

    # Samples are optimization evidence only. Runtime redaction is derived
    # exclusively from current detectors, LLM analysis, and explicit base maps.
    ctx.base_mappings = list(base_redaction_map.mappings) if base_redaction_map else []
    return ctx


def _linear_seed_base_prefixes(ctx) -> None:
    for mapping in ctx.base_mappings:
        if mapping.type != "location" or not mapping.masked:
            continue
        core = get_location_core(mapping.original)
        match = re.match(r"^([一-龥])", mapping.masked)
        if match and match.group(1) != "某":
            ctx.location_prefixes[core] = match.group(1)


def _linear_collect_regex_with_fixed(pipeline, ctx, text) -> None:
    if pipeline.config.enable_regex:
        for candidate in detect_standard_regex_candidates(text):
            if not _candidate_allowed(candidate.type, ctx.profile):
                continue
            masked = (
                map_case_number(candidate.text, ctx.prov_mapping)
                if candidate.type == "case_number"
                else "***"
            )
            mapping = MappingEntry(
                type=candidate.type,
                original=candidate.text,
                masked=masked,
                role=None,
                source=candidate.source,
                confidence=candidate.confidence,
                restore_by_default=False,
            )
            ctx.mappings.append(mapping)
            ctx.fixed_regex_mappings.append(mapping)


def _linear_collect_admin_spans(pipeline, ctx) -> None:
    for detector in (pipeline.hebei_admin_detector, pipeline.china_admin_detector):
        if detector is None:
            continue
        for candidate in sorted(
            detector.detect(ctx.scan_text),
            key=lambda item: (item.start, item.length, item.end),
        ):
            before = len(ctx.mappings)
            _append_admin_detection(
                candidate,
                profile=ctx.profile,
                mappings=ctx.mappings,
                admin_spans=ctx.admin_spans,
                get_location_prefix=ctx.get_location_prefix,
                get_admin_prefix=ctx.get_admin_prefix,
            )
            if len(ctx.mappings) == before:
                continue


def _linear_collect_china_admin_candidates(pipeline, ctx) -> None:
    if not (pipeline.config.enable_china_admin_rules and ctx.profile.redact_locations):
        return
    for candidate in detect_china_admin_rule_candidates(ctx.scan_text):
        if not _automatic_admin_candidate(candidate):
            continue
        level = str(candidate.metadata.get("level", "") or "")
        if _span_overlaps_admin(ctx.admin_spans, candidate.start, candidate.end, level):
            continue
        ctx.admin_candidates.append(candidate)


_COURT_PERSONNEL_PREFIXES = (
    "审判长",
    "审判员",
    "代理审判员",
    "人民陪审员",
    "法官助理",
    "书记员",
    "执行员",
    "执行法官",
)


def _hanlp_candidate_allowed(candidate: Candidate, text: str) -> bool:
    if candidate.type == "location":
        return (
            not candidate.text.startswith(("（", "("))
            and candidate.text.endswith(("省", "市", "区", "县", "旗", "自治区", "特别行政区", "自治州"))
        )
    if candidate.type != "person":
        return True
    line_start = max(text.rfind("\n", 0, candidate.start) + 1, text.rfind("。", 0, candidate.start) + 1)
    prefix = text[line_start:candidate.start].strip(" ：:")
    return not prefix.endswith(_COURT_PERSONNEL_PREFIXES)


def _linear_collect_hanlp_candidates(pipeline, ctx) -> None:
    if pipeline.config.enable_hanlp_ner:
        from .hanlp_ner import detect_hanlp_ner_candidates

        detected_hanlp, hanlp_error = detect_hanlp_ner_candidates(
            ctx.scan_text,
            model=pipeline.config.hanlp_model,
            max_chars=pipeline.config.hanlp_max_chars,
        )
        if hanlp_error:
            ctx.warnings.append(hanlp_error)
        for candidate in detected_hanlp:
            candidate = _as_project_candidate_if_needed(candidate)
            if not _candidate_allowed(candidate.type, ctx.profile):
                continue
            if not _hanlp_candidate_allowed(candidate, ctx.scan_text):
                continue
            if any(
                not (candidate.end <= start or candidate.start >= end)
                for start, end, _level in ctx.admin_spans
            ):
                continue
            ctx.hanlp_candidates.append(candidate)


def _linear_run_recognition(pipeline, ctx, text):
    """Dispatch configured recognition and preserve the fixed fallback ladder."""
    ctx.review_candidates = []
    ctx.analysis = {
        "locations": [],
        "companies": [],
        "persons": [],
        "projects": [],
        "reject": [],
        "calibrate": {},
    }
    llm_requested = pipeline.config.enable_llm and pipeline.config.llm.enabled
    if not llm_requested:
        ctx.recognition_state = _RecognitionState.NOT_REQUESTED
        ctx.recognition_stats = RecognitionRunStats(
            mode="rules_ner",
            model_id=None,
            status=ctx.recognition_state.value,
        )
        return None
    sentence_extraction_enabled = (
        pipeline.config.llm.role == "sentence_entity_extraction"
        or (
            pipeline.config.semantic_llm_first
            and pipeline.config.llm.mode == "max-effect"
        )
    )
    if not sentence_extraction_enabled:
        ctx.recognition_state = _RecognitionState.NOT_REQUESTED
        ctx.recognition_stats = RecognitionRunStats(
            mode="candidate_review",
            model_id=pipeline.config.llm.model,
            status=ctx.recognition_state.value,
        )
        return None


    if pipeline.config.llm.recognition_mode == "full_document":
        early = _linear_run_full_document_recognition(pipeline, ctx, text)
        if early is not None or ctx.recognition_state == _RecognitionState.SUCCESS:
            return early
        ctx.warnings.append(
            f"整篇 LLM 识别失败，已回退逐句窗口：{ctx.recognition_stats.reason if ctx.recognition_stats else 'unknown'}"
        )

    return _linear_run_sentence_windows(pipeline, ctx, text)


def _linear_run_full_document_recognition(pipeline, ctx, text):
    from .llm import LegalEntityAuditor

    extraction = LegalEntityAuditor(pipeline.config.llm).extract_full_document_registry(
        ctx.scan_text,
        enable_samples=False,
    )
    metadata = extraction.metadata
    if extraction.status != "success":
        ctx.recognition_state = _RecognitionState.FALLBACK
        ctx.recognition_stats = RecognitionRunStats(
            mode="full_document",
            model_id=pipeline.config.llm.model,
            status=ctx.recognition_state.value,
            call_count=metadata.call_count,
            retry_count=metadata.retry_count,
            fallback_count=1,
            duration_ms=metadata.duration_ms,
            prompt_token_count=metadata.prompt_token_count,
            completion_token_count=metadata.completion_token_count,
            total_token_count=metadata.total_token_count,
            reason=extraction.reason,
        )
        return None

    materialization = materialize_registry_candidates(ctx.scan_text, extraction.validation)
    ctx.registry_materialization = materialization
    ctx.registry_constraints = materialization.constraints
    ctx.review_candidates.extend(materialization.review_candidates)
    detector_candidates = CandidateCollector().collect(
        CandidateCollectionContext(
            text=ctx.scan_text,
            seed_candidates=[*ctx.admin_candidates, *ctx.hanlp_candidates],
            llm_analysis={},
            llm_primary_discovery=False,
            use_semantic_rules=True,
            use_china_admin_rules=pipeline.config.enable_china_admin_rules,
        )
    ).candidates
    audit_result = audit_recognition(
        detector_candidates,
        materialization,
        materialization.constraints,
    )
    ctx.review_candidates.extend(audit_result.review_candidates)
    ctx.warnings.extend(extraction.validation.warnings)
    ctx.recognition_state = _RecognitionState.SUCCESS
    ctx.recognition_stats = RecognitionRunStats(
        mode="full_document",
        model_id=pipeline.config.llm.model,
        status=ctx.recognition_state.value,
        call_count=metadata.call_count,
        retry_count=metadata.retry_count,
        conflict_count=sum(
            audit_result.category_counts.get(category, 0)
            for category in (
                "type_conflict",
                "grouping_conflict",
                "merge_conflict",
                "split_conflict",
                "uncertain",
            )
        ),
        duration_ms=metadata.duration_ms,
        prompt_token_count=metadata.prompt_token_count,
        completion_token_count=metadata.completion_token_count,
        total_token_count=metadata.total_token_count,
        category_counts=audit_result.category_counts,
    )
    return None


def _linear_run_sentence_windows(pipeline, ctx, text):
    """Run the stable sentence-window baseline, including fail-open behavior."""
    from .llm import LegalEntityAuditor

    prior_stats = ctx.recognition_stats
    ctx.analysis = LegalEntityAuditor(pipeline.config.llm).extract_sentence_entities(
        ctx.scan_text,
        enable_samples=False,
    )
    if ctx.analysis.get("error"):
        reason = str(ctx.analysis["error"])
        call_count = prior_stats.call_count if prior_stats else 0
        retry_count = prior_stats.retry_count if prior_stats else 0
        duration_ms = prior_stats.duration_ms if prior_stats else 0
        fallback_count = (prior_stats.fallback_count if prior_stats else 0) + 1
        if not pipeline.config.llm.fail_open:
            ctx.recognition_state = _RecognitionState.HARD_FAILURE
            ctx.recognition_stats = RecognitionRunStats(
                mode=pipeline.config.llm.recognition_mode,
                model_id=pipeline.config.llm.model,
                status=ctx.recognition_state.value,
                call_count=call_count,
                retry_count=retry_count,
                fallback_count=fallback_count,
                duration_ms=duration_ms,
                reason=reason,
            )
            ctx.warnings.append(f"整句 LLM 识别失败，已仅保留固定结构化正则脱敏：{reason}")
            return _structured_regex_early_result(pipeline, ctx, text)
        ctx.recognition_state = _RecognitionState.FALLBACK
        ctx.recognition_stats = RecognitionRunStats(
            mode=pipeline.config.llm.recognition_mode,
            model_id=pipeline.config.llm.model,
            status=ctx.recognition_state.value,
            call_count=call_count,
            retry_count=retry_count,
            fallback_count=fallback_count,
            duration_ms=duration_ms,
            reason=reason,
        )
        ctx.warnings.append(f"整句 LLM 识别失败，已降级为规则模式：{reason}")
        ctx.analysis = {
            "locations": [],
            "companies": [],
            "persons": [],
            "projects": [],
            "reject": [],
            "calibrate": {},
        }
        return None

    if ctx.analysis.get("_no_target_windows"):
        ctx.recognition_state = _RecognitionState.NO_TARGETS
    elif ctx.analysis.get("_batch_failures"):
        failures = ctx.analysis.get("_batch_failures", [])
        ctx.recognition_state = _RecognitionState.PARTIAL
        ctx.warnings.append(f"部分批次 LLM 识别失败（{len(failures)} 批），已使用其余批次结果编排。")
    else:
        ctx.recognition_state = _RecognitionState.SUCCESS
    ctx.recognition_stats = RecognitionRunStats(
        mode="sentence_windows",
        model_id=pipeline.config.llm.model,
        status=ctx.recognition_state.value,
        fallback_count=prior_stats.fallback_count if prior_stats else 0,
        reason=prior_stats.reason if prior_stats and prior_stats.fallback_count else None,
    )
    return None


def _structured_regex_early_result(pipeline, ctx, text) -> RedactionResult:
    unique_mappings: list[MappingEntry] = []
    seen_originals: set[str] = set()
    for mapping in [*ctx.base_mappings, *sorted(ctx.fixed_regex_mappings, key=lambda item: len(item.original), reverse=True)]:
        if mapping.original in seen_originals:
            continue
        seen_originals.add(mapping.original)
        unique_mappings.append(mapping)
    unique_mappings = apply_postprocess(text, unique_mappings, PostprocessConfig())
    redacted_text = remove_court_signatures(pipeline.apply_mappings(text, unique_mappings))
    return RedactionResult(
        original_text=text,
        redacted_text=redacted_text,
        redaction_map=RedactionMap.create(
            mappings=unique_mappings,
            mode=ctx.profile.name,
            source_file=ctx.source_file,
        ),
        candidates=[],
        review_candidates=[],
        leaks=pipeline.scan_high_risk_leaks(redacted_text),
        mode=ctx.profile.name,
        warnings=ctx.warnings,
        recognition_stats=ctx.recognition_stats,
    )


def _linear_run_engine(pipeline, ctx) -> None:
    collector = CandidateCollector()
    engine = LinearRuleEngine(
        counters=ctx.counters,
        profile=ctx.profile,
        get_location_prefix=ctx.get_location_prefix,
    )
    engine.known_locations = {
        mapping.original: mapping.masked
        for mapping in ctx.mappings
        if mapping.type == "location" and mapping.masked
    }
    seed_candidates = [*ctx.admin_candidates, *ctx.hanlp_candidates]

    if ctx.registry_materialization is not None and ctx.recognition_state == _RecognitionState.SUCCESS:
        collected = collector.collect(
            CandidateCollectionContext(
                text=ctx.scan_text,
                seed_candidates=seed_candidates,
                llm_analysis={},
                llm_primary_discovery=False,
                use_semantic_rules=True,
                use_china_admin_rules=pipeline.config.enable_china_admin_rules,
                registry_materialization=ctx.registry_materialization,
            )
        )
        final_candidates = collected.candidates
        ctx.review_candidates = _dedupe_review_candidates(
            [*ctx.review_candidates, *collected.review_candidates]
        )
    elif ctx.recognition_state in {
        _RecognitionState.SUCCESS,
        _RecognitionState.PARTIAL,
        _RecognitionState.NO_TARGETS,
    } and pipeline.config.llm.recognition_mode == "sentence_windows":
        final_candidates = collector.collect(
            CandidateCollectionContext(
                text=ctx.scan_text,
                seed_candidates=seed_candidates,
                llm_analysis=ctx.analysis,
                llm_primary_discovery=True,
                use_semantic_rules=False,
                use_china_admin_rules=pipeline.config.enable_china_admin_rules,
            )
        ).candidates
    else:
        rule_candidates = collector.collect(
            CandidateCollectionContext(
                text=ctx.scan_text,
                seed_candidates=seed_candidates,
                llm_analysis={},
                llm_primary_discovery=False,
                use_semantic_rules=True,
                use_china_admin_rules=pipeline.config.enable_china_admin_rules,
            )
        ).candidates
        ctx.review_candidates = _dedupe_review_candidates(
            [candidate for candidate in rule_candidates if candidate_needs_llm_review(candidate)]
        )
        if (
            pipeline.config.enable_llm
            and pipeline.config.llm.enabled
            and ctx.review_candidates
            and pipeline.config.llm.role != "sentence_entity_extraction"
        ):
            from .llm import LegalEntityAuditor

            verify_list = [
                {
                    "text": candidate.text,
                    "type": candidate.type,
                    "context": candidate.metadata.get(
                        "context",
                        ctx.scan_text[
                            max(0, candidate.start - 60):min(len(ctx.scan_text), candidate.end + 60)
                        ],
                    ),
                }
                for candidate in ctx.review_candidates
            ]
            ctx.analysis = LegalEntityAuditor(pipeline.config.llm).audit_and_verify(
                ctx.scan_text,
                verify_list,
                enable_samples=False,
            )
            if ctx.analysis.get("error"):
                ctx.warnings.append(str(ctx.analysis["error"]))
            final_candidates = CandidateCollectionResult(
                candidates=rule_candidates
            ).with_llm_analysis(collector, ctx.scan_text, ctx.analysis).candidates
        else:
            final_candidates = rule_candidates

    ctx.mappings.extend(
        engine.discover(
            ctx.scan_text,
            final_candidates,
            ctx.analysis,
            registry_constraints=ctx.registry_constraints,
        )
    )


def _dedupe_review_candidates(candidates: list[Candidate]) -> list[Candidate]:
    deduped: list[Candidate] = []
    seen: set[tuple[str, str, int]] = set()
    for candidate in candidates:
        key = (candidate.type, candidate.text, candidate.start)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped[:80]


def _linear_finalize(pipeline, ctx, text) -> RedactionResult:
    unique_mappings: list[MappingEntry] = []
    seen_originals: set[str] = set()
    for mapping in ctx.base_mappings:
        if mapping.original in seen_originals:
            continue
        seen_originals.add(mapping.original)
        unique_mappings.append(mapping)
    for mapping in sorted(ctx.mappings, key=lambda item: len(item.original), reverse=True):
        if mapping.original in seen_originals:
            continue
        seen_originals.add(mapping.original)
        unique_mappings.append(mapping)

    unique_mappings = apply_postprocess(
        text,
        unique_mappings,
        PostprocessConfig(),
    )

    redacted_text = remove_court_signatures(pipeline.apply_mappings(text, unique_mappings))
    leaks = pipeline.scan_high_risk_leaks(redacted_text)
    return RedactionResult(
        original_text=text,
        redacted_text=redacted_text,
        redaction_map=RedactionMap.create(
            mappings=unique_mappings,
            mode=ctx.profile.name,
            source_file=ctx.source_file,
        ),
        candidates=[],
        review_candidates=ctx.review_candidates,
        leaks=leaks,
        mode=ctx.profile.name,
        warnings=ctx.warnings,
        recognition_stats=ctx.recognition_stats,
    )


def _aggregate_recognition_stats(
    stats: list[RecognitionRunStats],
    document_count: int,
) -> RecognitionRunStats | None:
    if not stats:
        return None
    mode = stats[0].mode if all(item.mode == stats[0].mode for item in stats) else "mixed"
    model_ids = {item.model_id for item in stats}
    statuses = {item.status for item in stats}
    return RecognitionRunStats(
        mode=mode,
        model_id=next(iter(model_ids)) if len(model_ids) == 1 else None,
        status=next(iter(statuses)) if len(statuses) == 1 else "partial",
        document_count=document_count,
        call_count=sum(item.call_count for item in stats),
        retry_count=sum(item.retry_count for item in stats),
        fallback_count=sum(item.fallback_count for item in stats),
        conflict_count=sum(item.conflict_count for item in stats),
        duration_ms=sum(item.duration_ms for item in stats),
        prompt_token_count=_sum_optional(item.prompt_token_count for item in stats),
        completion_token_count=_sum_optional(item.completion_token_count for item in stats),
        total_token_count=_sum_optional(item.total_token_count for item in stats),
        reason=next((item.reason for item in stats if item.reason), None),
    )


def _sum_optional(values) -> int | None:
    items = list(values)
    if not items or all(value is None for value in items):
        return None
    return sum(value or 0 for value in items)


class RedactionPipeline:
    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or PipelineConfig()
        self.hebei_admin_detector = (
            HebeiAdminDivisionDetector(self.config.hebei_admin_db_path)
            if self.config.enable_hebei_admin_db else None
        )
        self.china_admin_detector = (
            AdminDivisionDetector(
                self.config.china_admin_db_path,
                source="china_admin_db",
                region_label="全国三级行政区划",
                max_level="county_city",
                require_canonical_substring=True,
            )
            if self.config.enable_china_admin_db else None
        )

    @property
    def _profile(self) -> RedactionProfile:
        return self.config.redaction_profile

    def analyze(self, text: str) -> dict[str, Any]:
        """Return the entity-group shape used by the Web confirmation flow."""
        result = self.redact(text)
        groups_by_key: dict[tuple[str, str], list[MappingEntry]] = {}
        locations: list[str] = []
        seen_locations: set[str] = set()

        for mapping in result.redaction_map.mappings:
            if mapping.type in {"organization", "individual_business"}:
                groups_by_key.setdefault(("organization", mapping.masked), []).append(mapping)
            elif mapping.type == "person":
                groups_by_key.setdefault(("person", mapping.original), []).append(mapping)
            elif mapping.type in {"location", "grassroots_org"} and mapping.original not in seen_locations:
                seen_locations.add(mapping.original)
                locations.append(mapping.original)

        entity_groups: list[dict[str, Any]] = []
        for index, ((entity_type, _key), mappings) in enumerate(groups_by_key.items(), 1):
            originals = _dedupe_strings([mapping.original for mapping in mappings if mapping.original])
            if not originals:
                continue
            full_name = max(originals, key=len)
            aliases = [value for value in originals if value != full_name]
            role = next((mapping.role for mapping in mappings if mapping.role), None)
            entity_groups.append(
                {
                    "id": index,
                    "type": entity_type,
                    "role": role,
                    "full_name": full_name,
                    "aliases": aliases,
                }
            )

        return {
            "entity_groups": entity_groups,
            "locations": locations,
            "warnings": result.warnings,
            "recognition_stats": result.recognition_stats.to_dict() if result.recognition_stats else None,
        }

    def redact(self, text: str, source_file: str | None = None, mode: str | None = None, prov_mapping: dict[str, str] | None = None, base_redaction_map: RedactionMap | None = None) -> RedactionResult:
        if mode is not None:
            config = replace(self.config, redaction_profile=RedactionProfile.from_preset(mode))
            self.config = config
        return self._redact_linear(
            text,
            source_file=source_file,
            prov_mapping=prov_mapping,
            base_redaction_map=base_redaction_map,
        )

    def _redact_linear(
        self,
        text: str,
        source_file: str | None = None,
        prov_mapping: dict[str, str] | None = None,
        base_redaction_map: RedactionMap | None = None,
    ) -> RedactionResult:
        # Linear path: build shared context and run named single-responsibility steps.
        ctx = _linear_init_ctx(self, text, source_file, prov_mapping, base_redaction_map)
        _linear_seed_base_prefixes(ctx)
        _linear_collect_regex_with_fixed(self, ctx, text)
        _linear_collect_admin_spans(self, ctx)
        _linear_collect_china_admin_candidates(self, ctx)
        _linear_collect_hanlp_candidates(self, ctx)
        early = _linear_run_recognition(self, ctx, text)
        if early is not None:
            return early
        _linear_run_engine(self, ctx)
        return _linear_finalize(self, ctx, text)


    def redact_many(self, documents: list[tuple[str, str]], mode: str | None = None, base_redaction_map: RedactionMap | None = None) -> BatchRedactionResult:
        if mode is not None:
            self.config = replace(self.config, redaction_profile=RedactionProfile.from_preset(mode))

        profile = self._profile
        if not documents:
            return BatchRedactionResult(
                documents=[],
                redaction_map=RedactionMap.create(mappings=[], mode=profile.name, source_file=None),
                candidates=[],
                review_candidates=[],
                leaks=[],
                mode=profile.name
            )

        # 解决拼接截断 Bug：逐个对独立文件进行脱敏分析，获取高质量的 Mapping 项
        all_mappings = []
        warnings = []
        recognition_stats: list[RecognitionRunStats] = []
        prov_mapping = {}
        shared_redaction_map = base_redaction_map
        for source_name, original_text in documents:
            res = self.redact(
                original_text,
                source_file=source_name,
                prov_mapping=prov_mapping,
                base_redaction_map=shared_redaction_map,
            )
            all_mappings.extend(res.redaction_map.mappings)
            shared_redaction_map = RedactionMap.create(
                mappings=all_mappings,
                mode=profile.name,
                source_file=None,
            )
            if res.warnings:
                warnings.extend(res.warnings)
            if res.recognition_stats is not None:
                recognition_stats.append(res.recognition_stats)
                
        # 统一汇总去重，生成统一共享的高质量映射表 (按原文长度倒序)
        unique_mappings = []
        seen_orig = set()
        if base_redaction_map and base_redaction_map.mappings:
            for m in base_redaction_map.mappings:
                if m.original not in seen_orig:
                    seen_orig.add(m.original)
                    unique_mappings.append(m)

        for m in sorted(all_mappings, key=lambda x: len(x.original), reverse=True):
            if m.original not in seen_orig:
                seen_orig.add(m.original)
                unique_mappings.append(m)

        joined_text = "\n\n".join(original_text for _, original_text in documents)
        unique_mappings = apply_postprocess(
            joined_text,
            unique_mappings,
            PostprocessConfig(include_fragments=True, include_alias_merge=True),
        )
                
        unified_redaction_map = RedactionMap.create(
            mappings=unique_mappings,
            mode=profile.name,
            source_file="; ".join(n for n, _ in documents)
        )
        
        # 应用统一的高质量映射表到各个文档
        redacted_documents: list[RedactedDocument] = []
        leaks: list[Leak] = []
        for source_name, original_text in documents:
            redacted_text = self.apply_redaction_map(original_text, unified_redaction_map)
            document_leaks = self.scan_high_risk_leaks(redacted_text)
            redacted_documents.append(RedactedDocument(source_file=source_name, original_text=original_text, redacted_text=redacted_text, leaks=document_leaks))
            leaks.extend(document_leaks)
            
        batch_warnings = [f"已对 {len(documents)} 份文书使用同一张映射表统一脱敏。", *warnings]
        batch_stats = _aggregate_recognition_stats(recognition_stats, len(documents))
        return BatchRedactionResult(
            documents=redacted_documents,
            redaction_map=unified_redaction_map,
            candidates=[],
            review_candidates=[],
            leaks=leaks,
            mode=profile.name,
            warnings=batch_warnings,
            recognition_stats=batch_stats,
        )



    def apply_redaction_map(self, text: str, redaction_map: RedactionMap) -> str:
        return remove_court_signatures(self.apply_mappings(text, redaction_map.mappings))

    def apply_mappings(self, text: str, mappings: list[MappingEntry]) -> str:
        if not mappings:
            return text
        sorted_mappings = sorted((m for m in mappings if m.original), key=lambda m: len(m.original), reverse=True)
        replacements: list[tuple[int, int, str]] = []
        occupied: list[tuple[int, int]] = []
        for entry in sorted_mappings:
            start = 0
            while True:
                index = text.find(entry.original, start)
                if index < 0:
                    break
                end = index + len(entry.original)
                start = index + 1
                if any(not (end <= used_start or index >= used_end) for used_start, used_end in occupied):
                    continue
                if _should_skip_short_org_alias_replacement(text, index, end, entry):
                    continue
                replacements.append((index, end, entry.masked))
                occupied.append((index, end))
        if not replacements:
            return text
        chars = list(text)
        for start, end, masked in sorted(replacements, key=lambda item: item[0], reverse=True):
            chars[start:end] = list(masked)
        return "".join(chars)

    def scan_high_risk_leaks(self, text: str) -> list[Leak]:
        leaks: list[Leak] = []
        for candidate in detect_standard_regex_candidates(text):
            if candidate.type not in HIGH_RISK_TYPES:
                continue
            if "某" in candidate.text or "***" in candidate.text:
                continue
            leaks.append(
                Leak(
                    type=candidate.type,
                    text=candidate.text,
                    start=candidate.start,
                    end=candidate.end,
                    source=candidate.source,
                    risk_level=candidate.risk_level,
                )
            )
        return leaks


def apply_redaction_map(text: str, redaction_map: RedactionMap) -> str:
    pipeline = RedactionPipeline()
    return pipeline.apply_redaction_map(text, redaction_map)


