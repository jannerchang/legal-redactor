from __future__ import annotations

import re
import random
from dataclasses import dataclass, field, replace
from typing import Any

from .config import HIGH_RISK_TYPES, PipelineConfig, RedactionProfile
from .counters import TypeCounters
from .detectors import (
    detect_standard_regex_candidates,
    detect_party_candidates,
    detect_heuristic_ner_candidates,
    detect_fallback_person_candidates,
    remove_court_signatures,
    _is_false_org,
    _clean_organization_text,
    _clean_location_text,
    _clean_person_name,
    _is_false_person
)
from .lexicon import GENERIC_BRAND_BLACKLIST as _GENERIC_BRAND_BLACKLIST_SET
from .admin_division import AdminDivisionDetector
from .china_admin_rules import detect_china_admin_rule_candidates
from .hebei_admin import HebeiAdminDivisionDetector
from .linear_engine import LinearRuleEngine
from .location_utils import get_location_core
from .models import BatchRedactionResult, Candidate, Leak, MappingEntry, RedactedDocument, RedactionMap, RedactionResult
from ._samples import load_all_samples, load_trusted_sample_mappings
# load_all_samples is not called in this module, but tests patch
# legal_redactor.pipeline.load_all_samples as a mock anchor
# (tests/test_hebei_admin.py, tests/test_china_admin.py); keep the name
# importable on this module so mock.patch can resolve it.


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


# ── 行业与法律通用高频品牌词黑名单（防止超脱敏误伤普通词汇） ──
GENERIC_BRAND_BLACKLIST = _GENERIC_BRAND_BLACKLIST_SET

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
        get_loc_prefix = lambda name: "某"

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
    direct_levels = {"province", "city", "county", "county_city", "township"}
    return level in direct_levels and used_level in direct_levels


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


def _append_admin_detection(
    candidate: Candidate,
    *,
    profile: RedactionProfile,
    sample_blacklist: set[str],
    mappings: list[MappingEntry],
    admin_spans: list[tuple[int, int, str]],
    get_location_prefix,
    get_admin_prefix,
) -> None:
    if candidate.text in sample_blacklist:
        return
    if candidate.type == "grassroots_org":
        allowed = profile.redact_locations or profile.redact_organizations
    else:
        allowed = _candidate_allowed(candidate.type, profile)
    if not allowed:
        return
    level = str(candidate.metadata.get("level", "") or "")
    if _span_overlaps_admin(admin_spans, candidate.start, candidate.end, level):
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





# ── 公司名解析：品牌 + 业务描述 + 法律后缀 ──
_LEGAL_SUFFIXES = [
    '有限责任公司', '股份有限公司', '集团有限公司', '有限公司',
    '律师事务所', '会计师事务所',
    '个体工商户', '经营部', '工作室', '商行',
    '委员会', '管理局', '公安局', '税务局',
    '合作社', '公司', '集团',
    '中心', '医院', '学校', '幼儿园', '银行', '厂', '店',
]

_BIZ_DESCRIPTORS = [
    '房地产开发', '房地产经纪', '房地产',
    '建筑工程', '建设工程', '装饰工程', '园林工程', '市政工程', '水利工程', '消防工程',
    '建筑装饰', '建筑设计', '建筑材料', '建筑',
    '工程建设', '工程机械', '工程技术', '工程',
    '建设', '装饰', '装修',
    '国际贸易', '进出口贸易', '贸易', '商贸', '外贸',
    '电子商务', '电子科技', '电子',
    '教育科技', '教育咨询', '教育培训', '教育',
    '信息技术', '信息科技', '信息', '网络科技', '网络技术', '网络',
    '新材料', '新能源', '新型建材',
    '生物科技', '生物技术', '生物医药', '生物',
    '物业管理', '物业服务', '物业',
    '物流', '运输', '货运', '快递',
    '投资管理', '投资咨询', '投资发展', '投资',
    '资产管理', '资产',
    '融资租赁', '金融', '保险', '证券',
    '科技发展', '科技',
    '文化传媒', '文化传播', '文化', '传媒',
    '旅游开发', '旅游',
    '餐饮管理', '餐饮', '食品',
    '服装', '纺织',
    '制药', '医药', '药业', '医疗',
    '化工', '化学',
    '矿业', '矿产',
    '能源', '电力', '电气',
    '机械', '设备', '制造',
    '汽车', '车业',
    '农业', '农产品', '农牧',
    '环保', '环境',
    '咨询', '顾问', '策划', '广告',
    '设计', '规划',
    '软件', '数据', '智能', '互联网', '计算机',
    '置业', '实业', '产业', '控股', '开发',
    '园林', '绿化', '景观',
    '酒店', '宾馆', '度假',
    '娱乐', '体育', '健身',
    '家居', '家具', '建材',
    '通信', '通讯',
    '印刷', '包装', '塑料', '橡胶', '玻璃', '陶瓷',
    '钢铁', '金属', '铝业', '铜业',
    '石油', '天然气', '燃气',
    '水务', '供水', '排水',
    '航空', '航天', '船舶',
]

_NON_COMPANY_SUFFIXES = frozenset({
    '委员会', '管理局', '公安局', '税务局', '中心', '医院', '学校',
    '幼儿园', '银行', '合作社', '厂', '店', '经营部', '工作室', '商行',
    '集团', '个体工商户', '律师事务所', '会计师事务所',
})


def _parse_company_name(name: str, known_locations: set[str] | None = None) -> tuple[str, str, str]:
    """将公司名拆分为 (品牌名, 业务描述, 简化后缀)。"""
    # 1. 去掉法律后缀
    legal_suffix = ''
    core = name
    for sfx in _LEGAL_SUFFIXES:
        if name.endswith(sfx):
            legal_suffix = sfx
            core = name[:-len(sfx)]
            break

    # 2. 去掉行政区划前缀（如有）
    if known_locations:
        for loc in sorted(known_locations, key=len, reverse=True):
            if core.startswith(loc) and len(core) > len(loc):
                core = core[len(loc):]
                break
    admin_match = re.match(r'^[\u4e00-\u9fa5]{2,8}(?:省|市|区|县|自治[区州县]|旗)', core)
    if admin_match:
        core = core[admin_match.end():]

    # 2.5. 去掉括号中的行政区划（如 (河北)、（石家庄）等，不论出现在何处）
    core = re.sub(r"[（(](?:[\u4e00-\u9fa5]{2,6}?(?:省|市|区|县|新)?)[）)]", "", core)
    core = core.strip(" ：:，,。；;\n\t（）()")

    # 3. 从 core 中分离品牌和业务描述
    biz_descriptor = ''
    brand = core
    for desc in _BIZ_DESCRIPTORS:
        if core.endswith(desc) and len(core) > len(desc):
            biz_descriptor = desc
            brand = core[:-len(desc)]
            break

    # 4. 简化法律后缀
    if legal_suffix in _NON_COMPANY_SUFFIXES:
        simple_suffix = legal_suffix
    else:
        simple_suffix = '公司'

    return brand, biz_descriptor, simple_suffix


