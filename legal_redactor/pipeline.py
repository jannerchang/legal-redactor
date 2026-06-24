from __future__ import annotations

import re
import random
from dataclasses import replace
from typing import Any

from .config import HIGH_RISK_TYPES, PipelineConfig, RedactionProfile
from .counters import TypeCounters
from .detectors import (
    detect_standard_regex_candidates,
    detect_party_candidates,
    detect_heuristic_ner_candidates,
    detect_fallback_person_candidates,
    remove_court_signatures,
    default_restore,
    _clean_org_simple,
    _is_false_org,
    _clean_organization_text,
    _FALSE_PERSON_WORDS,
    _clean_unbalanced_brackets,
    _clean_location_text,
    _clean_person_name,
    _is_false_person
)
from .hebei_admin import HebeiAdminDivisionDetector
from .models import BatchRedactionResult, Candidate, Leak, MappingEntry, RedactedDocument, RedactionMap, RedactionResult
from ._samples import load_all_samples, load_trusted_sample_mappings



# ── 行业与法律通用高频品牌词黑名单（防止超脱敏误伤普通词汇） ──
GENERIC_BRAND_BLACKLIST = {
    "开发", "建设", "工程", "集团", "贸易", "商贸", "物业", "投资", "科技",
    "信息", "网络", "电子商务", "电子", "新材料", "服务", "咨询", "代理",
    "管理", "资产", "金融", "工业", "农业", "商业", "联合", "发展", "实业",
    "劳务", "建筑", "装饰", "物流", "运输", "环保", "能源", "置业", "产业",
    "燃气", "水务", "热力", "供热", "供水", "排水", "电力", "交通", "运输"
}

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


def _get_location_core(name: str) -> str:
    """提取地名的核心部分，递归去除行政区划与基层组织后缀。"""
    if name.endswith("小镇"):
        return name
    suffixes = (
        "居民委员会", "村民委员会", "居委会", "村委会", "自治区",
        "自治州", "街道", "社区", "省", "市", "区", "县", "旗", "镇", "乡", "村"
    )
    core = name
    while True:
        stripped = False
        for sfx in suffixes:
            if core.endswith(sfx) and len(core) > len(sfx):
                if len(core) - len(sfx) >= 2:
                    core = core[:-len(sfx)]
                    stripped = True
                    break
        if not stripped:
            break
    return core


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
    prefix = get_admin_prefix(division_code, canonical_name or text)
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


def _candidate_needs_llm_review(candidate: Candidate) -> bool:
    source = candidate.source
    if source in {"fallback_person", "heuristic_ner", "linear_full_org", "linear_bare_org_alias"}:
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
    from .linear_engine import _derived_organization_alias_cores

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


def _span_inside_any(span: tuple[int, int], containers: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start >= c_start and end <= c_end for c_start, c_end in containers)


def _find_all_spans(text: str, needle: str) -> list[tuple[int, int]]:
    if not needle:
        return []
    spans: list[tuple[int, int]] = []
    start = text.find(needle)
    while start >= 0:
        spans.append((start, start + len(needle)))
        start = text.find(needle, start + 1)
    return spans


def _filter_locations_inside_organizations(
    text: str,
    mappings: list[MappingEntry],
    protected_texts: set[str] | None = None,
) -> list[MappingEntry]:
    """Drop location mappings that only occur inside organization or rejected phrases."""
    organization_spans: list[tuple[int, int]] = []
    for mapping in mappings:
        if mapping.type not in {"organization", "individual_business"}:
            continue
        organization_spans.extend(_find_all_spans(text, mapping.original))
    if protected_texts:
        for protected in protected_texts:
            if protected and len(protected) >= 2:
                organization_spans.extend(_find_all_spans(text, protected))
    if not organization_spans:
        return mappings

    filtered: list[MappingEntry] = []
    for mapping in mappings:
        if mapping.type not in {"location", "grassroots_org"}:
            filtered.append(mapping)
            continue
        spans = _find_all_spans(text, mapping.original)
        if spans and all(_span_inside_any(span, organization_spans) for span in spans):
            continue
        filtered.append(mapping)
    return filtered


def _filter_mappings_inside_trusted_samples(text: str, mappings: list[MappingEntry]) -> list[MappingEntry]:
    """Drop rule-discovered fragments that are fully covered by a trusted sample mapping."""
    trusted_spans: list[tuple[int, int, str]] = []
    for mapping in mappings:
        if not str(mapping.source or "").startswith("sample_library:"):
            continue
        if mapping.type not in {"organization", "individual_business", "location", "grassroots_org", "person", "project"}:
            continue
        for start, end in _find_all_spans(text, mapping.original):
            trusted_spans.append((start, end, mapping.original))
    if not trusted_spans:
        return mappings

    filtered: list[MappingEntry] = []
    for mapping in mappings:
        if str(mapping.source or "").startswith("sample_library:"):
            filtered.append(mapping)
            continue
        spans = _find_all_spans(text, mapping.original)
        if spans and all(
            any(start >= c_start and end <= c_end and mapping.original != container for c_start, c_end, container in trusted_spans)
            for start, end in spans
        ):
            continue
        filtered.append(mapping)
    return filtered


