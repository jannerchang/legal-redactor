from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .config import HIGH_RISK_TYPES
from .lexicon import COMMON_SURNAMES, PROVINCE_NAMES
from .models import Candidate


ROLE_NAMES = (
    "委托代理人",
    "委托诉讼代理人",
    "法定代理人",
    "法定代表人",
    "再审申请人",
    "申请再审人",
    "再审被申请人",
    "申请执行人",
    "被申请人",
    "被上诉人",
    "被执行人",
    "申诉人",
    "被申诉人",
    "上诉人",
    "申请人",
    "第三人",
    "负责人",
    "经营者",
    "原告",
    "被告",
    "原审原告",
    "原审被告",
    "原审第三人",
    "异议人",
    "案外人",
    "利害关系人",
    "复议申请人",
    "异议申请人",
    "辩护人",
    "证人",
)

ROLE_RE = re.compile(rf"^\s*(?P<role>{'|'.join(ROLE_NAMES)})\s*(?:[：:]|\s+)?\s*(?P<body>.+?)\s*$")
ROLE_PREFIX_RE = re.compile(rf"^\s*(?P<role>{'|'.join(ROLE_NAMES)})(?:[一二三四五六七八九十\d]+)?(?:[（\(].*?[）\)])?\s*(?:[：:]|\s+)?\s*(?P<body>.+?)\s*$")

PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)")
ID_RE = re.compile(
    r"(?<![0-9Xx])\d{6}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])"
    r"(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![0-9Xx])"
)
USCC_RE = re.compile(r"(?<![A-Z0-9])[0-9A-Z]{18}(?![A-Z0-9])")
EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9._%+-])")
BANK_RE = re.compile(r"(?<!\d)(?:\d[ -]?){16,24}(?!\d)")

CASE_RE = re.compile(
    r"[（(][12]\d{3}[）)]"
    r"[\u4e00-\u9fa5A-Za-z0-9]{1,16}?"
    r"(?P<proc>知民初|知民终|执异|执复|民辖终|民辖初|民辖|民初|民终|民申|民再|行初|行终|行申|刑初|刑终|刑申|刑再|商初|商终|破申|执|民撤|民特|民保|强清|管辖)"
    r"(?:[0-9一二三四五六七八九十百千万]+号)?"
)

COURT_SUFFIXES = (
    "知识产权法院",
    "互联网法院",
    "铁路运输法院",
    "金融法院",
    "海事法院",
    "高级人民法院",
    "中级人民法院",
    "人民法院",
)
COURT_RE = re.compile(r"[\u4e00-\u9fa5]{2,45}(?:" + "|".join(COURT_SUFFIXES) + r")")

# 增加排除前缀，避免把“以下简称”等词抓进机构名
ORG_RE = re.compile(
    # 1) 含行政区划前缀的公司/机构
    r"[\u4e00-\u9fa5]{2,5}(?:省|市|区|县|自治[区州县]|旗)[\u4e00-\u9fa5A-Za-z0-9()（）·]{1,40}"
    r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司|公司|集团)"
    r"|"
    # 2) 以下简称/简称后，或在句首/标点后的公司简称  
    r"(?:(?<=以下简称)|(?<=简称)|(?<=下称)|(?<=[，。；、\n：]))[\u4e00-\u9fa5A-Za-z0-9·]{2,20}(?:公司|集团)"
    r"|"
    # 3) 专业事务所
    r"[\u4e00-\u9fa5A-Za-z0-9·]{2,25}(?:律师事务所|会计师事务所)"
    r"|"
    # 4) 教育机构（幼儿园前缀通常较短，单独处理）
    r"[\u4e00-\u9fa5]{2,30}(?:幼儿园)"
    r"|"
    # 5) 机构/单位（需较长前缀防止误匹配）
    r"[\u4e00-\u9fa5]{4,30}"
    r"(?:委员会|管理局|公安局|税务局|中心|医院|学校|银行)"
    r"|"
    # 6) 个体工商户/经营部/商行/工作室
    r"[\u4e00-\u9fa5]{3,25}(?:个体工商户|经营部|商行|工作室)"
    r"|"
    # 7) 带地名前缀的厂/店
    r"[\u4e00-\u9fa5]{2,10}(?:省|市|区|县)[\u4e00-\u9fa5]{2,25}(?:厂|店)"
    r"|"
    # 8) 通用公司名（不要求行政区划前缀）
    r"[\u4e00-\u9fa5A-Za-z0-9()（）·]{2,45}(?:有限责任公司|股份有限公司|集团有限公司|有限公司)"
)
PROJECT_RE = re.compile(
    r"(?<!案件)[\u4e00-\u9fa5A-Za-z0-9·]{4,45}?" # 避免匹配“本案件”
    r"(?:商业综合体工程|建设项目|工程项目|工程施工|项目工程|项目|工程|小区|花园|公寓|广场|大厦|商业综合体|产业园|标段)"
)
LOCATION_RE = re.compile(
    r"(?!(?:余名|多名|整个|那么|这个|那个|某某|几个|本案|该案|上述|本市|本省|本区|省市|市区|县城|城镇|乡镇|村庄|本村|该村|扰乱|范围|国家|维持|驳回|反映|限制|保护|金融|总部|商务|制度|组织|全面|一定))"
    r"(?![个些么这那某每各全数余多近共约将整前在往到去赴与和同及当该此被原住扰乱维驳映范限])"
    r"[\u4e00-\u9fa5]{2,6}?(?:省|自治区|市|自治州|盟|(?<!小|校|厂|园|战|军|市|省|街|工|林|矿|片)区|县|旗|镇|乡|街道|(?<!名)村|社区)"
)
GRASSROOTS_ORG_RE = re.compile(
    r"[\u4e00-\u9fa5]{2,30}?(?:村民委员会|居民委员会|村委会|居委会)"
)
ADDRESS_KEY_RE = re.compile(
    r"(?:住所地|住址|户籍地|经常居住地|送达地址|地址|住)"
    r"[：:]?\s*(?P<addr>[\u4e00-\u9fa5A-Za-z0-9（）()号幢栋单元室楼层路街弄巷村社区区县市省镇乡\-]{5,80})"
)
ADDRESS_BODY_RE = re.compile(
    r"[\u4e00-\u9fa5]{2,12}(?:省|自治区|市)"
    r"[\u4e00-\u9fa5A-Za-z0-9号幢栋单元室楼层路街弄巷村社区区县镇乡\-]{6,70}"
)
PERSON_AFTER_ROLE_RE = re.compile(r"(?:证人|联系人|经办人|代理人|法定代表人|负责人|经营者)[：:]?\s*([\u4e00-\u9fa5]{2,4})")
PERSON_AFTER_KINSHIP_RE = re.compile(
    r"(?:及其|与其|和其|其|的)"
    r"(?:儿子|儿|子|女儿|女|父亲|父|母亲|母|妻子|妻|丈夫|夫|配偶|兄弟|哥哥|弟弟|姐姐|妹妹)"
    r"([\u4e00-\u9fa5]{2,4}?)(?=之间|间|，|,|。|；|;|、|和|与|及|$)"
)

TITLE_ENTITY_RE = re.compile(
    r"^(?P<a>[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,40}?)"
    r"(?:与|诉)"
    r"(?P<b>[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,45}?)"
    r"(?:劳动争议|建设工程|合同纠纷|买卖合同|民间借贷|侵权责任|行政|刑事|一审|二审|再审|民事)"
)


@dataclass(frozen=True)
class LineSpan:
    index: int
    text: str
    start: int
    end: int
    newline: str


@dataclass(frozen=True)
class PartyLine:
    role: str
    entity: str
    entity_type: str
    line: str
    line_start: int
    line_end: int
    entity_start: int
    entity_end: int
    keep_lawyer_label: bool