def _candidate_allowed(entity_type: str, config: RedactionProfile) -> bool:
    if entity_type == "person": return config.redact_persons
    if entity_type == "location": return config.redact_locations
    if entity_type == "organization": return config.redact_organizations
    if entity_type == "project": return config.redact_projects
    if entity_type == "id_number": return config.redact_id_numbers
    if entity_type == "phone": return config.redact_phones
    if entity_type == "bank_account": return config.redact_bank_accounts
    if entity_type == "unified_social_credit_code": return config.redact_uscc
    if entity_type == "email": return config.redact_emails
    if entity_type == "case_number": return config.redact_case_numbers
    if entity_type == "court_name": return config.redact_court_names
    if entity_type == "address": return config.redact_addresses
    return True


def _suspicious_organization_candidate(candidate: Candidate) -> bool:
    if candidate.type != "organization":
        return False
    text = candidate.text.strip()
    if not text:
        return False
    from .detectors import _is_false_org

    if _is_false_org(text):
        return False
    if len(text) >= 10:
        return True
    if any(
        marker in text
        for marker in (
            "否认",
            "关联公司",
            "合同",
            "银行流水",
            "人员混同",
            "搅浑",
            "欲证实",
            "无权再向",
        )
    ):
        return True
    return candidate.source == "party_section" and len(text) > 6


def _linear_sentence_review_candidates(
    scan_text: str,
    analysis: dict,
    hanlp_candidates: list[Candidate],
    org_aliases: set[str],
) -> list[Candidate]:
    llm_texts = _analysis_entity_texts(analysis)
    review_candidates: list[Candidate] = []
    seen_review_keys: set[tuple[str, str]] = set()

    for candidate in hanlp_candidates:
        if candidate.text in llm_texts:
            continue
        if not _hanlp_candidate_needs_sentence_review(candidate, org_aliases):
            continue
        key = (candidate.type, candidate.text)
        if key in seen_review_keys:
            continue
        seen_review_keys.add(key)
        review_candidates.append(candidate)

    party_candidates, _ = detect_party_candidates(scan_text)
    for candidate in party_candidates:
        if candidate.text in llm_texts:
            continue
        if not _suspicious_organization_candidate(candidate):
            continue
        key = (candidate.type, candidate.text)
        if key in seen_review_keys:
            continue
        seen_review_keys.add(key)
        review_candidates.append(candidate)

    return review_candidates[:80]


def _candidate_needs_llm_review(candidate: Candidate) -> bool:
    source = candidate.source
    if source in {"fallback_person", "heuristic_ner", "linear_full_org", "linear_bare_org_alias"}:
        return True
    if _suspicious_organization_candidate(candidate):
        return True
    if candidate.confidence < 0.85:
        return True
    if source.startswith("hanlp_ner"):
        if candidate.type == "person":
            return len(candidate.text) <= 2
        if candidate.type in {"location", "grassroots_org"}:
            return len(candidate.text) <= 4 or candidate.text.startswith(("（", "("))
        if candidate.type == "organization":
            return len(candidate.text) <= 6 or not any(
                candidate.text.endswith(suffix)
                for suffix in ("有限责任公司", "股份有限公司", "集团有限公司", "有限公司")
            )
    return False


def _analysis_entity_texts(analysis: dict) -> set[str]:
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
                texts.update(value.strip() for value in variants if isinstance(value, str) and value.strip())
    return texts


def _organization_alias_cores_from_candidates(candidates: list[Candidate]) -> set[str]:
    from .org_masking import derived_organization_alias_cores as _derived_organization_alias_cores

    aliases: set[str] = set()
    for candidate in candidates:
        if candidate.type != "organization":
            continue
        text = _clean_organization_text(candidate.text)
        if not text:
            continue
        aliases.update(_derived_organization_alias_cores(text))
    return {alias for alias in aliases if len(alias) >= 2}


def _has_org_alias_collision(candidate: Candidate, org_aliases: set[str]) -> bool:
    text = candidate.text.strip()
    if not text:
        return False
    if candidate.type == "person" and text in org_aliases:
        return True
    if candidate.type == "location":
        return any(text.startswith(alias) and len(text) > len(alias) for alias in org_aliases)
    return False


def _hanlp_candidate_needs_sentence_review(candidate: Candidate, org_aliases: set[str]) -> bool:
    if not candidate.source.startswith("hanlp_ner"):
        return False
    if _candidate_needs_llm_review(candidate):
        return True
    if candidate.type == "person":
        return True
    if _has_org_alias_collision(candidate, org_aliases):
        return True
    return False


def _as_project_candidate_if_needed(candidate: Candidate) -> Candidate:
    if candidate.type != "location":
        return candidate
    if candidate.text.endswith(("风电场", "项目", "工程", "小区", "花园", "公寓", "广场", "大厦", "产业园", "标段")):
        return replace(candidate, type="project", reason=f"{candidate.reason}; HanLP 地名按项目后缀转为项目")
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


def _trusted_organization_short_names(sample_mappings: list[MappingEntry]) -> set[str]:
    """Short names that trusted samples already treat as organizations."""
    names: set[str] = set()
    for mapping in sample_mappings:
        masked = mapping.masked or ""
        if mapping.type not in {"organization", "individual_business"} and not masked.endswith(
            ("公司", "集团", "律所", "事务所", "机构", "商行", "经营部", "合作社")
        ):
            continue
        original = (mapping.original or "").strip()
        if original:
            names.add(original)
    return names


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