def _mapping_overrides_sample_blacklist(mapping: MappingEntry) -> bool:
    if mapping.source != "linear:linear_llm_exact":
        return False
    if mapping.type == "person":
        return bool(re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", mapping.original))
    if mapping.type == "organization":
        return mapping.original.endswith((
            "有限责任公司",
            "股份有限公司",
            "集团有限公司",
            "有限公司",
            "保险公司",
            "商业银行",
            "公司",
            "集团",
            "银行",
        ))
    return False


def _filter_fragments_inside_longer_entities(text: str, mappings: list[MappingEntry]) -> list[MappingEntry]:
    """Drop short model/rule fragments that only occur inside longer accepted entities."""
    container_types = {"organization", "individual_business", "project", "case_number", "person"}
    containers: list[tuple[int, int, str, str]] = []
    for mapping in mappings:
        if mapping.type not in container_types or len(mapping.original) < 3:
            continue
        for start, end in _find_all_spans(text, mapping.original):
            containers.append((start, end, mapping.original, mapping.type))
    if not containers:
        return mappings

    filtered: list[MappingEntry] = []
    for mapping in mappings:
        if str(mapping.source or "").startswith("sample_library:"):
            filtered.append(mapping)
            continue
        if (
            mapping.type == "person"
            and len(mapping.original) <= 2
            and any(
                mapping.original in container
                and mapping.original != container
                and c_type in {"organization", "individual_business", "person"}
                for _, _, container, c_type in containers
            )
        ):
            continue
        if mapping.type == "location" and mapping.original.startswith(("（", "(")):
            continue
        if mapping.type not in {"person", "location", "grassroots_org", "organization"}:
            filtered.append(mapping)
            continue
        if len(mapping.original) > 4 and not mapping.original.startswith("（"):
            filtered.append(mapping)
            continue
        spans = _find_all_spans(text, mapping.original)
        if not spans:
            filtered.append(mapping)
            continue
        if all(
            any(
                start >= c_start
                and end <= c_end
                and mapping.original != container
                and (
                    mapping.type != c_type
                    or mapping.type == "person"
                    or mapping.original.startswith("（")
                )
                for c_start, c_end, container, c_type in containers
            )
            for start, end in spans
        ):
            continue
        filtered.append(mapping)
    return filtered


def _filter_org_alias_prefixed_locations(mappings: list[MappingEntry]) -> list[MappingEntry]:
    """Drop pseudo-locations formed as organization alias + an already accepted location."""
    from .linear_engine import _derived_organization_alias_cores

    org_aliases: set[str] = set()
    location_originals = {
        mapping.original
        for mapping in mappings
        if mapping.type in {"location", "grassroots_org"} and len(mapping.original) >= 2
    }
    for mapping in mappings:
        if mapping.type != "organization":
            continue
        org_aliases.update(_derived_organization_alias_cores(mapping.original))

    if not org_aliases or not location_originals:
        return mappings

    filtered: list[MappingEntry] = []
    for mapping in mappings:
        if mapping.type not in {"location", "grassroots_org"}:
            filtered.append(mapping)
            continue
        original = mapping.original
        should_drop = False
        for alias in sorted(org_aliases, key=len, reverse=True):
            if not original.startswith(alias) or len(original) <= len(alias):
                continue
            suffix = original[len(alias):]
            if suffix in location_originals:
                should_drop = True
                break
        if not should_drop:
            filtered.append(mapping)
    return filtered


def _strip_organization_legal_suffix(value: str, legal_suffixes: tuple[str, ...]) -> tuple[str, str]:
    for suffix in sorted(legal_suffixes, key=len, reverse=True):
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)], suffix
    return value, ""


def _strip_organization_place_prefix(value: str, place_prefixes: set[str]) -> str:
    body = value
    for _ in range(3):
        stripped = False
        for prefix in sorted(place_prefixes, key=len, reverse=True):
            if body.startswith(prefix) and len(body) >= len(prefix) + 2:
                body = body[len(prefix) :]
                stripped = True
                break
        if not stripped:
            break
    return body


def _strip_organization_industry_suffix(value: str, industry_terms: tuple[str, ...]) -> str:
    body = value
    for term in sorted((*industry_terms, "建设", "工程", "电力", "能源"), key=len, reverse=True):
        if body.endswith(term) and len(body) >= len(term) + 2:
            return body[: -len(term)]
    return body


def _organization_number_aliases(value: str) -> set[str]:
    aliases: set[str] = set()
    cn_digits = {
        "1": "一",
        "2": "二",
        "3": "三",
        "4": "四",
        "5": "五",
        "6": "六",
        "7": "七",
        "8": "八",
        "9": "九",
        "10": "十",
    }
    for match in re.finditer(r"电建(?P<num>[一二三四五六七八九十]|\d{1,2})", value):
        num = cn_digits.get(match.group("num"), match.group("num"))
        aliases.add(f"{num}建")
    for match in re.finditer(r"第(?P<num>[一二三四五六七八九十]|\d{1,2})工程", value):
        num = cn_digits.get(match.group("num"), match.group("num"))
        aliases.add(f"{num}建")
    return aliases


def _usable_organization_alias_key(value: str, place_prefixes: set[str]) -> bool:
    if len(value) < 2 or len(value) > 16:
        return False
    if value in place_prefixes or value in GENERIC_BRAND_BLACKLIST:
        return False
    if not re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9·]+", value):
        return False
    return True