def iter_line_spans(text: str) -> Iterable[LineSpan]:
    pos = 0
    for index, raw in enumerate(text.splitlines(keepends=True)):
        newline = ""
        line = raw
        if raw.endswith("\r\n"):
            newline = "\r\n"
            line = raw[:-2]
        elif raw.endswith("\n") or raw.endswith("\r"):
            newline = raw[-1]
            line = raw[:-1]
        yield LineSpan(index=index, text=line, start=pos, end=pos + len(line), newline=newline)
        pos += len(raw)
    if not text:
        return
    if text and not text.endswith(("\n", "\r")):
        return


def parse_party_line(line: str, line_start: int = 0) -> PartyLine | None:
    match = ROLE_PREFIX_RE.match(line.strip())
    if not match:
        return None

    role = match.group("role")
    body = match.group("body").strip()
    if not body:
        return None

    entity = _extract_party_entity(body)
    if not entity:
        return None

    line_entity_start = line.find(entity)
    if line_entity_start < 0:
        return None

    entity_type = classify_entity(entity, role)
    if entity_type == "person" and _is_false_person(entity):
        return None
    if entity_type == "organization" and _is_false_org(entity):
        return None

    return PartyLine(
        role=role,
        entity=entity,
        entity_type=entity_type,
        line=line,
        line_start=line_start,
        line_end=line_start + len(line),
        entity_start=line_start + line_entity_start,
        entity_end=line_start + line_entity_start + len(entity),
        keep_lawyer_label=("律师" in body and role == "委托诉讼代理人"),
    )


def _extract_party_entity(body: str) -> str:
    body = body.strip(" ：:，,。；;、")
    if re.match(r"^(?:位于|在|因|与|起诉|诉称|称|认为|主张|住所地|经常居住地|现住|地址|系)", body):
        return ""
    body = re.sub(r"^(?:自然人|公民|公司|单位|个体工商户)\s*", "", body)
    field = re.split(r"[，,。；;、\n]", body, maxsplit=1)[0].strip()
    
    if not field:
        return ""
        
    # 移除末尾可能的动作词（如“答辩称”、“诉称”、“称”等）
    field = re.sub(r"(?:答辩称|辩称|诉称|申请称|复议称|补充陈述|补充说明|陈述|说明|补充|称)$", "", field).strip()
    if not field:
        return ""
        
    # 排除明显的案件叙述行
    if any(kw in field for kw in ("纠纷一案", "纠纷案", "一案", "本院", "审理", "查明", "判决")):
        return ""
        
    # 1. 优先尝试作为完整机构匹配（保留机构名中的括号如（集团））
    org_match = ORG_RE.search(field)
    if org_match and org_match.start() == 0:
        cleaned = _clean_org_simple(org_match.group(0))
        if cleaned and cleaned not in {"公司", "该公司", "本公司", "分公司"}:
            return cleaned

    # 2. 如果不是机构，移除可能存在的尾部括号（如人名的曾用名、简称等）
    field_clean = re.sub(r"（.*?）|\(.*?\)", "", field).strip()
    field_clean = field_clean.strip(" ：:，,。；;、")
    
    if not field_clean:
        return ""
        
    # 3. 针对剩余情况（主要是人名或未被正则识别的罕见组织）
    return field_clean


def classify_entity(text: str, role: str | None = None) -> str:
    if role in {"委托诉讼代理人", "委托代理人", "法定代理人"}:
        return "person"
    if role in {"法定代表人", "负责人", "经营者"} and len(text) <= 6:
        return "person"
    if "个体工商户" in text:
        return "individual_business"
    if ORG_RE.fullmatch(text) or any(key in text for key in ("公司", "集团", "律师事务所", "合作社", "委员会", "管理局", "公安局", "税务局", "中心", "医院", "学校", "幼儿园", "银行", "经营部", "商行", "工作室", "厂", "店")):
        return "organization"
    if PROJECT_RE.fullmatch(text):
        return "project"
    if LOCATION_RE.fullmatch(text):
        return "location"
    return "person"


def extract_organization_entities(text: str) -> list[tuple[str, int, int]]:
    entities: list[tuple[str, int, int]] = []
    for match in ORG_RE.finditer(text):
        raw = match.group(0)
        # ORG_RE 已经做了很好的筛选，这里只做最小清理
        value = _clean_org_simple(raw)
        if not value or value in {"公司", "该公司", "本公司", "分公司"}:
            continue
        start = match.start() + raw.find(value)
        entities.append((value, start, start + len(value)))
    return entities


def _clean_org_simple(value: str) -> str:
    """对公司名做最小化清理：只剥离确定不会出现在公司名中的前导词与括号噪声。"""
    value = value.strip(" ：:，,。；;\n\t)）(（-·")
    # 剥离常见的非公司名前缀（角色标签、标点、连接词）
    _role_prefix = re.compile(
        r"^(?:申诉人|被申诉人|原告(?:\d+)?|被告(?:\d+)?|第三人|申请人|被申请人|"
        r"上诉人|被上诉人|再审申请人|再审被申请人|原审原告|原审被告)"
    )
    value = _role_prefix.sub("", value).strip()
    
    # 剥离前导常见动词、介词、代词、语气词或连词（加盖、本案、系、然、由、为、费用由、关于等）
    _noise_prefix = re.compile(
        r"^(?:和|及|与|、|，|,|；|;|的|为|由|在|系|然|费用由|费用|加盖|本案|程中|导致|配合|协助|不服|认为|诉称|辩称|判决|裁定|关于|向|致|对|由其|将其|由该|将该|该|此|通知|请追加|身份系代表|去跟|见|返还给|支付给|返还|退还|偿还|遵循|根据|解(?=[\u4e00-\u9fa5]{2,4}(?:公司|集团|有限)))"
    )
    
    # 循环剥离直到没有前导噪声词
    while True:
        prev_len = len(value)
        value = _noise_prefix.sub("", value).strip()
        if len(value) == prev_len:
            break
            
    return value


def risk_for(entity_type: str) -> str:
    return "high" if entity_type in HIGH_RISK_TYPES or entity_type in {"email"} else "medium"


def default_restore(entity_type: str) -> bool:
    return entity_type not in {
        "id_number",
        "phone",
        "bank_account",
        "address",
        "unified_social_credit_code",
        "email",
        "postcode",
    }


def detect_party_candidates(text: str) -> tuple[list[Candidate], list[PartyLine]]:
    candidates: list[Candidate] = []
    party_lines: list[PartyLine] = []
    for line in iter_line_spans(text):
        party = parse_party_line(line.text, line.start)
        if not party:
            continue
        party_lines.append(party)
        candidates.append(
            Candidate(
                type=party.entity_type,
                text=party.entity,
                start=party.entity_start,
                end=party.entity_end,
                source="party_section",
                confidence=1.0,
                risk_level=risk_for(party.entity_type),
                auto_redact=True,
                role=party.role,
                reason="当事人信息段专项解析",
            )
        )
    return candidates, party_lines


INLINE_PERSON_LIST_ROLE_RE = re.compile(
    rf"(?:^|[，,。；;\n\s]|诉|与|和|及)"
    rf"(?P<role>{'|'.join(ROLE_NAMES)})(?:[一二三四五六七八九十\d]+)?(?:[：:])?"
)
INLINE_PERSON_LIST_STOP_RE = re.compile(
    rf"[。；;\n]|(?:诉|与|和|及)?(?:{'|'.join(ROLE_NAMES)})(?:[一二三四五六七八九十\d]+)?(?:[：:])?"
)
INLINE_PERSON_CASE_TAIL_RE = re.compile(
    r"(?:合同纠纷|劳动争议|民间借贷|侵权责任|买卖合同|建设工程|"
    r"纠纷一案|纠纷案|一案).*$"
)