def extract_and_map_geonames(
    text: str,
    get_loc_prefix,
    profile,
    sample_blacklist,
    hebei_admin_detector=None,
    china_admin_detector=None,
) -> list[MappingEntry]:
    if not _candidate_allowed("location", profile):
        return []

    # 1. 收集所有显式地名候选
    candidates = []
    if hebei_admin_detector:
        candidates.extend(hebei_admin_detector.detect(text))
    if china_admin_detector:
        candidates.extend(china_admin_detector.detect(text))
    if profile and getattr(profile, "redact_locations", True):
        candidates.extend(detect_china_admin_rule_candidates(text))

    # 启发式地名也收集过来
    c_ner = detect_heuristic_ner_candidates(text)
    candidates.extend(c for c in c_ner if c.type in ("location", "grassroots_org"))

    # 2. 准备层级容器
    prov_list = []
    city_list = []
    county_list = []
    town_list = []
    village_list = []

    seen_orgs_and_exclusions = {"我们", "你们", "他们", "本案", "该案", "上述", "被告", "原告", "法院", "判决", "公司", "合同", "项目", "工程"}

    # 级联匹配正则，用于分解任何复合地址路径
    decomp_pattern = re.compile(
        r"^(?:(?P<prov>[\u4e00-\u9fa5]+?(?:省|自治区)))?"
        r"(?:(?P<city>[\u4e00-\u9fa5]+?(?:市|自治州)))?"
        r"(?:(?P<county>[\u4e00-\u9fa5]+?(?:(?<!社)区|县)))?"
        r"(?:(?P<town>[\u4e00-\u9fa5]+?(?:街道|镇|乡)))?"
        r"(?:(?P<village>[\u4e00-\u9fa5]+?(?:居民委员会|居委会|村民委员会|村委会|社区|村)))?$"
    )

    for c in candidates:
        full = _clean_location_text(c.text)
        if not full or full in sample_blacklist or full in seen_orgs_and_exclusions:
            continue
        
        m = decomp_pattern.match(full)
        if m:
            if m.group("prov"):
                p_text = m.group("prov")
                prov_list.append((p_text, get_location_core(p_text)))
            if m.group("city"):
                c_text = m.group("city")
                city_list.append((c_text, get_location_core(c_text)))
            if m.group("county"):
                co_text = m.group("county")
                county_list.append((co_text, get_location_core(co_text)))
            if m.group("town"):
                t_text = m.group("town")
                town_list.append((t_text, get_location_core(t_text)))
            if m.group("village"):
                v_text = m.group("village")
                village_list.append((v_text, get_location_core(v_text)))
        else:
            # 备用地名后缀归类
            level = None
            for suffix in ("省", "自治区"):
                if full.endswith(suffix) and len(full) > len(suffix):
                    prov_list.append((full, get_location_core(full)))
                    level = "province"
                    break
            if not level:
                for suffix in ("市", "自治州", "盟"):
                    if full.endswith(suffix) and len(full) > len(suffix):
                        city_list.append((full, get_location_core(full)))
                        level = "city"
                        break
            if not level:
                for suffix in ("区", "县", "旗"):
                    if full.endswith(suffix) and len(full) > len(suffix):
                        county_list.append((full, get_location_core(full)))
                        level = "county"
                        break
            if not level:
                for suffix in ("街道", "镇", "乡"):
                    if full.endswith(suffix) and len(full) > len(suffix):
                        town_list.append((full, get_location_core(full)))
                        level = "town"
                        break
            if not level:
                for suffix in ("居民委员会", "居委会", "村民委员会", "村委会", "社区", "村"):
                    if full.endswith(suffix) and len(full) > len(suffix):
                        village_list.append((full, get_location_core(full)))
                        level = "village"
                        break

    # 3. 级联注册
    mappings = []
    def register_level(items, level_type):
        unique_cores = []
        seen_cores = set()
        for full, core in items:
            if core not in seen_cores:
                seen_cores.add(core)
                unique_cores.append((full, core))
                
        for full, core in unique_cores:
            if len(core) >= 2:
                if core not in seen_orgs_and_exclusions:
                    loc_prefix = get_loc_prefix(core)
                    if level_type == "province":
                        masked = f"{loc_prefix}省" if full.endswith("省") else f"{loc_prefix}自治区"
                    elif level_type == "city":
                        masked = f"{loc_prefix}市" if full.endswith("市") else (f"{loc_prefix}自治州" if full.endswith("自治州") else f"{loc_prefix}盟")
                    elif level_type == "county":
                        masked = f"{loc_prefix}{full[-1]}"
                    elif level_type == "town":
                        masked = f"{loc_prefix}街道" if full.endswith("街道") else (f"{loc_prefix}镇" if full.endswith("镇") else f"{loc_prefix}乡")
                    elif level_type == "village":
                        if full.endswith("居民委员会"):
                            masked = f"{loc_prefix}社区居民委员会"
                        elif full.endswith("居委会"):
                            masked = f"{loc_prefix}社区居委会"
                        elif full.endswith("村民委员会"):
                            masked = f"{loc_prefix}村民委员会"
                        elif full.endswith("村委会"):
                            masked = f"{loc_prefix}村委会"
                        elif full.endswith("社区"):
                            masked = f"{loc_prefix}社区"
                        else:
                            masked = f"{loc_prefix}村"
                    
                    mappings.append(MappingEntry(type="location", original=full, masked=masked, role=None, source="geoname_hierarchy", confidence=0.95, restore_by_default=True))
                    if core != full:
                        mappings.append(MappingEntry(type="location", original=core, masked=masked, role=None, source="geoname_hierarchy_core", confidence=0.95, restore_by_default=True))
            else:
                if full not in seen_orgs_and_exclusions:
                    loc_prefix = get_loc_prefix(full)
                    if level_type == "province":
                        masked = f"{loc_prefix}省" if full.endswith("省") else f"{loc_prefix}自治区"
                    elif level_type == "city":
                        masked = f"{loc_prefix}市" if full.endswith("市") else (f"{loc_prefix}自治州" if full.endswith("自治州") else f"{loc_prefix}盟")
                    elif level_type == "county":
                        masked = f"{loc_prefix}{full[-1]}"
                    elif level_type == "town":
                        masked = f"{loc_prefix}街道" if full.endswith("街道") else (f"{loc_prefix}镇" if full.endswith("镇") else f"{loc_prefix}乡")
                    elif level_type == "village":
                        if full.endswith("居民委员会"):
                            masked = f"{loc_prefix}社区居民委员会"
                        elif full.endswith("居委会"):
                            masked = f"{loc_prefix}社区居委会"
                        elif full.endswith("村民委员会"):
                            masked = f"{loc_prefix}村民委员会"
                        elif full.endswith("村委会"):
                            masked = f"{loc_prefix}村委会"
                        elif full.endswith("社区"):
                            masked = f"{loc_prefix}社区"
                        else:
                            masked = f"{loc_prefix}村"
                    mappings.append(MappingEntry(type="location", original=full, masked=masked, role=None, source="geoname_hierarchy", confidence=0.95, restore_by_default=True))

    register_level(prov_list, "province")
    register_level(city_list, "city")
    register_level(county_list, "county")
    register_level(town_list, "town")
    register_level(village_list, "village")

    return mappings