def _organization_alias_profile(
    mapping: MappingEntry,
    place_prefixes: set[str],
) -> dict[str, set[str] | str]:
    from .linear_engine import INDUSTRY_TERMS, LEGAL_SUFFIXES, _derived_organization_alias_cores

    cleaned = _clean_organization_text(mapping.original) or mapping.original.strip()
    cleaned = re.sub(r"\s+", "", cleaned.strip(" ：:，,。；;、\n\t"))
    cleaned = re.sub(r"[（(][^）)]{0,20}[）)]", "", cleaned)
    body, legal_suffix = _strip_organization_legal_suffix(cleaned, LEGAL_SUFFIXES)
    body = body.strip("（）() ")
    body_without_place = _strip_organization_place_prefix(body, place_prefixes)

    raw_cores = {body, body_without_place}
    raw_cores.update(_derived_organization_alias_cores(cleaned))

    tokens: set[str] = set()
    exact_alias_keys: set[str] = set()
    for core in raw_cores:
        core = re.sub(r"\s+", "", core.strip(" ：:，,。；;、（）()"))
        if not core:
            continue
        variants = {
            core,
            _strip_organization_place_prefix(core, place_prefixes),
        }
        for variant in list(variants):
            variants.add(_strip_organization_industry_suffix(variant, INDUSTRY_TERMS))
            variants.update(_organization_number_aliases(variant))
        for token in variants:
            token = token.strip(" ：:，,。；;、（）()")
            if _usable_organization_alias_key(token, place_prefixes):
                tokens.add(token)

    compact_body = _strip_organization_industry_suffix(body_without_place, INDUSTRY_TERMS)
    for alias_key in {body_without_place, compact_body, *_organization_number_aliases(body_without_place)}:
        alias_key = alias_key.strip(" ：:，,。；;、（）()")
        if (
            _usable_organization_alias_key(alias_key, place_prefixes)
            and len(alias_key) <= 3
            and (
                legal_suffix in {"公司", "集团", ""}
                or cleaned.endswith((f"{alias_key}公司", f"{alias_key}集团"))
            )
        ):
            exact_alias_keys.add(alias_key)

    return {
        "cleaned": cleaned,
        "tokens": tokens,
        "exact_alias_keys": exact_alias_keys,
    }


def _organization_canonical_score(mapping: MappingEntry) -> tuple[int, int, str]:
    source = str(mapping.source or "")
    original = mapping.original or ""
    masked = mapping.masked or ""
    score = 0
    if source.startswith("sample_library:"):
        score += 9000
    if mapping.role:
        score += 7000
    if "party_section" in source:
        score += 5000
    if original.endswith(("有限责任公司", "股份有限公司", "集团有限公司", "有限公司")):
        score += 1500
    elif original.endswith(("公司", "集团")):
        score += 500
    if masked.endswith("机构"):
        score -= 800
    if masked.endswith(("公司", "集团")):
        score += 100
    score += min(len(original), 80)
    return score, len(original), original


def _merge_organization_alias_mappings(mappings: list[MappingEntry]) -> list[MappingEntry]:
    """Make same-subject organization variants share one mask inside a batch map."""
    from .linear_engine import PROVINCE_NAMES

    org_indices = [index for index, mapping in enumerate(mappings) if mapping.type == "organization"]
    if len(org_indices) < 2:
        return mappings

    place_prefixes: set[str] = set()
    for province in PROVINCE_NAMES:
        place_prefixes.add(province)
        place_prefixes.add(f"{province}省")
    for mapping in mappings:
        if mapping.type not in {"location", "grassroots_org"}:
            continue
        original = _clean_unbalanced_brackets(mapping.original.strip(" ：:，,。；;、\n\t"))
        if 2 <= len(original) <= 10:
            place_prefixes.add(original)
        core = _get_location_core(original)
        if 2 <= len(core) <= 8:
            place_prefixes.add(core)

    profiles = {
        index: _organization_alias_profile(mappings[index], place_prefixes)
        for index in org_indices
    }
    exact_short_alias_keys = {
        key
        for profile in profiles.values()
        for key in profile["exact_alias_keys"]
        if isinstance(key, str)
    }

    parent = {index: index for index in org_indices}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    token_index: dict[str, list[int]] = {}
    for index, profile in profiles.items():
        tokens = profile["tokens"]
        if not isinstance(tokens, set):
            continue
        for token in tokens:
            if len(token) >= 4 or token in exact_short_alias_keys:
                token_index.setdefault(token, []).append(index)

    for indices in token_index.values():
        if len(indices) < 2:
            continue
        first = indices[0]
        for index in indices[1:]:
            union(first, index)

    for position, left in enumerate(org_indices):
        left_tokens = profiles[left]["tokens"]
        if not isinstance(left_tokens, set):
            continue
        for right in org_indices[position + 1 :]:
            right_tokens = profiles[right]["tokens"]
            if not isinstance(right_tokens, set):
                continue
            should_union = False
            for left_token in left_tokens:
                for right_token in right_tokens:
                    if left_token == right_token and (
                        len(left_token) >= 4 or left_token in exact_short_alias_keys
                    ):
                        should_union = True
                    else:
                        long_token, short_token = (
                            (left_token, right_token)
                            if len(left_token) >= len(right_token)
                            else (right_token, left_token)
                        )
                        if len(short_token) >= 4 and long_token.endswith(short_token):
                            should_union = True
                        elif short_token in exact_short_alias_keys and (
                            long_token.endswith(short_token)
                            or (
                                long_token.startswith(short_token)
                                and long_token[len(short_token) :] in place_prefixes
                            )
                        ):
                            should_union = True
                    if should_union:
                        break
                if should_union:
                    break
            if should_union:
                union(left, right)

    groups: dict[int, list[int]] = {}
    for index in org_indices:
        groups.setdefault(find(index), []).append(index)

    canonical_mask_by_index: dict[int, str] = {}
    for indices in groups.values():
        if len(indices) < 2:
            continue
        masks = {mappings[index].masked for index in indices}
        if len(masks) < 2:
            continue
        canonical = max((mappings[index] for index in indices), key=_organization_canonical_score)
        for index in indices:
            canonical_mask_by_index[index] = canonical.masked

    if not canonical_mask_by_index:
        return mappings

    merged: list[MappingEntry] = []
    for index, mapping in enumerate(mappings):
        canonical_mask = canonical_mask_by_index.get(index)
        if canonical_mask and mapping.masked != canonical_mask:
            merged.append(replace(mapping, masked=canonical_mask))
        else:
            merged.append(mapping)
    return merged