def detect_inline_party_person_list_candidates(text: str) -> list[Candidate]:
    """Detect people listed after inline party roles, e.g. 第三人张三、李四."""
    candidates: list[Candidate] = []
    seen: set[tuple[str, int]] = set()
    for match in INLINE_PERSON_LIST_ROLE_RE.finditer(text):
        role = match.group("role")
        tail = text[match.end() :]
        stop = INLINE_PERSON_LIST_STOP_RE.search(tail)
        if stop:
            tail = tail[: stop.start()]
        tail = INLINE_PERSON_CASE_TAIL_RE.sub("", tail).strip(" ：:，,。；;\n\t")
        if not tail:
            continue
        parts = re.split(r"[、,，]|(?:和|及)(?=[\u4e00-\u9fa5]{2,4}(?:[、,，]|$))", tail)
        for part in parts:
            raw = part.strip(" ：:，,。；;\n\t")
            raw = re.split(r"(?:男|女|汉族|住|住所地|身份证|公民身份)", raw, maxsplit=1)[0]
            value = _clean_person_name(raw)
            if _is_false_person(value) or not re.fullmatch(r"[\u4e00-\u9fa5·]{2,6}", value):
                continue
            local_start = text.find(value, match.end())
            if local_start < 0:
                continue
            key = (value, local_start)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                Candidate(
                    type="person",
                    text=value,
                    start=local_start,
                    end=local_start + len(value),
                    source="inline_party_person_list",
                    confidence=0.93,
                    risk_level=risk_for("person"),
                    auto_redact=True,
                    role=role,
                    reason="行内当事人/第三人名单解析",
                    metadata={"context": text[max(0, match.start() - 20) : min(len(text), local_start + len(value) + 40)]},
                )
            )
    return candidates


def detect_standard_regex_candidates(text: str) -> list[Candidate]:
    return detect_regex_candidates(text, include_addresses=False)


def detect_regex_candidates(text: str, include_addresses: bool = False) -> list[Candidate]:
    candidates: list[Candidate] = []
    candidates.extend(_sensitive_regex_candidates(text, PHONE_RE, "phone", "regex", 1.0, "手机号规则"))
    candidates.extend(_sensitive_regex_candidates(text, ID_RE, "id_number", "regex", 1.0, "身份证号规则"))
    candidates.extend(_uscc_candidates(text))
    candidates.extend(_bank_candidates(text))
    candidates.extend(_regex_candidates(text, EMAIL_RE, "email", "regex", 1.0, "邮箱规则"))
    candidates.extend(_case_candidates(text, source="court_case_number_parser"))
    if include_addresses:
        candidates.extend(_address_candidates(text))
    return candidates


