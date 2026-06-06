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
from ._samples import load_all_samples



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





# ── 公司名解析：品牌 + 业务描述 + 法律后缀 ──
_LEGAL_SUFFIXES = [
    '有限责任公司', '股份有限公司', '集团有限公司', '有限公司',
    '律师事务所', '会计师事务所',
    '个体工商户', '经营部', '工作室', '商行',
    '委员会', '管理局', '公安局', '税务局',
    '合作社', '公司', '集团',
    '中心', '医院', '学校', '银行', '厂', '店',
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
    '银行', '合作社', '厂', '店', '经营部', '工作室', '商行',
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

        # 0. 加载本地样本库的精准匹配词与黑名单
        if self.config.enable_sample_library:
            _, sample_blacklist = load_all_samples()
        else:
            sample_blacklist = set()

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
                    masked = mask_hebei_text(c.text, get_loc_prefix)
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

        for m in sorted(mappings, key=lambda x: len(x.original), reverse=True):
            if m.original in sample_blacklist:
                continue
            if m.original not in seen_orig:
                seen_orig.add(m.original)
                unique_mappings.append(m)

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
        else:
            sample_blacklist = set()

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
                        masked=mask_hebei_text(candidate.text, get_location_prefix),
                        role=None,
                        source="hebei_admin_db",
                        confidence=candidate.confidence,
                        restore_by_default=True,
                    )
                )

        if self.config.enable_heuristic_ner and profile.redact_locations:
            for candidate in detect_heuristic_ner_candidates(scan_text):
                if candidate.type != "location" or candidate.text in sample_blacklist:
                    continue
                if any(
                    not (candidate.end <= start or candidate.start >= end)
                    for start, end in admin_spans
                ):
                    continue
                if len(candidate.text) > 8 or any(
                    noise in candidate.text
                    for noise in ("银行", "保险", "公司", "集团", "法院", "检察院")
                ):
                    continue
                admin_candidates.append(candidate)

        analysis = {"locations": [], "companies": [], "persons": [], "reject": []}
        if self.config.enable_local_llm and self.config.local_llm.enabled:
            from .llm import LegalEntityAuditor

            auditor = LegalEntityAuditor(self.config.local_llm)
            analysis = auditor.audit_and_verify(
                scan_text,
                [],
                enable_samples=self.config.enable_sample_library,
            )
            if analysis.get("error"):
                warnings.append(str(analysis["error"]))

        engine = LinearRuleEngine(
            counters=counters,
            profile=profile,
            sample_blacklist=sample_blacklist,
            get_location_prefix=get_location_prefix,
        )
        mappings.extend(engine.discover(scan_text, admin_candidates, analysis))

        unique_mappings: list[MappingEntry] = []
        seen_originals: set[str] = set()
        for mapping in base_mappings:
            if mapping.original in seen_originals:
                continue
            seen_originals.add(mapping.original)
            unique_mappings.append(mapping)
        for mapping in sorted(mappings, key=lambda item: len(item.original), reverse=True):
            if mapping.original in seen_originals or mapping.original in sample_blacklist:
                continue
            seen_originals.add(mapping.original)
            unique_mappings.append(mapping)

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
            review_candidates=[],
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