def extract_and_map_geonames(text: str, get_loc_prefix, profile, sample_blacklist, hebei_admin_detector=None) -> list[MappingEntry]:
    if not _candidate_allowed("location", profile):
        return []

    # 1. 收集所有显式地名候选
    candidates = []
    if hebei_admin_detector:
        candidates.extend(hebei_admin_detector.detect(text))
    
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
                prov_list.append((p_text, _get_location_core(p_text)))
            if m.group("city"):
                c_text = m.group("city")
                city_list.append((c_text, _get_location_core(c_text)))
            if m.group("county"):
                co_text = m.group("county")
                county_list.append((co_text, _get_location_core(co_text)))
            if m.group("town"):
                t_text = m.group("town")
                town_list.append((t_text, _get_location_core(t_text)))
            if m.group("village"):
                v_text = m.group("village")
                village_list.append((v_text, _get_location_core(v_text)))
        else:
            # 备用地名后缀归类
            level = None
            for suffix in ("省", "自治区"):
                if full.endswith(suffix) and len(full) > len(suffix):
                    prov_list.append((full, _get_location_core(full)))
                    level = "province"
                    break
            if not level:
                for suffix in ("市", "自治州", "盟"):
                    if full.endswith(suffix) and len(full) > len(suffix):
                        city_list.append((full, _get_location_core(full)))
                        level = "city"
                        break
            if not level:
                for suffix in ("区", "县", "旗"):
                    if full.endswith(suffix) and len(full) > len(suffix):
                        county_list.append((full, _get_location_core(full)))
                        level = "county"
                        break
            if not level:
                for suffix in ("街道", "镇", "乡"):
                    if full.endswith(suffix) and len(full) > len(suffix):
                        town_list.append((full, _get_location_core(full)))
                        level = "town"
                        break
            if not level:
                for suffix in ("居民委员会", "居委会", "村民委员会", "村委会", "社区", "村"):
                    if full.endswith(suffix) and len(full) > len(suffix):
                        village_list.append((full, _get_location_core(full)))
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