def detect_title_candidates(text: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    non_empty_seen = 0
    for line in iter_line_spans(text):
        stripped = line.text.strip()
        if not stripped:
            continue
        non_empty_seen += 1
        if non_empty_seen > 12 or parse_party_line(stripped):
            break
        if any(key in stripped for key in ("判决书", "裁定书", "调解书", "决定书")):
            match = TITLE_ENTITY_RE.search(stripped)
            if match:
                for group in ("a", "b"):
                    raw = match.group(group).strip()
                    entity = _trim_title_entity(raw)
                    if len(entity) >= 2:
                        offset = line.text.find(entity)
                        entity_type = classify_entity(entity)
                        candidates.append(
                            Candidate(
                                type=entity_type,
                                text=entity,
                                start=line.start + offset,
                                end=line.start + offset + len(entity),
                                source="title_parser",
                                confidence=0.96,
                                risk_level=risk_for(entity_type),
                                auto_redact=True,
                                reason="标题当事人名称解析",
                            )
                        )
        candidates.extend(_case_candidates(stripped, source="title_parser", base_offset=line.start))
    return candidates


# ── 兜底人名检测（不依赖当事人段格式） ──────────────────────────

# 中文法律文书中常见的人名模式
_FALLBACK_PERSON_PATTERNS = [
    # "，XXX，男/女" 或 "，XXX，汉族"
    re.compile(r"[，,]\s*([一-龥]{2,4})\s*[，,]\s*(?:男|女|汉族)"),
    # 句号/换行后的人名动作
    re.compile(r"(?:^|[。\n])\s*(?:原告|被告|第三人|上诉人|被上诉人|申请人|被申请人)?\s*([一-龥]{2,4})\s*(?:答辩称|辩称|诉称|申请称|复议称|向本院|补充)"),
    # 名字+的+特定角色或动作主张
    re.compile(r"(?:^|[，。；\n、])\s*([一-龥]{2,4})的(?:委托|法定|诉讼|代理|主张|请求|意见|陈述|辩称|诉称|要求|签字|签章|签名)"),
    # 角色标签后的明确冒号人名
    re.compile(r"(?:证人|联系人|经办人|代理人|法定代表人|负责人|经营者|执行人|收件人)[：:]\s*([一-龥]{2,4})(?=[，。；\n、]|$)"),
    # 常用关系/介词引导人名（对单字介词限制前导字符，防止误匹配“涉及”、“合同”等，并移除了纯连接词“及”）
    re.compile(r"(?:(?:听取|询问|传唤|通知|告知|召集|委托|交由|伙同|连同|会同)|(?<!涉|以|波|触|及|共|合|不|陪|相|针|面|敌|交|送|分|留|付|参|赠|施|总|温)(?:由|向|与|和|同|对|给|致))\s*([一-龥]{2,3})(?=[，。；\n、\s一-龥])"),
    # 句中名字起句与动作
    re.compile(r"(?:^|[，。；\n、\s])\s*([一-龥]{2,3})\s*(?:于|在|已|将|以|向|与|提交|提供|出具|收到|签收|签署|签字|支付|偿还|欠|借|称|说|表示|辩称|要求|主张|确认|拒绝|不服|同意|补办|说明|转账|汇款|下载|发送|立案|驳回)"),
    # 亲属关系
    PERSON_AFTER_KINSHIP_RE,
]
# 不应识别的常见词
_FALSE_PERSON_WORDS = frozenset({
    "原告", "被告", "本院", "法院", "裁定", "判决", "公司",
    "合同", "项目", "工程", "事实", "法律",
    "规定", "根据", "认为", "审理", "查明", "适用", "依法",
    "上述", "如下", "另有", "对于", "关于", "有关", "由于",
    "鉴于", "依照", "按照", "予以", "不予",
    "共同", "各自", "应当", "可以", "不得", "已经", "尚未",
    "进行", "作出", "提出", "提交", "出具", "提供",
    "存在", "发生", "产生", "决定", "确认", "认定", "确定",
    "当事人", "委托", "法定", "代理", "诉讼", "起诉", "上诉", "申诉",
    "负责人", "代表人", "代理人", "辩护人", "权利人", "义务人",
    "人数", "两年内", "一年内", "补充", "说明", "本案", "他人", "本人",
    "三原告", "两原告", "三被告", "两被告", "原审", "被申请", "申请",
    # ── 常见误识别排除词 ──
    "双方", "各方", "对方", "本方", "通知", "公告", "送达",
    "费用", "金额", "损失", "利息", "无效", "有效", "解除", "终止",
    "履行", "支付", "请求", "主张", "配合", "协助", "支持", "理由",
    "陈述", "辩称", "答辩", "陈述意见", "抗诉",
    "执行", "裁决", "判令", "承担", "案情", "起诉状", "答辩状", "委托书", "代理词",
    # ── 口语与泛称实体、动词、方位词排除 ──
    "单位", "毕业", "订立", "成立", "设立", "责任", "见过", "帮忙", "结算", "开庭",
    "开庭后", "劳动者", "代表", "表示", "工作", "任职", "离职", "入职", "集团", "中心", "都用",
    "部门", "块", "圈", "后", "没见", "见过章", "明确", "法庭",
    "包含", "施工", "法官", "齐齐", "利润", "时三方", "时到期", "时甲方", "时该条", "时还约",
    "水采暖", "水配管", "水管道", "水管清", "时期其", "应检测", "应实体", "安装费",
    "安置方", "所说", "正义", "仲裁", "应以",
    # ── 新增：从715条黑名单分析出的高频误识别词 ──
    "通过", "经由", "经营", "劳动", "劳力", "劳务", "安装", "万元", "平房", "房屋",
    "应予", "应债", "应就", "应票", "应该", "应项", "应造价", "应商票", "应向",
    "方式", "方法", "方上", "程序", "管理", "质证", "都属", "甄别", "明显",
    "公共", "公平", "公序", "公交", "司法", "制度", "维持", "驳回", "扰乱",
    "国家", "范围", "反映", "步推", "保护", "限制", "组织", "全面",
    "高水", "花架", "解协",
    "同意", "不同意", "第一", "第二", "第三", "仲裁委", "仲裁时",
    "包括", "作为", "案涉", "权限",
    # ── 4396 样本：口语/程序性短语误识别人名 ──
    "甲方", "签约", "维护", "而非", "银行流水", "人员混同", "仍然认可", "同时",
    "将水搅浑", "无关", "无权再向", "欲证实", "直至今日", "老贾",
})


def _clean_person_name(value: str) -> str:
    """清理人名：剥离首尾多余括号及不匹配的标点，裁剪多余的尾随助词/连词/介词/动作词"""
    value = value.strip(" ：:，,。；;\n\t（）()")
    value = _clean_unbalanced_brackets(value)
    # 剥离末尾可能被误匹配进去的助词、连词、介词或动作词
    while len(value) >= 2 and value[-1] in "及辩诉称和与等某已在于男女将被原吗呢吧啊呀":
        value = value[:-1]
    return value.strip()


def _is_false_person(value: str) -> bool:
    """判定是否为伪人名（非合法实体，如长句误抓、动词短语等）"""
    if len(value) < 2 or len(value) > 20:
        return True
    if any(char.isdigit() or char in "0123456789０１２３４５６７８９.%‰万亿元" for char in value):
        return True
    # 含"某"字且某不在末尾 → 已脱敏占位符+尾字误抓（如 罗某手、罗某提、丁某向）
    # 但"李某"（某在末尾）是合法的匿名引用，应保留
    if "某" in value and not value.endswith("某"):
        return True
    # 汉字姓名如果没有点“·”，通常不应超过4个字
    if len(value) > 4 and "·" not in value and "•" not in value:
        return True
    if any(w in value for w in _FALSE_PERSON_WORDS):
        return True
    if any(
        term in value
        for term in (
            "采暖", "配管", "管道", "管清", "检测", "实体", "安装费", "时期",
            "施工", "进度", "过程中", "过错", "费用",
        )
    ):
        return True
    # ── 末字是高频动词/副词/形容词尾字 → 伪人名（如 高涛全, 王平抗, 徐闯提）──
    _TAIL_ACTION_CHARS = frozenset(
        "全均承提抗扣图聊反送担到打替找查验收据向属力监者称证过进内无赔手"
        "交破期满合范工费还详适关就形备规约债票项款应出"
        "拨支负签协公"
    )
    if len(value) == 3 and value[-1] in _TAIL_ACTION_CHARS:
        return True
    if len(value) <= 3 and (
        value.endswith(("提", "未", "内", "反", "聊", "分", "也", "吗", "呢", "吧", "啊", "呀"))
        or value.startswith(("方", "施工", "法官", "齐齐", "包含"))
    ):
        return True
    # 排除包含常见助词、连词、语气代词等误匹配
    if any(p in value for p in ("的", "了", "在", "是", "去", "给", "有", "我", "你", "他", "们", "这", "那", "个", "对", "后", "做", "用")):
        return True
    if any(value.startswith(prov) for prov in PROVINCE_NAMES):
        return True
    return False


def detect_fallback_person_candidates(text: str) -> list[Candidate]:
    """兜底人名检测：扫描常见中文人名模式，不依赖当事人段格式。

    适用于当事人段解析失败或文档格式不同于标准判决书的情况。
    """
    candidates: list[Candidate] = []
    
    # 增加百家姓校验，如果匹配的词是以百家姓开头，可信度更高
    common_surnames = COMMON_SURNAMES

    for pattern in _FALLBACK_PERSON_PATTERNS:
        for match in pattern.finditer(text):
            raw_value = match.group(1).strip()
            if not raw_value:
                continue
            value = _clean_person_name(raw_value)
            if _is_false_person(value):
                continue
            # 必须像中文名：2-4个汉字，无明显非名字特征
            if not re.fullmatch(r"[一-龥]{2,4}", value):
                continue
            # 姓不能是罕见单字指示词
            if value[0] in "被原申本上该此前述依根关由自因对从与和或及至向在已请告人我持合配旗交说证其们起于当维扰驳范息房步经劳公司":
                continue
            
            # 如果不是以常见姓氏开头，直接过滤掉（非百家姓开头的兜底匹配极易造成误识别，如“绝密代”）
            is_surname = value[0] in common_surnames or (len(value) > 2 and value[:2] in common_surnames)
            if not is_surname:
                continue

            start = match.start(1) + raw_value.find(value)
            candidates.append(
                Candidate(
                    type="person",
                    text=value,
                    start=start,
                    end=start + len(value),
                    source="fallback_person",
                    confidence=0.85 if is_surname else 0.60,
                    risk_level="medium",
                    auto_redact=True,
                    reason="兜底人名模式匹配",
                    metadata={"context": text[max(0, start - 20):min(len(text), start + len(value) + 20)]},
                )
            )
    return candidates


def detect_heuristic_ner_candidates(text: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    for match in GRASSROOTS_ORG_RE.finditer(text):
        raw_value = match.group(0)
        value = raw_value
        leading_admin = re.match(r"^.*(?:省|市|区|县|旗|镇|乡|街道)(?P<leaf>[\u4e00-\u9fa5]{2,12}(?:村民委员会|居民委员会|村委会|居委会))$", value)
        if leading_admin:
            value = leading_admin.group("leaf")
        if value in {"村村民委员会", "村村委会", "社区居民委员会", "社区居委会"}:
            continue
        start = match.start() + raw_value.rfind(value)
        candidates.append(
            Candidate(
                type="grassroots_org",
                text=value,
                start=start,
                end=start + len(value),
                source="heuristic_grassroots_org",
                confidence=0.86,
                risk_level=risk_for("location"),
                auto_redact=True,
                reason="本地启发式基层组织识别",
                metadata={"context": text[max(0, match.start() - 40) : min(len(text), match.end() + 40)]},
            )
        )
    for pattern, entity_type, reason, confidence in (
        (ORG_RE, "organization", "本地启发式组织机构识别", 0.84),
        (PROJECT_RE, "project", "本地启发式项目/工程/楼盘识别", 0.82),
        (LOCATION_RE, "location", "本地启发式地名识别", 0.78),
    ):
        for match in pattern.finditer(text):
            raw = match.group(0)
            if entity_type == "organization" and raw.endswith(("村民委员会", "居民委员会", "村委会", "居委会")):
                continue
            if entity_type == "project":
                value = _clean_project_text(raw)
            elif entity_type == "location":
                value = _clean_location_text(raw)
            elif entity_type == "organization":
                value = _clean_organization_text(raw)
            else:
                value = _clean_candidate_text(raw)
            if not value or value.startswith("某"):
                continue
            start = match.start() + match.group(0).find(value)
            # ── 地名上下文过滤：先收窄“张三住某地”这类边界，再判断是否伪地名 ──
            if entity_type == "location" and _looks_like_false_location(text, start, start + len(value), value):
                continue
            # 过滤无品牌名的纯后缀/描述词公司名（如"家具有限公司"、"有限责任公司"）
            if entity_type == "organization" and _is_false_org(value):
                continue
            if entity_type == "organization" and value.endswith("集团"):
                next_index = start + len(value)
                if next_index < len(text) and text[next_index] in "区县市":
                    continue
            candidates.append(
                Candidate(
                    type=entity_type,
                    text=value,
                    start=start,
                    end=start + len(value),
                    source="heuristic_ner",
                    confidence=confidence,
                    risk_level=risk_for(entity_type),
                    auto_redact=True,
                    reason=reason,
                    metadata={"context": text[max(0, start - 40) : min(len(text), start + len(value) + 40)]},
                )
            )
    return candidates


# 常见的非品牌名词汇——当这些词作为公司名的"品牌"部分时，说明是误识别
_FALSE_ORG_BRANDS = frozenset({
    # 产品/物品类
    "家具", "家居", "设备", "材料", "建材", "食品", "服装", "药品", "商品",
    "货物", "物品", "物资", "器材", "器械", "用品", "产品", "配件", "零件",
    # 动作/状态类
    "购买", "销售", "生产", "加工", "制造", "维修", "安装", "运输",
    "管理", "经营", "服务", "咨询", "代理", "承包", "租赁", "出租",
    "策划",
    # 纯后缀/法律术语
    "有限", "责任", "股份", "集团",
    # ── 新增：从黑名单分析出的非品牌名词 ──
    "开发", "建设", "检测", "检验", "造价", "质检",
})

_FALSE_ORG_EXACT_CORES = frozenset({
    "工程", "建筑劳务", "建设", "房地产", "房地产开发", "技术", "科技", "燃气",
    "药业", "生态环境", "独资", "留存", "完善", "扩大适用",
    "检测技术", "检测技术服务", "工程质检技术",
    # ── 新增：从黑名单分析出的纯行业词核心 ──
    "建筑材料设备检验", "工程造价", "建工技术", "电子", "声旺",
    "建筑安装", "建筑科技", "建设工程", "水电开发", "企业发展",
    "流域水电", "网络技术", "信息技术", "策划",
})

_COMMON_SURNAME_CHARS = frozenset("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜谢范彭马苗方袁唐薛雷贺倪汤罗郝安常于傅康伍余顾孟黄萧尹姚邵汪毛董梁杜阮贾路江郭梅林钟徐邱骆高夏蔡田胡万卢莫曾白王")

# 公司字号末尾常见的行业/业务词，与动作动词同形但不应单独触发误杀。
_INDUSTRY_CORE_SUFFIXES = frozenset({
    "运输", "建设", "工程", "制造", "销售", "租赁", "装饰", "物流", "物业",
    "开发", "投资", "科技", "信息", "服务", "咨询", "代理", "管理", "贸易",
    "商贸", "建筑", "劳务", "环保", "能源", "置业", "产业", "电力", "水利",
})


def _core_has_action_verb_noise(core: str, action_verbs: tuple[str, ...]) -> bool:
    for verb in action_verbs:
        if verb not in core:
            continue
        if (
            verb in _INDUSTRY_CORE_SUFFIXES
            and core.endswith(verb)
            and len(core) > len(verb) + 1
        ):
            continue
        return True
    return False


# Module-level constants for _is_false_org (previously redefined on every call)
_PURE_LEGAL_SUFFIXES = frozenset({
    "有限责任公司", "股份有限公司", "集团有限公司", "有限公司", "公司", "集团", "幼儿园",
})

_ORG_ACTION_VERBS = (
    "违反", "拒绝", "接受", "返还", "邮寄", "接管", "工作", "往返",
    "报销", "成立", "设立", "注销", "变更", "起诉", "上诉", "答辩", "申诉",
    "执行", "查封", "扣押", "冻结", "辞退", "解雇", "开除", "离职", "入职",
    "购买", "销售", "生产", "加工", "制造", "维修", "安装", "运输", "承包",
    "租赁", "出租", "派遣", "支付", "履行", "不服", "认为", "陈述", "答辩",
    "进行", "支持", "协助", "配合", "加盖", "盖章", "签章", "签字",
    "损害", "不接受", "交跟", "去跟", "发放", "归属", "使用",
    "核对", "核实", "审查", "交给", "转给", "遵循", "通知", "依据", "根据",
    "汇入", "聘用",
)

_ORG_FALSE_CORE_PREFIXES = frozenset({
    "我", "你", "他", "本", "该", "贵", "此", "来我", "我去", "我区", "你区", "来",
    "中国", "中华", "全国", "地方", "本地", "其实", "确实", "事实", "真实", "证实",
    "落实", "实", "但是", "可是", "若是", "总是", "但", "并", "且", "及", "或", "已",
    "曾", "即", "就", "也", "都", "而", "上", "下", "前", "后", "两", "两家", "三",
    "三家", "双", "各", "各家", "某", "某家", "一", "用", "指", "往", "去", "来", "分",
    "联", "劳动者", "单位", "两个", "二公司", "三公司", "多个", "几家", "见两个",
    "两个公司", "三家公司", "外两家", "达等", "任何", "刺破", "代", "备选机构",
    "机构", "股东用", "非", "说", "知", "解", "知天煜",
})

def _is_false_org(value: str) -> bool:
    """检查清理后的公司名是否为误识别（如"家具有限公司"、"有限责任公司"）。"""
    if re.fullmatch(r"合同[一二三四五六七八九十百零\d]+", value):
        return True
    if "系关联公司" in value or value.startswith(("否认其", "否认与")):
        return True

    # 纯法律后缀，无品牌
    if value in _PURE_LEGAL_SUFFIXES:
        return True
    if "（" in value or "）" in value or "(" in value or ")" in value:
        if not re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9·]+[（(][\u4e00-\u9fa5A-Za-z0-9·]{2,12}[）)][\u4e00-\u9fa5A-Za-z0-9·]*(?:有限责任公司|股份有限公司|集团有限公司|有限公司|公司|集团)", value):
            return True
    
    # 过滤带有明显合同、证据、诉讼等非机构特征的长句。
    if any(noise in value for noise in ("合同", "证据", "佐证", "在卷", "协议", "诉讼", "裁判", "本案", "案涉", "原告", "被告", "第三人", "本院", "转账", "凭证", "案卷")):
        return True

    # 去掉法律后缀后，检查剩余部分
    for sfx in sorted(_PURE_LEGAL_SUFFIXES, key=len, reverse=True):
        if value.endswith(sfx) and len(value) > len(sfx):
            core = value[:-len(sfx)]
            # ── 过滤由常用代词、语气词或国家/通用指代代词构成的伪字号 ──
            if core in _ORG_FALSE_CORE_PREFIXES:
                return True
            if len(core) < 2:
                return True
            if "我" in core or "两家" in core or core.endswith(("等", "等公司")):
                return True
            if core.endswith(("省", "市", "区", "县", "旗", "镇", "乡", "街道", "村", "社区")):
                return True
            if re.fullmatch(r"[\u4e00-\u9fa5]{2,3}", core) and core[0] in _COMMON_SURNAME_CHARS:
                return True
            if core.endswith(("北京区", "中国北京区", "集团区")):
                return True
            # ── 过滤包含法律诉讼/日常动作动词构成的动词短语公司（如 "严重违反公司" -> "严重违反"） ──
            if _core_has_action_verb_noise(core, _ORG_ACTION_VERBS):
                return True
            # 完全匹配常见非品牌词
            if core in _FALSE_ORG_BRANDS or core in _FALSE_ORG_EXACT_CORES:
                return True
            # 核心以常见非品牌词结尾（如"购买家具"以"家具"结尾）
            for fb in _FALSE_ORG_BRANDS:
                if core.endswith(fb) and len(core) > len(fb):
                    prefix = core[: -len(fb)]
                    if len(prefix) <= 2 or _core_has_action_verb_noise(prefix, _ORG_ACTION_VERBS):
                        return True
            break
    else:
        # 如果不带公司/集团后缀，直接检查 core 级别的非地理/动作词
        if any(noise in value for noise in ("我", "你", "他", "本", "该", "贵", "此", "两", "两家", "各", "各家", "某", "一", "两个", "几家", "见两个")):
            return True
        if _core_has_action_verb_noise(value, _ORG_ACTION_VERBS):
            return True
            
    return False



def _regex_candidates(
    text: str,
    pattern: re.Pattern[str],
    entity_type: str,
    source: str,
    confidence: float,
    reason: str,
    base_offset: int = 0,
) -> list[Candidate]:
    return [
        Candidate(
            type=entity_type,
            text=match.group(0),
            start=base_offset + match.start(),
            end=base_offset + match.end(),
            source=source,
            confidence=confidence,
            risk_level=risk_for(entity_type),
            auto_redact=True,
            reason=reason,
        )
        for match in pattern.finditer(text)
    ]


def _sensitive_regex_candidates(
    text: str,
    pattern: re.Pattern[str],
    entity_type: str,
    source: str,
    confidence: float,
    reason: str,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for match in pattern.finditer(text):
        start, end = _expand_sensitive_label(text, match.start(), match.end(), entity_type)
        candidates.append(
            Candidate(
                type=entity_type,
                text=text[start:end],
                start=start,
                end=end,
                source=source,
                confidence=confidence,
                risk_level=risk_for(entity_type),
                auto_redact=True,
                reason=reason,
            )
        )
    return candidates


def _expand_sensitive_label(text: str, start: int, end: int, entity_type: str) -> tuple[int, int]:
    prefixes = {
        "phone": ("联系电话", "电话号码", "手机号", "手机", "电话"),
        "id_number": ("公民身份号码", "身份证号码", "身份证号"),
        "unified_social_credit_code": ("统一社会信用代码",),
    }.get(entity_type, ())
    lookback_start = max(0, start - 12)
    before = text[lookback_start:start]
    for prefix in sorted(prefixes, key=len, reverse=True):
        if before.endswith(prefix):
            return start - len(prefix), end
    return start, end


def _uscc_candidates(text: str) -> list[Candidate]:
    candidates = []
    for match in USCC_RE.finditer(text):
        value = match.group(0)
        if ID_RE.fullmatch(value):
            continue
        # Unified social credit codes are alphanumeric and avoid I/O/Z/S/V.
        if not re.fullmatch(r"[159Y][1239][0-9A-HJ-NPQRTUWXY]{6}[0-9A-HJ-NPQRTUWXY]{10}", value):
            continue
        start, end = _expand_sensitive_label(text, match.start(), match.end(), "unified_social_credit_code")
        candidates.append(
            Candidate(
                type="unified_social_credit_code",
                text=text[start:end],
                start=start,
                end=end,
                source="regex",
                confidence=1.0,
                risk_level="high",
                auto_redact=True,
                reason="统一社会信用代码规则",
            )
        )
    return candidates


def _bank_candidates(text: str) -> list[Candidate]:
    candidates = []
    for match in BANK_RE.finditer(text):
        value = match.group(0).strip()
        digits = re.sub(r"\D", "", value)
        if not 16 <= len(digits) <= 24:
            continue
        if ID_RE.fullmatch(digits):
            continue
        candidates.append(
            Candidate(
                type="bank_account",
                text=value,
                start=match.start(),
                end=match.end(),
                source="regex",
                confidence=0.98,
                risk_level="high",
                auto_redact=True,
                reason="银行账号规则",
            )
        )
    return candidates


def _case_candidates(text: str, source: str, base_offset: int = 0) -> list[Candidate]:
    candidates = []
    for match in CASE_RE.finditer(text):
        candidates.append(
            Candidate(
                type="case_number",
                text=match.group(0),
                start=base_offset + match.start(),
                end=base_offset + match.end(),
                source=source,
                confidence=1.0,
                risk_level="high",
                auto_redact=True,
                reason="案号结构化规则",
                metadata={"procedure": match.group("proc")},
            )
        )
    return candidates


def _clean_unbalanced_brackets(s: str) -> str:
    """递归清理字符串首尾可能存在的不匹配/非对称的括号、标点"""
    s = s.strip()
    brackets = [("（", "）"), ("(", ")"), ("【", "】"), ("[", "]"), ("《", "》"), ("<", ">")]
    changed = True
    while changed:
        changed = False
        for opening, closing in brackets:
            if s.startswith(opening) and not s.endswith(closing):
                s = s[len(opening):].strip()
                changed = True
            elif s.endswith(closing) and not s.startswith(opening):
                s = s[:-len(closing)].strip()
                changed = True
    return s


def _court_candidates(text: str, source: str, base_offset: int = 0) -> list[Candidate]:
    candidates = []
    for match in COURT_RE.finditer(text):
        value = _trim_court_name(match.group(0))
        if not value or value in {"最高人民法院", "最高院"} or value.startswith("某"):
            continue
        start_delta = match.group(0).find(value)
        local_start = match.start() + start_delta
        local_end = local_start + len(value)
        if _is_court_judgment_reference(text, local_start, local_end, match.group(0)):
            continue
        candidates.append(
            Candidate(
                type="court_name",
                text=value,
                start=base_offset + match.start() + start_delta,
                end=base_offset + match.start() + start_delta + len(value),
                source=source,
                confidence=1.0,
                risk_level="high",
                auto_redact=True,
                reason="法院名称规则",
            )
        )
    return candidates


def _address_candidates(text: str) -> list[Candidate]:
    candidates = []
    for match in ADDRESS_KEY_RE.finditer(text):
        value = _trim_address(match.group("addr"))
        if not value or len(value) < 5:
            continue
        if _looks_like_non_address(value):
            continue
        if _looks_like_placeholder_address(value):
            continue
        start = match.start("addr") + match.group("addr").find(value)
        candidates.append(
            Candidate(
                type="address",
                text=value,
                start=start,
                end=start + len(value),
                source="regex",
                confidence=0.92,
                risk_level="high",
                auto_redact=True,
                reason="地址关键词规则",
            )
        )
    for match in ADDRESS_BODY_RE.finditer(text):
        value = _trim_address(match.group(0))
        if not value or value.startswith("某"):
            continue
        if _looks_like_non_address(value):
            continue
        if _looks_like_placeholder_address(value):
            continue
        start = match.start() + match.group(0).find(value)
        candidates.append(
            Candidate(
                type="address",
                text=value,
                start=start,
                end=start + len(value),
                source="regex",
                confidence=0.86,
                risk_level="high",
                auto_redact=True,
                reason="地址结构规则",
            )
        )
    return candidates


def _trim_court_name(value: str) -> str:
    value = value.strip()
    for marker in ("不服", "维持", "撤销", "向", "由", "经", "在", "至", "收到", "提交"):
        idx = value.rfind(marker)
        if idx >= 0 and idx + len(marker) < len(value):
            value = value[idx + len(marker) :]
    if "最高人民法院" in value:
        return "最高人民法院"
    if "最高院" in value:
        return "最高院"
    # Prefer the shortest credible administrative court name at the end.
    admin_match = re.search(
        r"([\u4e00-\u9fa5]{2,12}(?:省|自治区)[\u4e00-\u9fa5]{0,18}(?:高级人民法院|中级人民法院|人民法院)|"
        r"[\u4e00-\u9fa5]{2,12}(?:市|自治州)[\u4e00-\u9fa5]{0,18}(?:中级人民法院|人民法院)|"
        r"[\u4e00-\u9fa5]{2,12}(?:区|县|旗)[\u4e00-\u9fa5]{0,10}人民法院|"
        r"[\u4e00-\u9fa5]{2,20}(?:金融法院|知识产权法院|互联网法院|海事法院|铁路运输法院))$",
        value,
    )
    if admin_match:
        return admin_match.group(1)
    return value[-30:]


def _is_court_judgment_reference(text: str, start: int, end: int, raw_match: str) -> bool:
    before = text[max(0, start - 12) : start]
    after = text[end : min(len(text), end + 18)]
    raw = raw_match.strip()
    judgment_action = before.endswith(("维持", "撤销", "裁定撤销", "判决维持")) or raw.startswith(("维持", "撤销"))
    judgment_object = any(marker in after for marker in ("判决", "裁定", "民事判决", "一审判决", "原判"))
    return judgment_action and judgment_object


def _trim_address(value: str) -> str:
    value = value.strip(" ：:，,。；;\n\t")
    value = re.sub(r"^(?:住所地|住所|住址|户籍地|经常居住地|送达地址|地址|住)[：:]?", "", value)
    value = re.split(r"(?:公民身份号码|统一社会信用代码|电话|手机|邮编|电子邮箱|邮箱)", value, maxsplit=1)[0]
    value = value.strip(" ：:，,。；;\n\t")
    return value


def _clean_location_text(value: str) -> str:
    value = _clean_candidate_text(value)
    value = re.sub(
        r"^[\u4e00-\u9fa5]{2,4}住(?=[\u4e00-\u9fa5]{2,20}(?:省|自治区|市|自治州|区|县|旗|镇|乡|街道|村|社区)$)",
        "",
        value,
    )
    value = re.sub(
        r"^(?:项目地点|项目|地点|住所地|住所|住址|户籍地|经常居住地|送达地址|地址|所在地|"
        r"坐落于|坐落|位于|前往|进驻|人员进驻|提交|提供|交|出|发|派|根据|按照|"
        r"涉及|合作开发|开发|投资实施|住|地)",
        "",
        value,
    )
    return value.strip(" ：:，,。；;\n\t")

def _looks_like_placeholder_address(value: str) -> bool:
    return bool(re.fullmatch(r"(?:地址)?[^\d,，。；;]{0,4}地址[甲乙丙丁戊己庚辛壬癸\d]+", value)) or bool(
        re.fullmatch(r"地址[甲乙丙丁戊己庚辛壬癸\d]+", value)
    ) or (value.startswith("某") and any(marker in value for marker in ("某省", "某市", "某区", "某县", "某镇", "某乡", "某街道", "某村", "某社区")))


def _looks_like_non_address(value: str) -> bool:
    if re.search(r"(?:有限公司|公司|集团|委员会|居民委员会|村民委员会|合作社|经营部|商行|工作室|幼儿园|厂|店)", value):
        return True
    if any(
        marker in value
        for marker in (
            "本判决",
            "生效之日",
            "向原告",
            "向被告",
            "返还",
            "支付",
            "承担",
            "辩称",
            "诉称",
            "主张",
            "投资款",
        )
    ):
        return True
    return False


def _trim_title_entity(value: str) -> str:
    value = value.strip(" ：:，,。；;")
    value = re.sub(r"^(?:原告|被告|上诉人|被上诉人|申请人|被申请人)", "", value)
    return value.strip()


def _clean_candidate_text(value: str) -> str:
    value = value.strip(" ：:，,。、；;\n\t")
    for marker in (
        "申请确认与",
        "合作期间",
        "期间",
        "作为",
        "围绕",
        "与",
        "诉",
        "入职",
        "任职于",
        "受雇于",
        "承建",
        "发包给",
        "支付给",
        "签订的",
        "签订",
        "认为",
        "向",
    ):
        idx = value.rfind(marker)
        if idx >= 0 and idx + len(marker) < len(value):
            value = value[idx + len(marker) :]
    for bad_prefix in (
        "本案原告",
        "本案被告",
        "案涉原告",
        "案涉被告",
        "原告",
        "被告",
        "上诉人",
        "被上诉人",
        "申请人",
        "被申请人",
        "第三人",
    ):
        if value.startswith(bad_prefix) and len(value) > len(bad_prefix) + 1:
            value = value[len(bad_prefix) :]
    value = re.sub(r"^\d+(?:\.\d+)?(?:元|万元|亿元)?", "", value)
    value = re.sub(r"^\d{4}年\d{1,2}月\d{1,2}日", "", value)
    return value.strip(" ：:，,。、；;\n\t")


def _clean_project_text(value: str) -> str:
    value = _clean_candidate_text(value)
    if not value:
        return ""
    if re.search(r"(?:有限公司|公司|集团|置业有限公司)(?:建设工程|工程|项目)$", value):
        return ""
    # 泛称工程/项目词语，不是具体项目名
    if value in {"建设工程", "工程", "项目", "该公司项目", "质量存在争议",
                 "的工程", "施工工程", "拖欠工程", "支付工程", "剩余工程",
                 "导致工程", "承包工程", "在建工程", "对该工程", "上述工程"}:
        return ""
    if re.match(r"^(?:拖欠|支付|剩余|导致|该|上述|此|本|涉案|案涉|施工|在建|已完|未完)(?:工程|项目)$", value):
        return ""
    if value.endswith(("施工合同", "合同纠纷")):
        return ""
    # 剥离常见的谓词前缀
    value = re.sub(r"^(?:鉴于|关于|涉及|导致|造成|属于|的|在|由|对|将|让|使)", "", value)
    return value


def _clean_organization_text(value: str) -> str:
    value = value.strip(" ：:，,。、；;\n\t（）()")
    value = _clean_unbalanced_brackets(value)
    value = re.sub(r"(有限责任公司|股份有限公司|集团有限公司|有限公司)公司$", r"\1", value)
    _org_sfx = ["有限责任公司","股份有限公司","集团有限公司","有限公司",
                "律师事务所","会计师事务所","公司","集团","经营部",
                "商行","工作室","委员会","管理局","公安局","税务局",
                "中心","医院","学校","幼儿园","银行","个体工商户","厂","店"]
    value = _clean_org_brackets(value.strip(" ：:，,。、；;\n\t"))
    value = re.sub(
        r"^(?:申诉人|被申诉人|原告(?:\d+)?|被告(?:\d+)?|第三人|申请人|被申请人|"
        r"上诉人|被上诉人|再审申请人|再审被申请人|原审原告|原审被告)",
        "",
        value,
    ).strip(" ：:，,。、；;\n\t")
    value = re.sub(
        r"^(?:和|及|与|、|，|,|；|;|"
        r"原名|曾用名为|曾用名|原名称|简称为|简称|"
        r"以下简称|下称)",
        "",
        value,
    ).strip(" ：:，,。、；;\n\t")
    matched = next((sfx for sfx in sorted(_org_sfx, key=len, reverse=True) if value.endswith(sfx)), "")
    core = value[: -len(matched)] if matched else value
    if not core:
        return ""
    if core.startswith("名") and core[1:].startswith((
        "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
        "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
        "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
        "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
    )):
        return ""
    if _looks_like_standalone_branch_company(value):
        return ""
    if value in ("公司","该公司","本公司","分公司"):
        return ""
    return value

def _clean_org_brackets(value: str) -> str:
    if value.count("（") == value.count("）") and value.count("(") == value.count(")"):
        return value
    return _clean_unbalanced_brackets(value)

def _looks_like_standalone_branch_company(value: str) -> bool:
    return bool(re.fullmatch(r"[\u4e00-\u9fa5]{2,12}(?:市)?分公司", value))


def _looks_like_non_name(value: str) -> bool:
    if value in {"公司", "本院", "法院", "原告", "被告", "项目", "工程", "住所", "电话"}:
        return True
    # 纯虚词/介词/连词不是人名
    if value in {"并在", "且在", "并在", "也在", "还对", "而对", "并向", "并为"}:
        return True
    # 以“的”结尾不是人名
    if value.endswith("的"):
        return True
    return False


# ── 审判组织签名块删除 ──────────────────────────────────────────

_COURT_PERSONNEL_ROLES = (
    "审判长",
    "审判员",
    "代理审判员",
    "人民陪审员",
    "法官助理",
    "书记员",
    "执行员",
    "执行法官",
    "法 官 助 理",
    "书 记 员",
    "审 判 长",
    "审 判 员",
)

_COURT_SIGNATURE_RE = re.compile(
    r"(?:^|\n)\s*(?:" + "|".join(_COURT_PERSONNEL_ROLES) + r")[\s：:]*[一-龥·\s]{2,20}(?:\n|$)",
    re.MULTILINE,
)


def remove_court_signatures(text: str) -> str:
    """删除文书末尾的审判组织成员署名行。"""
    # 找到签名块起始位置（最后一个审判角色出现的位置）
    lines = text.split("\n")
    # 从后往前找第一个匹配的行
    for i in range(len(lines) - 1, -1, -1):
        if _COURT_SIGNATURE_RE.match(lines[i]):
            # 找到了，删除从此行往后的所有符合模式的行
            start = i
            # 往前找到第一个不匹配的，确定签名块范围
            # 实际上审判组织行通常是连续的几行，从前往后删
            clean = []
            j = 0
            while j < len(lines):
                stripped = lines[j].strip()
                # 检查是否为审判组织行
                is_sig = bool(_COURT_SIGNATURE_RE.match(stripped))
                # 也检查宽松模式：以角色开头，后面只有人名和空格
                is_loose = any(
                    stripped.startswith(role) for role in _COURT_PERSONNEL_ROLES
                ) and len(stripped) < 30
                if is_sig or is_loose:
                    j += 1
                    continue
                clean.append(lines[j])
                j += 1
            return "\n".join(clean)
    return text


# ── 地名误匹配过滤 ──────────────────────────────────────────────

# 这些前缀字符表示后面的地名是通用指代而非具体地点
_FALSE_LOCATION_LEADING = frozenset(
    "所辖各县各全将及涉除等本该此上前后下"
    "含包由自因从对为与和或到至向在"
)

# 真实地名的主体部分不应包含这些常见的动词、副词、介词、助词、连词
# （用于通用过滤，不依赖硬编码地名词典）
_NON_GEO_CHARS = frozenset(
    "做不是有的了吗呢把被让给跟关得过着会能要想可就也还都很太更最"
    "只但而且因所以如果虽然却并没无非即使已经正常并且或者"
    "在由向对从至到为与和或含包自"
    "购买使用需求满足达超低高属于价格数量"
    "导致办请找等候住"
    "未无非没"
    # ── 新增：从误识别地名分析出的高频非地理字符 ──
    "扰乱维驳映范围限制护境息商务总金融反组织全面制度规"
)

_LOCATION_SUFFIXES = ("省", "自治区", "市", "自治州", "盟", "区", "县", "旗", "镇", "乡", "街道", "村", "社区")


def _looks_like_false_location(text: str, start: int, end: int, raw: str) -> bool:
    """检查 LOCATION_RE 匹配是否为误匹配。

    过滤：涉及所辖市、将全省、各县市、及市、除特殊企业及市 等。
    """
    # —— 排除含有常见动作、事务等非地名的高频名词和动词 ——
    if any(
        kw in raw
        for kw in (
            "产权", "进行", "项目", "工程", "施工", "合同", "协议", "纠纷", "案件",
            "单位", "劳动者", "原告", "被告", "第三人", "本院", "回迁", "拆迁",
            "撤销", "设立", "注销", "地址", "地点", "位置",
            "农业农村", "贷款", "法律主体", "女儿墙", "党支部", "负责人称",
            "享受", "规定", "同意", "部门", "调差", "砌体", "票权利人",
            "逐级报", "遵循", "负责", "本地建筑", "农村村", "分分区",
            "技术产业", "集团", "融创", "宅基地", "省道",
            "地块", "地上", "停工前", "应按照", "故西", "重新确认",
            # ── 新增：从测试结果分析出的高频误匹配关键词 ──
            "扰乱", "范围内", "国家", "维持", "驳回", "反映", "息地",
            "保护", "金融", "总部", "商务", "制度", "全面", "组织",
            "限制", "一定地", "国医馆", "年郊",
        )
    ):
        return True

    # —— 匹配内容本身是通用表述 ——
    raw_stripped = re.sub(
        r"^(?:涉及所辖|涉及|所辖|各县|各|全|将|及|涉|除特殊企业及|除|等|本|该|此|上|前|后|下)",
        "",
        raw,
    )
    if raw_stripped.endswith(("村民委员会", "居民委员会", "村委会", "居委会")):
        return raw_stripped in {"村村民委员会", "村村委会", "社区居民委员会", "社区居委会"}
    if raw_stripped in {
        "省", "市", "区", "县", "镇", "乡", "村", "街道", "社区", "自治区", "自治州",
        "市甲", "省丙", "其他村", "我村村", "城中村", "安置区", "生活区",
        "年郊区", "年郊", "玉村村",
        "大部分地区", "建设村", "政府农村", "政府报县", "接单区", "逐级报乡",
    }:
        return True

    false_raw_prefixes = (
        "主方", "之后", "乎", "事处", "人石家庄", "代大马", "件规定及", "公司及",
        "三个", "扰乱", "范围内", "国家", "维持", "驳回", "反映一定地",
        "息地生境", "金融总部", "商务", "城一层国医馆", "年郊",
        "利人", "县长岗", "司将", "告", "址湖北", "垫付", "天记录", "委托前往",
        "威华泰", "审斜角头", "家庄", "局同意", "年张岩海上", "年长岗",
        "府各部门", "建二局同意", "建石家庄", "开始出资协助", "待长岗",
        "挥部进驻", "揽石家庄", "日井陉", "日石家庄", "时城中", "曾志学表示",
        "月一年期", "月内进驻", "服石家庄", "照石家庄", "理石家庄",
        "甲方长岗", "祥子送往", "系邢台", "联合开发", "起确认", "订石家庄",
        "销石家庄",
    )
    if raw.startswith(false_raw_prefixes):
        return True

    # 只剩一个字+后缀
    if re.fullmatch(r"[一-龥](?:省|自治区|市|自治州|盟|区|县|旗|镇|乡|街道|村|社区)", raw_stripped):
        return True
    if re.fullmatch(r"[\u4e00-\u9fa5]{2,4}村村", raw_stripped):
        return True

    # —— 地名主体含非地理字符（动词/副词/助词等）——
    body = raw
    for suffix in sorted(_LOCATION_SUFFIXES, key=len, reverse=True):
        if body.endswith(suffix):
            body = body[:-len(suffix)]
            break
    if body and any(c in _NON_GEO_CHARS for c in body):
        return True

    # —— 匹配前有连用的指示词 ——
    false_prefixes = (
        "涉及所辖", "涉及", "所辖", "各县", "除特殊企业及", "除",
        "各", "全", "将", "及", "涉", "等", "本", "该", "此",
        "上", "前", "后", "下",
    )
    for prefix in false_prefixes:
        if raw.startswith(prefix) and len(raw) > len(prefix):
            return True

    # —— 前一个字是修饰/连接成分 ——
    if start > 0:
        char_before = text[start - 1]
        if char_before in _FALSE_LOCATION_LEADING:
            return True

    # —— 已脱敏占位 ——
    if raw.startswith("某") and any(raw.endswith(s) for s in ("省", "市", "区", "县", "镇", "乡", "街道")):
        return True

    return False