@dataclass
class _RedactionContext:
    """Shared mutable state threaded through the legacy and linear redaction paths.

    Holds the cross-step accumulators (mappings, counters, prefix registries, LLM
    analysis, etc.) so the previously monolithic ``redact``/``_redact_linear``
    bodies can be decomposed into single-responsibility step functions. Step-local
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
    sample_blacklist: set[str] = field(default_factory=set)
    sample_mappings: list[MappingEntry] = field(default_factory=list)
    trusted_org_short_names: set[str] = field(default_factory=set)
    base_mappings: list[MappingEntry] = field(default_factory=list)
    location_prefixes: dict[str, str] = field(default_factory=dict)
    admin_prefixes: dict[str, str] = field(default_factory=dict)
    # legacy-only
    high_conf_spans: list[tuple[int, int]] = field(default_factory=list)
    fallback_persons: list[Candidate] = field(default_factory=list)
    fallback_orgs: list[Candidate] = field(default_factory=list)
    analysis: dict[str, Any] = field(default_factory=dict)
    # linear-only
    fixed_regex_mappings: list[MappingEntry] = field(default_factory=list)
    admin_candidates: list[Candidate] = field(default_factory=list)
    admin_spans: list[tuple[int, int, str]] = field(default_factory=list)
    hanlp_candidates: list[Candidate] = field(default_factory=list)
    review_candidates: list[Candidate] = field(default_factory=list)
    sentence_extraction_mode: bool = False
    sentence_extraction_success: bool = False
    llm_extraction_failed: bool = False

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

    def overlaps_high_conf(self, start: int, end: int) -> bool:
        return any(not (end <= s or start >= e) for s, e in self.high_conf_spans)


# ── Legacy path steps ──────────────────────────────────────────

def _legacy_init_ctx(pipeline, text, source_file, prov_mapping, base_redaction_map) -> _RedactionContext:
    profile = pipeline._profile
    ctx = _RedactionContext(text=text, source_file=source_file, profile=profile, counters=TypeCounters())
    ctx.prov_mapping = prov_mapping if prov_mapping is not None else {}

    # 确定扫描的文本范围：只扫描到“本院认为”之前（查明事实部分），极大地提高大模型和匹配引擎的效率与准确率
    boundary_match = re.search(r"本院(?:经审理|经审查|审理)?认为", text)
    ctx.scan_text = text[: boundary_match.start()] if boundary_match else text

    # 0. 加载本地样本库的精准匹配词与黑名单
    if pipeline.config.enable_sample_library:
        ctx.sample_blacklist = set()
        ctx.sample_mappings = [
            mapping
            for mapping in load_trusted_sample_mappings()
            if mapping.original in text and _candidate_allowed(mapping.type, profile)
        ]
    else:
        ctx.sample_blacklist = set()
        ctx.sample_mappings = []

    ctx.trusted_org_short_names = _trusted_organization_short_names(ctx.sample_mappings)
    ctx.base_mappings = list(base_redaction_map.mappings) if (base_redaction_map and base_redaction_map.mappings) else []
    return ctx


def _legacy_seed_base_prefixes(ctx) -> None:
    for m in ctx.base_mappings:
        if m.type == "location" and m.masked:
            core = get_location_core(m.original)
            prefix_match = re.match(r"^([A-Z]|[一-龥]+)", m.masked)
            if prefix_match:
                pfx = prefix_match.group(1)
                if pfx != "某" and len(pfx) == 1:
                    ctx.location_prefixes[core] = pfx


def _legacy_collect_regex_high_risk(pipeline, ctx, text) -> None:
    # 1. 提取 Regex 候选 (高风险数字类，包括案号、手机号、身份证、信用代码等)
    if pipeline.config.enable_regex:
        c_regex = detect_standard_regex_candidates(text)
        for c in c_regex:
            if c.text in ctx.sample_blacklist:
                continue
            if _candidate_allowed(c.type, ctx.profile):
                ctx.high_conf_spans.append((c.start, c.end))
                masked = "***"
                if c.type == "case_number":
                    masked = map_case_number(c.text, ctx.prov_mapping)
                ctx.mappings.append(MappingEntry(
                    type=c.type,
                    original=c.text,
                    masked=masked,
                    role=None,
                    source=c.source,
                    confidence=c.confidence,
                    restore_by_default=False
                ))


def _legacy_collect_geonames(pipeline, ctx) -> None:
    # 1.3. 基于人类级联替换逻辑，扫描全文并建立全国地名全称与核心词的一致性映射
    if pipeline.config.enable_heuristic_ner:
        geoname_mappings = extract_and_map_geonames(
            ctx.scan_text,
            ctx.get_location_prefix,
            ctx.profile,
            ctx.sample_blacklist,
            hebei_admin_detector=pipeline.hebei_admin_detector,
            china_admin_detector=pipeline.china_admin_detector,
        )
        ctx.mappings.extend(geoname_mappings)


def _legacy_collect_admin_candidates(pipeline, ctx) -> None:
    # 1.5. Administrative division database candidates (Hebei detail + nationwide 三级)
    admin_span_buffer: list[tuple[int, int, str]] = []
    for detector in (pipeline.hebei_admin_detector, pipeline.china_admin_detector):
        if detector is None:
            continue
        for candidate in detector.detect(ctx.scan_text):
            before = len(ctx.mappings)
            _append_admin_detection(
                candidate,
                profile=ctx.profile,
                sample_blacklist=ctx.sample_blacklist,
                mappings=ctx.mappings,
                admin_spans=admin_span_buffer,
                get_location_prefix=ctx.get_location_prefix,
                get_admin_prefix=ctx.get_admin_prefix,
            )
            if len(ctx.mappings) > before:
                ctx.high_conf_spans.append((candidate.start, candidate.end))
    if pipeline.config.enable_china_admin_rules:
        for candidate in detect_china_admin_rule_candidates(ctx.scan_text):
            if ctx.overlaps_high_conf(candidate.start, candidate.end):
                continue
            before = len(ctx.mappings)
            _append_admin_detection(
                candidate,
                profile=ctx.profile,
                sample_blacklist=ctx.sample_blacklist,
                mappings=ctx.mappings,
                admin_spans=admin_span_buffer,
                get_location_prefix=ctx.get_location_prefix,
                get_admin_prefix=ctx.get_admin_prefix,
            )
            if len(ctx.mappings) > before:
                ctx.high_conf_spans.append((candidate.start, candidate.end))


def _legacy_collect_fallback_persons_orgs(pipeline, ctx) -> None:
    # 2. 提取所有的启发式/规则候选（包括当事人解析、启发式 NER、人名兜底）
    fallback_persons: list[Candidate] = []
    fallback_orgs: list[Candidate] = []
    if pipeline.config.enable_party_parser:
        party_c, _ = detect_party_candidates(ctx.scan_text)
        fallback_persons.extend(
            c
            for c in party_c
            if c.type == "person"
            and c.text not in ctx.sample_blacklist
            and c.text not in ctx.trusted_org_short_names
            and not ctx.overlaps_high_conf(c.start, c.end)
        )
        fallback_orgs.extend(c for c in party_c if c.type == "organization" and c.text not in ctx.sample_blacklist and not ctx.overlaps_high_conf(c.start, c.end))
    if pipeline.config.enable_heuristic_ner:
        ner_c = detect_heuristic_ner_candidates(ctx.scan_text)
        fallback_persons.extend(
            c
            for c in ner_c
            if c.type == "person"
            and c.text not in ctx.sample_blacklist
            and c.text not in ctx.trusted_org_short_names
            and not ctx.overlaps_high_conf(c.start, c.end)
        )
        fallback_orgs.extend(c for c in ner_c if c.type == "organization" and c.text not in ctx.sample_blacklist and not ctx.overlaps_high_conf(c.start, c.end))
        fallback_persons.extend(
            c
            for c in detect_fallback_person_candidates(ctx.scan_text)
            if c.text not in ctx.sample_blacklist
            and c.text not in ctx.trusted_org_short_names
            and not ctx.overlaps_high_conf(c.start, c.end)
        )
    ctx.fallback_persons = fallback_persons
    ctx.fallback_orgs = fallback_orgs


def _legacy_run_llm_audit_and_calibrate(pipeline, ctx) -> None:
    # 3. 如果启用了本地 LLM，在调用前构造待验证的候选列表
    analysis = {"locations": [], "companies": [], "persons": [], "reject": [], "calibrate": {}}
    verify_list = []
    seen_entities = set()
    for c in ctx.fallback_persons:
        if len(c.text) >= 2 and c.text not in seen_entities:
            seen_entities.add(c.text)
            meta_ctx = c.metadata.get("context", "") if c.metadata else ""
            verify_list.append({"text": c.text, "type": "person", "context": meta_ctx[:150]})

    seen_orgs = set()
    for c in ctx.fallback_orgs:
        if len(c.text) >= 2 and c.text not in seen_orgs:
            seen_orgs.add(c.text)
            meta_ctx = c.metadata.get("context", "") if c.metadata else ""
            verify_list.append({"text": c.text, "type": "organization", "context": meta_ctx[:150]})

    # 发起合并的单个 LLM 审计与验证调用
    if pipeline.config.enable_local_llm and pipeline.config.local_llm.enabled:
        from .llm import LegalEntityAuditor
        auditor = LegalEntityAuditor(pipeline.config.local_llm)
        analysis = auditor.audit_and_verify(ctx.scan_text, verify_list, enable_samples=pipeline.config.enable_sample_library)
        if analysis.get("error"):
            ctx.warnings.append(str(analysis["error"]))

    # Extract calibrations mapping (candidates -> cleaned entities)
    calibrations = analysis.get("calibrate", {})
    if not isinstance(calibrations, dict):
        calibrations = {}

    # Apply calibrations only when the corrected entity can be located in the source.
    def calibrate_candidate_list(cand_list):
        calibrated = []
        for c in cand_list:
            if c.text in calibrations:
                calibrated_text = calibrations[c.text].strip()
                if not calibrated_text or len(calibrated_text) < 2:
                    continue
                start_idx = c.text.find(calibrated_text)
                if start_idx != -1:
                    new_start = c.start + start_idx
                    new_end = new_start + len(calibrated_text)
                    calibrated.append(replace(c, text=calibrated_text, start=new_start, end=new_end))
                else:
                    context_start = max(0, c.start - 80)
                    context_end = min(len(ctx.scan_text), c.end + 80)
                    nearby_idx = ctx.scan_text.find(calibrated_text, context_start, context_end)
                    if nearby_idx != -1:
                        calibrated.append(
                            replace(
                                c,
                                text=calibrated_text,
                                start=nearby_idx,
                                end=nearby_idx + len(calibrated_text),
                            )
                        )
                    else:
                        calibrated.append(c)
            else:
                calibrated.append(c)
        return calibrated

    ctx.fallback_persons = calibrate_candidate_list(ctx.fallback_persons)
    ctx.fallback_orgs = calibrate_candidate_list(ctx.fallback_orgs)
    ctx.analysis = analysis


def _legacy_process_llm_entities(pipeline, ctx, text) -> None:
    # 4. 汇总处理地名/机构/人名
    known_orgs = set()

    # 处理 LLM 提取的机构
    for comp in ctx.analysis.get("companies", []):
        brand = comp.get("brand")
        if brand:
            brand = _clean_organization_text(brand)
            if brand.startswith("实") and len(brand) >= 2:
                for prefix in ("确", "其", "证", "落", "真", "事"):
                    if prefix + brand in text:
                        brand = brand[1:]
                        break
        if not brand or len(brand) < 2 or brand in ctx.sample_blacklist or _is_false_org(brand):
            continue
        if _candidate_allowed("organization", ctx.profile):
            if brand not in GENERIC_BRAND_BLACKLIST:
                prefix = ctx.counters.next("group_prefix")
                ctx.mappings.append(MappingEntry(type="organization", original=brand, masked=prefix, role=None, source="local_llm", confidence=0.95, restore_by_default=True))
                known_orgs.add(brand)
                for variant in comp.get("variants", []):
                    if isinstance(variant, str):
                        variant = _clean_organization_text(variant)
                        if variant.startswith("实") and len(variant) >= 2:
                            for prefix in ("确", "其", "证", "落", "真", "事"):
                                if prefix + variant in text:
                                    variant = variant[1:]
                                    break
                        if len(variant) > len(brand) and variant not in ctx.sample_blacklist and not _is_false_org(variant):
                            masked_var = f"{prefix}公司"
                            ctx.mappings.append(MappingEntry(type="organization", original=variant, masked=masked_var, role=None, source="local_llm_variant", confidence=0.95, restore_by_default=True))
                            known_orgs.add(variant)
            else:
                # 属于通用行业字眼，只对它的完整变体/全名进行脱敏，避免误伤
                prefix = ctx.counters.next("group_prefix")
                for variant in comp.get("variants", []):
                    if isinstance(variant, str):
                        variant = _clean_organization_text(variant)
                        if variant.startswith("实") and len(variant) >= 2:
                            for prefix in ("确", "其", "证", "落", "真", "事"):
                                if prefix + variant in text:
                                    variant = variant[1:]
                                    break
                        if variant not in ctx.sample_blacklist and not _is_false_org(variant):
                            masked_var = f"{prefix}公司"
                            ctx.mappings.append(MappingEntry(type="organization", original=variant, masked=masked_var, role=None, source="local_llm_variant", confidence=0.95, restore_by_default=True))
                            known_orgs.add(variant)

    # 处理地名
    loc_entries = []
    for loc in ctx.analysis.get("locations", []):
        full = loc.get("full")
        core = loc.get("core")
        if not full or not core or full in ctx.sample_blacklist or core in ctx.sample_blacklist:
            continue
        if not _candidate_allowed("location", ctx.profile):
            continue

        loc_prefix = ctx.get_location_prefix(core)

        if full.endswith(("省", "自治区")):
            masked = f"{loc_prefix}省"
        elif full.endswith(("市", "自治州", "盟")):
            masked = f"{loc_prefix}市"
        elif full.endswith(("区", "县", "旗")):
            masked = f"{loc_prefix}{full[-1]}"
        elif full.endswith(("镇", "乡")):
            masked = f"{loc_prefix}{full[-1]}"
        elif full.endswith(("街道", "村", "社区")):
            if full.endswith("街道"):
                masked = f"{loc_prefix}街道"
            elif full.endswith("社区"):
                masked = f"{loc_prefix}社区"
            else:
                masked = f"{loc_prefix}村"
        else:
            masked = f"{loc_prefix}地"

        loc_entries.append((full, masked))
        if len(core) >= 2 and core != full:
            loc_entries.append((core, masked))

    for orig, mask in loc_entries:
        if orig in ctx.sample_blacklist:
            continue
        ctx.mappings.append(MappingEntry(type="location", original=orig, masked=mask, role=None, source="local_llm", confidence=0.95, restore_by_default=True))

    # 处理人名
    person_names = set()
    person_entries = []
    # 百家姓用于高可信度汉人姓名校验
    common_surnames = frozenset(
        "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
        "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳史唐"
        "费薛雷贺倪汤罗毕郝安常于时傅齐康伍余元顾孟平黄和萧尹姚邵汪祁毛"
        "狄米明计成戴谈宋庞熊纪舒屈项祝董梁杜阮蓝季强贾路娄危江童颜郭梅盛林"
        "钟徐邱骆高夏蔡田樊胡凌霍万柯管卢莫经房裘干解应宗丁宣邓郁单洪包诸左"
        "石崔吉龚程邢裴陆荣翁惠甄曲家封储松段富巫焦巴弓秋仲伊宁仇暴甘厉戎祖"
        "武符刘景詹龙叶幸司黎薄白从赖卓屠池乔阴能苍双闻党谭贡劳姬申冉郦"
        "桂牛寿通边燕浦尚农温庄晏柴瞿阎慕连茹习艾向古易戈廖终居衡步都耿满弘"
        "国文寇广禄阙东欧利师巩聂勾融冷辛简饶空曾沙养鞠须丰巢关查后荆红游权"
        "盖益公万俟司马上官欧阳夏侯诸葛闻人东方赫连皇甫尉迟公羊澹台公冶宗政"
        "濮阳淳于单于太叔申屠公孙仲孙轩辕令狐钟离宇文长孙慕容鲜于闾丘司徒司空"
        "端木巫马公西漆雕乐正拓跋夹谷谷梁晋楚闫法涂钦呼延羊舌岳帅有琴梁丘左丘"
        "南宫"
    )
    for person in ctx.analysis.get("persons", []):
        raw_name = person.get("name")
        surname = person.get("surname")
        if not raw_name or not surname or raw_name in ctx.sample_blacklist:
            continue
        name = _clean_person_name(raw_name)
        if _is_false_person(name):
            continue
        # ── 过滤明显的大模型抽取幻觉/长句误切 ──
        if len(name) > 6 or len(name) < 2:
            continue
        if any(char in name for char in "，。；、：:,\r\n"):
            continue
        # 过滤包含数字、百分号或万元币值特征的伪名字
        if any(char.isdigit() or char in "0123456789０１２３４５６７８９.%‰" for char in name):
            continue
        if "元" in name and ("万" in name or "亿" in name):
            continue
        # 含"某"字的是已脱敏占位符，不应二次匹配
        if "某" in name:
            continue
        # 必须符合常见的汉人名字长度（2-4字）且姓氏在常用百家姓中，或者少数民族带点人名（如 阿不都·艾山）
        is_valid_han = len(name) <= 4 and (name[0] in common_surnames or (len(name) > 2 and name[:2] in common_surnames))
        is_valid_minority = "·" in name and len(name) <= 15
        if not (is_valid_han or is_valid_minority):
            continue

        person_names.add(name)
        person_entries.append((name, surname, "local_llm", 0.95))

    # 获取 LLM 裁判认定的误匹配排除集合
    rejected_names = set(ctx.analysis.get("reject", []))

    # 启发式人名补充与 LLM 裁判过滤
    for c in ctx.fallback_persons:
        if (
            c.text not in person_names
            and c.text not in rejected_names
            and c.text not in ctx.sample_blacklist
            and c.text not in ctx.trusted_org_short_names
        ):
            person_names.add(c.text)
            surname = c.text[0]
            person_entries.append((c.text, surname, c.source, c.confidence))

    # 启发式机构名补充与 LLM 裁判过滤
    if _candidate_allowed("organization", ctx.profile):
        for c in ctx.fallback_orgs:
            if _is_false_org(c.text):
                continue
            if c.text not in known_orgs and c.text not in rejected_names and c.text not in ctx.sample_blacklist:
                known_orgs.add(c.text)
                b, _, _ = _parse_company_name(c.text)
                if b:
                    b = _clean_organization_text(b)
                    # 针对特定前缀残余字符进行裁剪优化
                    if b.startswith("实") and len(b) >= 2:
                        for prefix in ("确", "其", "证", "落", "真", "事"):
                            if prefix + b in text:
                                b = b[1:]
                                break
                    if not b or len(b) < 2 or b in ctx.sample_blacklist or _is_false_org(b):
                        continue
                    if len(b) >= 2 and b not in GENERIC_BRAND_BLACKLIST:
                        if b not in ctx.sample_blacklist:
                            prefix = ctx.counters.next("group_prefix")
                            ctx.mappings.append(MappingEntry(type="organization", original=b, masked=prefix, role=None, source="fallback_org_brand", confidence=c.confidence, restore_by_default=True))

                            # ── 彻底消除带噪声前缀的公司名（如“严重违反公司”） ──
                            cleaned_c = _clean_organization_text(c.text)
                            if cleaned_c and not _is_false_org(cleaned_c) and cleaned_c != b:
                                ctx.mappings.append(MappingEntry(type="organization", original=cleaned_c, masked=f"{prefix}公司", role=None, source=c.source, confidence=c.confidence, restore_by_default=True))
                        else:
                            cleaned_c = _clean_organization_text(c.text)
                            if cleaned_c and not _is_false_org(cleaned_c):
                                prefix = ctx.counters.next("group_prefix")
                                ctx.mappings.append(MappingEntry(type="organization", original=cleaned_c, masked=f"{prefix}公司", role=None, source=c.source, confidence=c.confidence, restore_by_default=True))
                    else:
                        cleaned_c = _clean_organization_text(c.text)
                        if cleaned_c and not _is_false_org(cleaned_c):
                            prefix = ctx.counters.next("group_prefix")
                            ctx.mappings.append(MappingEntry(type="organization", original=cleaned_c, masked=f"{prefix}公司", role=None, source=c.source, confidence=c.confidence, restore_by_default=True))

    if _candidate_allowed("person", ctx.profile):
        for name, surname, source, confidence in person_entries:
            if name in ctx.sample_blacklist or name in ctx.trusted_org_short_names:
                continue
            masked = f"{surname}某{ctx.counters.next(f'person_{surname}')}"
            ctx.mappings.append(MappingEntry(type="person", original=name, masked=masked, role=None, source=source, confidence=confidence, restore_by_default=True))


def _legacy_finalize(pipeline, ctx, text) -> RedactionResult:
    # 5. 去重并应用 Mapping (按原文长度倒序)
    unique_mappings = []
    seen_orig = set()
    for m in ctx.base_mappings:
        if m.original not in seen_orig:
            seen_orig.add(m.original)
            unique_mappings.append(m)

    for m in sorted(ctx.sample_mappings, key=lambda x: len(x.original), reverse=True):
        if m.original in ctx.sample_blacklist:
            continue
        if m.original not in seen_orig:
            seen_orig.add(m.original)
            unique_mappings.append(m)

    for m in sorted(ctx.mappings, key=lambda x: len(x.original), reverse=True):
        if m.original in ctx.sample_blacklist:
            continue
        if m.original not in seen_orig:
            seen_orig.add(m.original)
            unique_mappings.append(m)

    unique_mappings = _filter_mappings_inside_trusted_samples(text, unique_mappings)
    unique_mappings = _filter_locations_inside_organizations(text, unique_mappings, ctx.sample_blacklist)
    unique_mappings = _filter_org_alias_prefixed_locations(unique_mappings)
    unique_mappings = _filter_fragments_inside_longer_entities(text, unique_mappings)
    unique_mappings = _filter_noise_entity_mappings(unique_mappings)

    redacted_text = pipeline.apply_mappings(text, unique_mappings)
    redacted_text = remove_court_signatures(redacted_text)
    leaks = pipeline.scan_high_risk_leaks(redacted_text)

    redaction_map = RedactionMap.create(mappings=unique_mappings, mode=ctx.profile.name, source_file=ctx.source_file)

    return RedactionResult(
        original_text=text,
        redacted_text=redacted_text,
        redaction_map=redaction_map,
        candidates=[],
        review_candidates=[],
        leaks=leaks,
        mode=ctx.profile.name,
        warnings=ctx.warnings,
    )


# ── Linear path steps ──────────────────────────────────────────

def _linear_init_ctx(pipeline, text, source_file, prov_mapping, base_redaction_map) -> _RedactionContext:
    profile = pipeline._profile
    ctx = _RedactionContext(text=text, source_file=source_file, profile=profile, counters=TypeCounters())
    ctx.prov_mapping = prov_mapping if prov_mapping is not None else {}

    boundary_match = re.search(r"本院(?:经审理|经审查|审理)?认为", text)
    ctx.scan_text = text[: boundary_match.start()] if boundary_match else text

    if pipeline.config.enable_sample_library:
        ctx.sample_blacklist = set()
        ctx.sample_mappings = [
            mapping
            for mapping in load_trusted_sample_mappings()
            if mapping.original in text and _candidate_allowed(mapping.type, profile)
        ]
    else:
        ctx.sample_blacklist = set()
        ctx.sample_mappings = []

    ctx.trusted_org_short_names = _trusted_organization_short_names(ctx.sample_mappings)
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
            if candidate.text in ctx.sample_blacklist or not _candidate_allowed(candidate.type, ctx.profile):
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
            key=lambda item: (item.start, -item.length),
        ):
            before = len(ctx.mappings)
            _append_admin_detection(
                candidate,
                profile=ctx.profile,
                sample_blacklist=ctx.sample_blacklist,
                mappings=ctx.mappings,
                admin_spans=ctx.admin_spans,
                get_location_prefix=ctx.get_location_prefix,
                get_admin_prefix=ctx.get_admin_prefix,
            )
            if len(ctx.mappings) == before:
                continue


def _linear_collect_china_admin_candidates(pipeline, ctx) -> None:
    if pipeline.config.enable_china_admin_rules:
        for candidate in detect_china_admin_rule_candidates(ctx.scan_text):
            level = str(candidate.metadata.get("level", "") or "")
            if _span_overlaps_admin(ctx.admin_spans, candidate.start, candidate.end, level):
                continue
            ctx.admin_candidates.append(candidate)


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
            if candidate.text in ctx.sample_blacklist or not _candidate_allowed(candidate.type, ctx.profile):
                continue
            if candidate.type == "location" and candidate.text.startswith(("（", "(")):
                continue
            if any(
                not (candidate.end <= start or candidate.start >= end)
                for start, end, _level in ctx.admin_spans
            ):
                continue
            ctx.hanlp_candidates.append(candidate)


def _linear_run_sentence_extraction(pipeline, ctx, text):
    """Run LLM sentence-entity extraction when enabled.

    Returns a ``RedactionResult`` when the fail-open fallback short-circuits the
    whole redaction (``fail_open`` disabled); otherwise returns ``None`` and the
    caller proceeds with the rule engine.
    """

    def collect_heuristic_location_candidates() -> None:
        if not (pipeline.config.enable_heuristic_ner and ctx.profile.redact_locations):
            return
        for candidate in detect_heuristic_ner_candidates(ctx.scan_text):
            if candidate.type not in {"location", "grassroots_org"} or candidate.text in ctx.sample_blacklist:
                continue
            if any(
                not (candidate.end <= start or candidate.start >= end)
                for start, end, _level in ctx.admin_spans
            ):
                continue
            if len(candidate.text) > 8 or any(
                noise in candidate.text
                for noise in (
                    "银行", "保险", "公司", "集团", "法院", "检察院",
                    "农业农村", "产业开发", "技术开发",
                )
            ):
                continue
            ctx.admin_candidates.append(candidate)

    ctx.sentence_extraction_mode = (
        pipeline.config.enable_local_llm
        and pipeline.config.local_llm.enabled
        and (
            pipeline.config.local_llm.role == "sentence_entity_extraction"
            or (
                pipeline.config.semantic_llm_first
                and pipeline.config.local_llm.mode == "max-effect"
            )
        )
    )
    ctx.sentence_extraction_success = False
    ctx.review_candidates = []
    ctx.analysis = {
        "locations": [],
        "companies": [],
        "persons": [],
        "projects": [],
        "reject": [],
        "calibrate": {},
    }
    ctx.llm_extraction_failed = False

    if ctx.sentence_extraction_mode:
        from .llm import LegalEntityAuditor

        auditor = LegalEntityAuditor(pipeline.config.local_llm)
        ctx.analysis = auditor.extract_sentence_entities(
            ctx.scan_text,
            enable_samples=pipeline.config.enable_sample_library,
        )
        if ctx.analysis.get("error"):
            ctx.llm_extraction_failed = True
            if not pipeline.config.local_llm.fail_open:
                ctx.warnings.append(
                    f"整句 LLM 识别失败，已仅保留固定结构化正则脱敏：{ctx.analysis['error']}"
                )
                unique_mappings: list[MappingEntry] = []
                seen_originals: set[str] = set()
                for mapping in ctx.base_mappings:
                    if mapping.original in seen_originals:
                        continue
                    seen_originals.add(mapping.original)
                    unique_mappings.append(mapping)
                for mapping in sorted(ctx.sample_mappings, key=lambda item: len(item.original), reverse=True):
                    if mapping.original in seen_originals or mapping.original in ctx.sample_blacklist:
                        continue
                    seen_originals.add(mapping.original)
                    unique_mappings.append(mapping)
                for mapping in sorted(ctx.fixed_regex_mappings, key=lambda item: len(item.original), reverse=True):
                    if mapping.original in seen_originals or mapping.original in ctx.sample_blacklist:
                        continue
                    seen_originals.add(mapping.original)
                    unique_mappings.append(mapping)

                unique_mappings = _filter_mappings_inside_trusted_samples(text, unique_mappings)
                unique_mappings = _filter_locations_inside_organizations(text, unique_mappings, ctx.sample_blacklist)
                unique_mappings = _filter_org_alias_prefixed_locations(unique_mappings)
                unique_mappings = _filter_noise_entity_mappings(unique_mappings)

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
                    review_candidates=[],
                    leaks=leaks,
                    mode=ctx.profile.name,
                    warnings=ctx.warnings,
                )
            ctx.warnings.append(
                f"整句 LLM 识别失败，已降级为规则模式：{ctx.analysis['error']}"
            )
            ctx.analysis = {
                "locations": [],
                "companies": [],
                "persons": [],
                "projects": [],
                "reject": [],
                "calibrate": {},
            }
            collect_heuristic_location_candidates()
        elif ctx.analysis.get("_no_target_windows"):
            collect_heuristic_location_candidates()
        else:
            ctx.sentence_extraction_success = True
            batch_failures = ctx.analysis.get("_batch_failures")
            if isinstance(batch_failures, list) and batch_failures:
                ctx.warnings.append(
                    f"部分批次 LLM 识别失败（{len(batch_failures)} 批），已使用其余批次结果编排。"
                )
    else:
        collect_heuristic_location_candidates()
    return None


def _linear_run_engine(pipeline, ctx) -> None:
    engine = LinearRuleEngine(
        counters=ctx.counters,
        profile=ctx.profile,
        sample_blacklist=ctx.sample_blacklist,
        person_blacklist=ctx.trusted_org_short_names,
        get_location_prefix=ctx.get_location_prefix,
        use_semantic_rules=not ctx.sentence_extraction_success,
        llm_primary_discovery=ctx.sentence_extraction_success,
        use_china_admin_rules=pipeline.config.enable_china_admin_rules,
    )

    if not ctx.sentence_extraction_success:
        rule_candidates = engine.collect_candidates(ctx.scan_text, [*ctx.admin_candidates, *ctx.hanlp_candidates], {})
        review_candidates = [
            candidate
            for candidate in rule_candidates
            if _candidate_needs_llm_review(candidate)
        ]
        deduped_review_candidates: list[Candidate] = []
        seen_review_keys: set[tuple[str, str]] = set()
        for candidate in review_candidates:
            key = (candidate.type, candidate.text)
            if key in seen_review_keys:
                continue
            seen_review_keys.add(key)
            deduped_review_candidates.append(candidate)
        ctx.review_candidates = deduped_review_candidates[:80]

        if (
            pipeline.config.enable_local_llm
            and pipeline.config.local_llm.enabled
            and ctx.review_candidates
            and not ctx.llm_extraction_failed
        ):
            from .llm import LegalEntityAuditor

            auditor = LegalEntityAuditor(pipeline.config.local_llm)
            verify_list = [
                {
                    "text": candidate.text,
                    "type": candidate.type,
                    "context": candidate.metadata.get(
                        "context",
                        ctx.scan_text[
                            max(0, candidate.start - 60):
                            min(len(ctx.scan_text), candidate.end + 60)
                        ],
                    ),
                }
                for candidate in ctx.review_candidates
            ]
            ctx.analysis = auditor.audit_and_verify(
                ctx.scan_text,
                verify_list,
                enable_samples=pipeline.config.enable_sample_library,
            )
            if ctx.analysis.get("error"):
                ctx.warnings.append(str(ctx.analysis["error"]))

    ctx.mappings.extend(engine.discover(ctx.scan_text, [*ctx.admin_candidates, *ctx.hanlp_candidates], ctx.analysis))


def _linear_finalize(pipeline, ctx, text) -> RedactionResult:
    unique_mappings: list[MappingEntry] = []
    seen_originals: set[str] = set()
    for mapping in ctx.base_mappings:
        if mapping.original in seen_originals:
            continue
        seen_originals.add(mapping.original)
        unique_mappings.append(mapping)
    for mapping in sorted(ctx.sample_mappings, key=lambda item: len(item.original), reverse=True):
        if mapping.original in seen_originals or mapping.original in ctx.sample_blacklist:
            continue
        seen_originals.add(mapping.original)
        unique_mappings.append(mapping)
    for mapping in sorted(ctx.mappings, key=lambda item: len(item.original), reverse=True):
        if (
            mapping.original in seen_originals
            or mapping.original in ctx.sample_blacklist
        ):
            continue
        seen_originals.add(mapping.original)
        unique_mappings.append(mapping)

    unique_mappings = _filter_mappings_inside_trusted_samples(text, unique_mappings)
    unique_mappings = _filter_locations_inside_organizations(text, unique_mappings, ctx.sample_blacklist)
    unique_mappings = _filter_org_alias_prefixed_locations(unique_mappings)
    unique_mappings = _filter_noise_entity_mappings(unique_mappings)

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
    )


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
        }

    def redact(self, text: str, source_file: str | None = None, mode: str | None = None, prov_mapping: dict[str, str] | None = None, base_redaction_map: RedactionMap | None = None) -> RedactionResult:
        if mode is not None:
            config = replace(self.config, redaction_profile=RedactionProfile.from_preset(mode))
            self.config = config
        if self.config.strategy == "linear":
            return self._redact_linear(
                text,
                source_file=source_file,
                prov_mapping=prov_mapping,
                base_redaction_map=base_redaction_map,
            )

        # Legacy path: build shared context and run named single-responsibility steps.
        ctx = _legacy_init_ctx(self, text, source_file, prov_mapping, base_redaction_map)
        _legacy_seed_base_prefixes(ctx)
        _legacy_collect_regex_high_risk(self, ctx, text)
        _legacy_collect_geonames(self, ctx)
        _legacy_collect_admin_candidates(self, ctx)
        _legacy_collect_fallback_persons_orgs(self, ctx)
        _legacy_run_llm_audit_and_calibrate(self, ctx)
        _legacy_process_llm_entities(self, ctx, text)
        return _legacy_finalize(self, ctx, text)

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
        early = _linear_run_sentence_extraction(self, ctx, text)
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
        prov_mapping = {}
        for source_name, original_text in documents:
            res = self.redact(original_text, source_file=source_name, prov_mapping=prov_mapping, base_redaction_map=base_redaction_map)
            all_mappings.extend(res.redaction_map.mappings)
            if res.warnings:
                warnings.extend(res.warnings)
                
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
        unique_mappings = _filter_mappings_inside_trusted_samples(joined_text, unique_mappings)
        unique_mappings = _filter_locations_inside_organizations(joined_text, unique_mappings)
        unique_mappings = _filter_org_alias_prefixed_locations(unique_mappings)
        unique_mappings = _filter_fragments_inside_longer_entities(joined_text, unique_mappings)
        unique_mappings = _filter_noise_entity_mappings(unique_mappings)
        unique_mappings = _merge_organization_alias_mappings(unique_mappings)
                
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
        return BatchRedactionResult(
            documents=redacted_documents,
            redaction_map=unified_redaction_map,
            candidates=[],
            review_candidates=[],
            leaks=leaks,
            mode=profile.name,
            warnings=batch_warnings,
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
            if candidate.type not in HIGH_RISK_TYPES: continue
            if "某" in candidate.text or "***" in candidate.text: continue
            leaks.append(Leak(type=candidate.type, text=candidate.text, start=candidate.start, end=candidate.end, source=candidate.source, risk_level=candidate.risk_level))
        return leaks


def apply_redaction_map(text: str, redaction_map: RedactionMap) -> str:
    pipeline = RedactionPipeline()
    return pipeline.apply_redaction_map(text, redaction_map)


# ── Backward-compat aliases ─────────────────────────────────────────
# The mapping filter/merge pipeline has been relocated to .postprocess; these
# underscore aliases keep existing `from .pipeline import _filter_*` call sites
# (web_app, tests, and the four in-pipeline call sites until Phase 4 rewires
# them) working without changes.
from . import postprocess as _postprocess

_filter_locations_inside_organizations = _postprocess._filter_locations_inside_organizations
_filter_mappings_inside_trusted_samples = _postprocess._filter_mappings_inside_trusted_samples
_filter_noise_entity_mappings = _postprocess._filter_noise_entity_mappings
_filter_fragments_inside_longer_entities = _postprocess._filter_fragments_inside_longer_entities
_filter_org_alias_prefixed_locations = _postprocess._filter_org_alias_prefixed_locations
_merge_organization_alias_mappings = _postprocess._merge_organization_alias_mappings