class RedactionPipeline:
    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or PipelineConfig()
        self.hebei_admin_detector = (
            HebeiAdminDivisionDetector(self.config.hebei_admin_db_path)
            if self.config.enable_hebei_admin_db else None
        )

    @property
    def _profile(self) -> RedactionProfile:
        return self.config.redaction_profile

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

        profile = self._profile
        warnings: list[str] = []
        mappings: list[MappingEntry] = []
        counters = TypeCounters()
        if prov_mapping is None:
            prov_mapping = {}

        # 确定扫描的文本范围：只扫描到“本院认为”之前（查明事实部分），极大地提高大模型和匹配引擎的效率与准确率
        scan_text = text
        boundary_match = re.search(r"本院(?:经审理|经审查|审理)?认为", text)
        if boundary_match:
            scan_text = text[:boundary_match.start()]

        # 统一地名脱敏前缀注册，确保同核心地名的缩写、全称使用相同的字母前缀（例如 河北省、河北 均脱敏为 甲省）
        location_prefixes: dict[str, str] = {}
        def get_loc_prefix(name: str) -> str:
            core = _get_location_core(name)
            if core not in location_prefixes:
                location_prefixes[core] = counters.next('location')
            return location_prefixes[core]

        admin_prefixes: dict[str, str] = {}
        def get_admin_prefix(division_code: str, name: str) -> str:
            core = _get_location_core(name)
            if division_code in admin_prefixes:
                return admin_prefixes[division_code]
            if core in location_prefixes:
                admin_prefixes[division_code] = location_prefixes[core]
                return admin_prefixes[division_code]
            prefix = get_loc_prefix(name)
            if division_code:
                admin_prefixes[division_code] = prefix
            return prefix

        # 0. 加载本地样本库的精准匹配词与黑名单
        if self.config.enable_sample_library:
            _, sample_blacklist = load_all_samples()
            sample_mappings = [
                mapping
                for mapping in load_trusted_sample_mappings()
                if mapping.original in text and _candidate_allowed(mapping.type, profile)
            ]
        else:
            sample_blacklist = set()
            sample_mappings = []

        base_mappings = []
        if base_redaction_map and base_redaction_map.mappings:
            base_mappings = list(base_redaction_map.mappings)
            for m in base_mappings:
                if m.type == "location" and m.masked:
                    core = _get_location_core(m.original)
                    prefix_match = re.match(r"^([A-Z]|[\u4e00-\u9fa5]+)", m.masked)
                    if prefix_match:
                        pfx = prefix_match.group(1)
                        if pfx != "某" and len(pfx) == 1:
                            location_prefixes[core] = pfx

        high_conf_spans = []

        # 1. 提取 Regex 候选 (高风险数字类，包括案号、手机号、身份证、信用代码等)
        if self.config.enable_regex:
            c_regex = detect_standard_regex_candidates(text)
            for c in c_regex:
                if c.text in sample_blacklist:
                    continue
                if _candidate_allowed(c.type, profile):
                    high_conf_spans.append((c.start, c.end))
                    masked = "***"
                    if c.type == "case_number":
                        masked = map_case_number(c.text, prov_mapping)
                    mappings.append(MappingEntry(
                        type=c.type,
                        original=c.text,
                        masked=masked,
                        role=None,
                        source=c.source,
                        confidence=c.confidence,
                        restore_by_default=False
                    ))

        # 1.3. 基于人类级联替换逻辑，扫描全文并建立全国地名全称与核心词的一致性映射
        if self.config.enable_heuristic_ner:
            geoname_mappings = extract_and_map_geonames(
                scan_text, get_loc_prefix, profile, sample_blacklist,
                hebei_admin_detector=self.hebei_admin_detector
            )
            mappings.extend(geoname_mappings)

        # 1.5. Hebei Admin Division Database Candidates
        if self.config.enable_hebei_admin_db and self.hebei_admin_detector:
            c_hebei = self.hebei_admin_detector.detect(scan_text)
            for c in c_hebei:
                if c.text in sample_blacklist:
                    continue
                allowed = False
                if c.type == "grassroots_org":
                    allowed = _candidate_allowed("location", profile) or _candidate_allowed("organization", profile)
                else:
                    allowed = _candidate_allowed(c.type, profile)

                if allowed:
                    high_conf_spans.append((c.start, c.end))
                    masked = _admin_candidate_mask(c, get_loc_prefix, get_admin_prefix)
                    mappings.append(MappingEntry(
                        type=c.type,
                        original=c.text,
                        masked=masked,
                        role=None,
                        source="hebei_admin_db",
                        confidence=c.confidence,
                        restore_by_default=True
                    ))

        def overlaps_high_conf(start: int, end: int) -> bool:
            return any(not (end <= s or start >= e) for s, e in high_conf_spans)

        # 2. 提取所有的启发式/规则候选（包括当事人解析、启发式 NER、人名兜底）
        fallback_persons: list[Candidate] = []
        fallback_orgs: list[Candidate] = []
        if self.config.enable_party_parser:
            party_c, _ = detect_party_candidates(scan_text)
            fallback_persons.extend(c for c in party_c if c.type == "person" and c.text not in sample_blacklist and not overlaps_high_conf(c.start, c.end))
            fallback_orgs.extend(c for c in party_c if c.type == "organization" and c.text not in sample_blacklist and not overlaps_high_conf(c.start, c.end))
        if self.config.enable_heuristic_ner:
            ner_c = detect_heuristic_ner_candidates(scan_text)
            fallback_persons.extend(c for c in ner_c if c.type == "person" and c.text not in sample_blacklist and not overlaps_high_conf(c.start, c.end))
            fallback_orgs.extend(c for c in ner_c if c.type == "organization" and c.text not in sample_blacklist and not overlaps_high_conf(c.start, c.end))
            fallback_persons.extend(c for c in detect_fallback_person_candidates(scan_text) if c.text not in sample_blacklist and not overlaps_high_conf(c.start, c.end))

        # 3. 如果启用了本地 LLM，在调用前构造待验证的候选列表
        analysis = {"locations": [], "companies": [], "persons": [], "reject": [], "calibrate": {}}
        verify_list = []
        seen_entities = set()
        for c in fallback_persons:
            if len(c.text) >= 2 and c.text not in seen_entities:
                seen_entities.add(c.text)
                ctx = c.metadata.get("context", "") if c.metadata else ""
                verify_list.append({"text": c.text, "type": "person", "context": ctx[:150]})
                
        seen_orgs = set()
        for c in fallback_orgs:
            if len(c.text) >= 2 and c.text not in seen_orgs:
                seen_orgs.add(c.text)
                ctx = c.metadata.get("context", "") if c.metadata else ""
                verify_list.append({"text": c.text, "type": "organization", "context": ctx[:150]})

        # 发起合并的单个 LLM 审计与验证调用
        if self.config.enable_local_llm and self.config.local_llm.enabled:
            from .llm import LegalEntityAuditor
            auditor = LegalEntityAuditor(self.config.local_llm)
            analysis = auditor.audit_and_verify(scan_text, verify_list, enable_samples=self.config.enable_sample_library)
            if analysis.get("error"):
                warnings.append(str(analysis["error"]))

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
                        context_end = min(len(scan_text), c.end + 80)
                        nearby_idx = scan_text.find(calibrated_text, context_start, context_end)
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

        fallback_persons = calibrate_candidate_list(fallback_persons)
        fallback_orgs = calibrate_candidate_list(fallback_orgs)

        # 4. 汇总处理地名/机构/人名
        known_orgs = set()
        
        # 处理 LLM 提取的机构
        for comp in analysis.get("companies", []):
            brand = comp.get("brand")
            if brand:
                brand = _clean_organization_text(brand)
                if brand.startswith("实") and len(brand) >= 2:
                    for prefix in ("确", "其", "证", "落", "真", "事"):
                        if prefix + brand in text:
                            brand = brand[1:]
                            break
            if not brand or len(brand) < 2 or brand in sample_blacklist or _is_false_org(brand):
                continue
            if _candidate_allowed("organization", profile):
                if brand not in GENERIC_BRAND_BLACKLIST:
                    prefix = counters.next("group_prefix")
                    mappings.append(MappingEntry(type="organization", original=brand, masked=prefix, role=None, source="local_llm", confidence=0.95, restore_by_default=True))
                    known_orgs.add(brand)
                    for variant in comp.get("variants", []):
                        if isinstance(variant, str):
                            variant = _clean_organization_text(variant)
                            if variant.startswith("实") and len(variant) >= 2:
                                for prefix in ("确", "其", "证", "落", "真", "事"):
                                    if prefix + variant in text:
                                        variant = variant[1:]
                                        break
                            if len(variant) > len(brand) and variant not in sample_blacklist and not _is_false_org(variant):
                                masked_var = f"{prefix}公司"
                                mappings.append(MappingEntry(type="organization", original=variant, masked=masked_var, role=None, source="local_llm_variant", confidence=0.95, restore_by_default=True))
                                known_orgs.add(variant)
                else:
                    # 属于通用行业字眼，只对它的完整变体/全名进行脱敏，避免误伤
                    prefix = counters.next("group_prefix")
                    for variant in comp.get("variants", []):
                        if isinstance(variant, str):
                            variant = _clean_organization_text(variant)
                            if variant.startswith("实") and len(variant) >= 2:
                                for prefix in ("确", "其", "证", "落", "真", "事"):
                                    if prefix + variant in text:
                                        variant = variant[1:]
                                        break
                            if variant not in sample_blacklist and not _is_false_org(variant):
                                masked_var = f"{prefix}公司"
                                mappings.append(MappingEntry(type="organization", original=variant, masked=masked_var, role=None, source="local_llm_variant", confidence=0.95, restore_by_default=True))
                                known_orgs.add(variant)

        # 处理地名
        loc_entries = []
        for loc in analysis.get("locations", []):
            full = loc.get("full")
            core = loc.get("core")
            if not full or not core or full in sample_blacklist or core in sample_blacklist:
                continue
            if not _candidate_allowed("location", profile):
                continue
            
            loc_prefix = get_loc_prefix(core)
                
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
            if orig in sample_blacklist:
                continue
            mappings.append(MappingEntry(type="location", original=orig, masked=mask, role=None, source="local_llm", confidence=0.95, restore_by_default=True))
            
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
        for person in analysis.get("persons", []):
            raw_name = person.get("name")
            surname = person.get("surname")
            if not raw_name or not surname or raw_name in sample_blacklist:
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
        rejected_names = set(analysis.get("reject", []))

        # 启发式人名补充与 LLM 裁判过滤
        for c in fallback_persons:
            if c.text not in person_names and c.text not in rejected_names and c.text not in sample_blacklist:
                person_names.add(c.text)
                surname = c.text[0]
                person_entries.append((c.text, surname, c.source, c.confidence))

        # 启发式机构名补充与 LLM 裁判过滤
        if _candidate_allowed("organization", profile):
            for c in fallback_orgs:
                if _is_false_org(c.text):
                    continue
                if c.text not in known_orgs and c.text not in rejected_names and c.text not in sample_blacklist:
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
                    if not b or len(b) < 2 or b in sample_blacklist or _is_false_org(b):
                        continue
                    if len(b) >= 2 and b not in GENERIC_BRAND_BLACKLIST:
                        if b not in sample_blacklist:
                            prefix = counters.next("group_prefix")
                            mappings.append(MappingEntry(type="organization", original=b, masked=prefix, role=None, source="fallback_org_brand", confidence=c.confidence, restore_by_default=True))
                            
                            # ── 彻底消除带噪声前缀的公司名（如“严重违反公司”） ──
                            cleaned_c = _clean_organization_text(c.text)
                            if cleaned_c and not _is_false_org(cleaned_c) and cleaned_c != b:
                                mappings.append(MappingEntry(type="organization", original=cleaned_c, masked=f"{prefix}公司", role=None, source=c.source, confidence=c.confidence, restore_by_default=True))
                        else:
                            cleaned_c = _clean_organization_text(c.text)
                            if cleaned_c and not _is_false_org(cleaned_c):
                                prefix = counters.next("group_prefix")
                                mappings.append(MappingEntry(type="organization", original=cleaned_c, masked=f"{prefix}公司", role=None, source=c.source, confidence=c.confidence, restore_by_default=True))
                    else:
                        cleaned_c = _clean_organization_text(c.text)
                        if cleaned_c and not _is_false_org(cleaned_c):
                            prefix = counters.next("group_prefix")
                            mappings.append(MappingEntry(type="organization", original=cleaned_c, masked=f"{prefix}公司", role=None, source=c.source, confidence=c.confidence, restore_by_default=True))

        if _candidate_allowed("person", profile):
            for name, surname, source, confidence in person_entries:
                if name in sample_blacklist:
                    continue
                masked = f"{surname}某{counters.next(f'person_{surname}')}"
                mappings.append(MappingEntry(type="person", original=name, masked=masked, role=None, source=source, confidence=confidence, restore_by_default=True))

        # 5. 去重并应用 Mapping (按原文长度倒序)
        unique_mappings = []
        seen_orig = set()
        for m in base_mappings:
            if m.original not in seen_orig:
                seen_orig.add(m.original)
                unique_mappings.append(m)

        for m in sorted(sample_mappings, key=lambda x: len(x.original), reverse=True):
            if m.original in sample_blacklist:
                continue
            if m.original not in seen_orig:
                seen_orig.add(m.original)
                unique_mappings.append(m)

        for m in sorted(mappings, key=lambda x: len(x.original), reverse=True):
            if m.original in sample_blacklist and not _mapping_overrides_sample_blacklist(m):
                continue
            if m.original not in seen_orig:
                seen_orig.add(m.original)
                unique_mappings.append(m)

        unique_mappings = _filter_mappings_inside_trusted_samples(text, unique_mappings)
        unique_mappings = _filter_locations_inside_organizations(text, unique_mappings, sample_blacklist)
        unique_mappings = _filter_org_alias_prefixed_locations(unique_mappings)
        unique_mappings = _filter_fragments_inside_longer_entities(text, unique_mappings)

        redacted_text = self.apply_mappings(text, unique_mappings)
        redacted_text = remove_court_signatures(redacted_text)
        leaks = self.scan_high_risk_leaks(redacted_text)
        
        redaction_map = RedactionMap.create(mappings=unique_mappings, mode=profile.name, source_file=source_file)

        return RedactionResult(
            original_text=text,
            redacted_text=redacted_text,
            redaction_map=redaction_map,
            candidates=[],
            review_candidates=[],
            leaks=leaks,
            mode=profile.name,
            warnings=warnings,
        )

    def _redact_linear(
        self,
        text: str,
        source_file: str | None = None,
        prov_mapping: dict[str, str] | None = None,
        base_redaction_map: RedactionMap | None = None,
    ) -> RedactionResult:
        from .linear_engine import LinearRuleEngine

        profile = self._profile
        warnings: list[str] = []
        counters = TypeCounters()
        prov_mapping = prov_mapping if prov_mapping is not None else {}

        boundary_match = re.search(r"本院(?:经审理|经审查|审理)?认为", text)
        scan_text = text[: boundary_match.start()] if boundary_match else text

        if self.config.enable_sample_library:
            _, sample_blacklist = load_all_samples()
            sample_mappings = [
                mapping
                for mapping in load_trusted_sample_mappings()
                if mapping.original in text and _candidate_allowed(mapping.type, profile)
            ]
        else:
            sample_blacklist = set()
            sample_mappings = []

        base_mappings = list(base_redaction_map.mappings) if base_redaction_map else []
        location_prefixes: dict[str, str] = {}
        for mapping in base_mappings:
            if mapping.type != "location" or not mapping.masked:
                continue
            core = _get_location_core(mapping.original)
            match = re.match(r"^([\u4e00-\u9fa5])", mapping.masked)
            if match and match.group(1) != "某":
                location_prefixes[core] = match.group(1)

        def get_location_prefix(name: str) -> str:
            core = _get_location_core(name)
            if core not in location_prefixes:
                location_prefixes[core] = counters.next("location")
            return location_prefixes[core]

        admin_prefixes: dict[str, str] = {}
        def get_admin_prefix(division_code: str, name: str) -> str:
            core = _get_location_core(name)
            if division_code in admin_prefixes:
                return admin_prefixes[division_code]
            if core in location_prefixes:
                admin_prefixes[division_code] = location_prefixes[core]
                return admin_prefixes[division_code]
            prefix = get_location_prefix(name)
            if division_code:
                admin_prefixes[division_code] = prefix
            return prefix

        mappings: list[MappingEntry] = []
        if self.config.enable_regex:
            for candidate in detect_standard_regex_candidates(text):
                if candidate.text in sample_blacklist or not _candidate_allowed(candidate.type, profile):
                    continue
                masked = (
                    map_case_number(candidate.text, prov_mapping)
                    if candidate.type == "case_number"
                    else "***"
                )
                mappings.append(
                    MappingEntry(
                        type=candidate.type,
                        original=candidate.text,
                        masked=masked,
                        role=None,
                        source=candidate.source,
                        confidence=candidate.confidence,
                        restore_by_default=False,
                    )
                )

        admin_candidates = []
        admin_spans: list[tuple[int, int]] = []
        if self.config.enable_hebei_admin_db and self.hebei_admin_detector:
            detected_admin = sorted(
                self.hebei_admin_detector.detect(scan_text),
                key=lambda candidate: (candidate.start, -candidate.length),
            )
            for candidate in detected_admin:
                if candidate.text in sample_blacklist:
                    continue
                if candidate.type == "grassroots_org":
                    allowed = profile.redact_locations or profile.redact_organizations
                else:
                    allowed = _candidate_allowed(candidate.type, profile)
                if not allowed:
                    continue
                admin_spans.append((candidate.start, candidate.end))
                mappings.append(
                    MappingEntry(
                        type=candidate.type,
                        original=candidate.text,
                        masked=_admin_candidate_mask(candidate, get_location_prefix, get_admin_prefix),
                        role=None,
                        source="hebei_admin_db",
                        confidence=candidate.confidence,
                        restore_by_default=True,
                    )
                )

        hanlp_candidates: list[Candidate] = []
        if self.config.enable_hanlp_ner:
            from .hanlp_ner import detect_hanlp_ner_candidates

            detected_hanlp, hanlp_error = detect_hanlp_ner_candidates(
                scan_text,
                model=self.config.hanlp_model,
                max_chars=self.config.hanlp_max_chars,
            )
            if hanlp_error:
                warnings.append(hanlp_error)
            for candidate in detected_hanlp:
                candidate = _as_project_candidate_if_needed(candidate)
                if candidate.text in sample_blacklist or not _candidate_allowed(candidate.type, profile):
                    continue
                if candidate.type == "location" and candidate.text.startswith(("（", "(")):
                    continue
                if any(
                    not (candidate.end <= start or candidate.start >= end)
                    for start, end in admin_spans
                ):
                    continue
                hanlp_candidates.append(candidate)

        def collect_heuristic_location_candidates() -> None:
            if not (self.config.enable_heuristic_ner and profile.redact_locations):
                return
            for candidate in detect_heuristic_ner_candidates(scan_text):
                if candidate.type not in {"location", "grassroots_org"} or candidate.text in sample_blacklist:
                    continue
                if any(
                    not (candidate.end <= start or candidate.start >= end)
                    for start, end in admin_spans
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
                admin_candidates.append(candidate)

        sentence_extraction_mode = (
            self.config.enable_local_llm
            and self.config.local_llm.enabled
            and (
                self.config.local_llm.role == "sentence_entity_extraction"
                or (
                    self.config.semantic_llm_first
                    and self.config.local_llm.mode == "max-effect"
                )
            )
        )
        sentence_extraction_success = False
        review_candidates: list[Candidate] = []
        analysis = {
            "locations": [],
            "companies": [],
            "persons": [],
            "projects": [],
            "reject": [],
            "calibrate": {},
        }

        if sentence_extraction_mode:
            from .llm import LegalEntityAuditor

            auditor = LegalEntityAuditor(self.config.local_llm)
            analysis = auditor.extract_sentence_entities(
                scan_text,
                enable_samples=self.config.enable_sample_library,
            )
            if analysis.get("error"):
                warnings.append(str(analysis["error"]))
                analysis = {
                    "locations": [],
                    "companies": [],
                    "persons": [],
                    "projects": [],
                    "reject": [],
                    "calibrate": {},
                }
                collect_heuristic_location_candidates()
            else:
                sentence_extraction_success = True
        else:
            collect_heuristic_location_candidates()

        if sentence_extraction_success and self.config.enable_local_llm and self.config.local_llm.enabled:
            llm_texts = _analysis_entity_texts(analysis)
            org_aliases = _organization_alias_cores_from_candidates(hanlp_candidates)
            review_candidates = [
                candidate
                for candidate in hanlp_candidates
                if candidate.text not in llm_texts
                and _hanlp_candidate_needs_sentence_review(candidate, org_aliases)
            ]
            deduped_review_candidates: list[Candidate] = []
            seen_review_keys: set[tuple[str, str]] = set()
            for candidate in review_candidates:
                key = (candidate.type, candidate.text)
                if key in seen_review_keys:
                    continue
                seen_review_keys.add(key)
                deduped_review_candidates.append(candidate)
            review_candidates = deduped_review_candidates[:60]
            if review_candidates:
                from .llm import LegalEntityAuditor

                auditor = LegalEntityAuditor(self.config.local_llm)
                verify_list = [
                    {
                        "text": candidate.text,
                        "type": candidate.type,
                        "context": candidate.metadata.get(
                            "context",
                            scan_text[
                                max(0, candidate.start - 60):
                                min(len(scan_text), candidate.end + 60)
                            ],
                        ),
                    }
                    for candidate in review_candidates
                ]
                review_analysis = auditor.audit_and_verify(
                    scan_text,
                    verify_list,
                    enable_samples=self.config.enable_sample_library,
                )
                if review_analysis.get("error"):
                    warnings.append(str(review_analysis["error"]))
                else:
                    analysis["reject"] = [
                        *analysis.get("reject", []),
                        *review_analysis.get("reject", []),
                    ]
                    calibrate = analysis.get("calibrate", {})
                    if not isinstance(calibrate, dict):
                        calibrate = {}
                    review_calibrate = review_analysis.get("calibrate", {})
                    if isinstance(review_calibrate, dict):
                        calibrate.update(review_calibrate)
                    analysis["calibrate"] = calibrate

        engine = LinearRuleEngine(
            counters=counters,
            profile=profile,
            sample_blacklist=sample_blacklist,
            get_location_prefix=get_location_prefix,
            use_semantic_rules=not sentence_extraction_success,
        )

        if not sentence_extraction_success:
            rule_candidates = engine.collect_candidates(scan_text, [*admin_candidates, *hanlp_candidates], {})
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
            review_candidates = deduped_review_candidates[:80]

            if self.config.enable_local_llm and self.config.local_llm.enabled and review_candidates:
                from .llm import LegalEntityAuditor

                auditor = LegalEntityAuditor(self.config.local_llm)
                verify_list = [
                    {
                        "text": candidate.text,
                        "type": candidate.type,
                        "context": candidate.metadata.get(
                            "context",
                            scan_text[
                                max(0, candidate.start - 60):
                                min(len(scan_text), candidate.end + 60)
                            ],
                        ),
                    }
                    for candidate in review_candidates
                ]
                analysis = auditor.audit_and_verify(
                    scan_text,
                    verify_list,
                    enable_samples=self.config.enable_sample_library,
                )
                if analysis.get("error"):
                    warnings.append(str(analysis["error"]))

        mappings.extend(engine.discover(scan_text, [*admin_candidates, *hanlp_candidates], analysis))

        unique_mappings: list[MappingEntry] = []
        seen_originals: set[str] = set()
        for mapping in base_mappings:
            if mapping.original in seen_originals:
                continue
            seen_originals.add(mapping.original)
            unique_mappings.append(mapping)
        for mapping in sorted(sample_mappings, key=lambda item: len(item.original), reverse=True):
            if mapping.original in seen_originals or mapping.original in sample_blacklist:
                continue
            seen_originals.add(mapping.original)
            unique_mappings.append(mapping)
        for mapping in sorted(mappings, key=lambda item: len(item.original), reverse=True):
            if (
                mapping.original in seen_originals
                or (
                    mapping.original in sample_blacklist
                    and not _mapping_overrides_sample_blacklist(mapping)
                )
            ):
                continue
            seen_originals.add(mapping.original)
            unique_mappings.append(mapping)

        unique_mappings = _filter_mappings_inside_trusted_samples(text, unique_mappings)
        unique_mappings = _filter_locations_inside_organizations(text, unique_mappings, sample_blacklist)
        unique_mappings = _filter_org_alias_prefixed_locations(unique_mappings)

        redacted_text = remove_court_signatures(self.apply_mappings(text, unique_mappings))
        leaks = self.scan_high_risk_leaks(redacted_text)
        return RedactionResult(
            original_text=text,
            redacted_text=redacted_text,
            redaction_map=RedactionMap.create(
                mappings=unique_mappings,
                mode=profile.name,
                source_file=source_file,
            ),
            candidates=[],
            review_candidates=review_candidates,
            leaks=leaks,
            mode=profile.name,
            warnings=warnings,
        )

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
        if not mappings: return text
        sorted_mappings = sorted((m for m in mappings if m.original), key=lambda m: len(m.original), reverse=True)
        for entry in sorted_mappings:
            text = text.replace(entry.original, entry.masked)
        return text

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
