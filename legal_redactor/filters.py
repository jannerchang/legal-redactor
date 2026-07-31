"""Shared clean/reject helpers for entity filtering.

These functions validate and clean candidate entity text (person names,
organization names, locations). They depend only on the lexicon so that a
future judgment layer (HanLP / LLM) can reuse them without pulling in the
full detection machinery from detectors.py.
"""

from __future__ import annotations

import re

from .lexicon import (
    COMMON_SURNAME_CHARS,
    FALSE_ORG_BRANDS,
    FALSE_ORG_EXACT_CORES,
    FALSE_PERSON_WORDS,
    INDUSTRY_CORE_SUFFIXES,
    LEGAL_SUFFIXES,
    PROVINCE_NAMES,
)

# Aliases mirroring the former detectors private names, so the relocated
# function bodies (which reference these underscore names) stay verbatim.
_FALSE_PERSON_WORDS = FALSE_PERSON_WORDS
_FALSE_ORG_BRANDS = FALSE_ORG_BRANDS
_FALSE_ORG_EXACT_CORES = FALSE_ORG_EXACT_CORES
_COMMON_SURNAME_CHARS = COMMON_SURNAME_CHARS
_INDUSTRY_CORE_SUFFIXES = INDUSTRY_CORE_SUFFIXES


def clean_person_name(value: str) -> str:
    """清理人名：剥离首尾多余括号及不匹配的标点，裁剪多余的尾随助词/连词/介词/动作词"""
    value = value.strip(" ：:，,。；;\n\t（）()")
    value = _clean_unbalanced_brackets(value)
    # 剥离末尾可能被误匹配进去的助词、连词、介词或动作词
    while len(value) >= 2 and value[-1] in "及辩诉称和与等已在于男女将被原吗呢吧啊呀":
        value = value[:-1]
    return value.strip()


def is_false_person(value: str) -> bool:
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
    # 高频动作尾字只在候选本身不是常见姓氏开头时拦截，避免误杀“杨利进”一类真实姓名。
    _TAIL_ACTION_CHARS = frozenset(
        "全均承提抗扣图聊反送担到打替找查验收据向属力监者称证过进内无赔手"
        "交破期满合范工费还详适关就形备规约债票项款应出"
        "拨支负签协公"
    )
    if len(value) == 3 and value[0] not in _COMMON_SURNAME_CHARS and value[-1] in _TAIL_ACTION_CHARS:
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


# 常见的非品牌名词汇——当这些词作为公司名的"品牌"部分时，说明是误识别
# Relocated to lexicon.FALSE_ORG_BRANDS / FALSE_ORG_EXACT_CORES; aliases kept
# because _is_false_org references them by these private names.
_FALSE_ORG_BRANDS = FALSE_ORG_BRANDS
_FALSE_ORG_EXACT_CORES = FALSE_ORG_EXACT_CORES

_COMMON_SURNAME_CHARS = COMMON_SURNAME_CHARS

# 公司字号末尾常见的行业/业务词，与动作动词同形但不应单独触发误杀。
_INDUSTRY_CORE_SUFFIXES = INDUSTRY_CORE_SUFFIXES


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
# Derived from lexicon.LEGAL_SUFFIXES (same 7 members) to avoid a duplicate literal.
_PURE_LEGAL_SUFFIXES = frozenset(LEGAL_SUFFIXES)

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

def _org_has_disclaimer_or_contract_ref(value: str) -> bool:
    if re.fullmatch(r"合同[一二三四五六七八九十百零\d]+", value):
        return True
    if "系关联公司" in value or value.startswith(("否认其", "否认与")):
        return True
    return False


def _org_bracket_shape_invalid(value: str) -> bool:
    if "（" in value or "）" in value or "(" in value or ")" in value:
        if not re.fullmatch(r"[一-龥A-Za-z0-9·]+[（(][一-龥A-Za-z0-9·]{2,12}[）)][一-龥A-Za-z0-9·]*(?:有限责任公司|股份有限公司|集团有限公司|有限公司|公司|集团)", value):
            return True
    return False


# 长句特征词：带有明显合同、证据、诉讼等非机构特征时为误识别。
_ORG_LONG_SENTENCE_NOISE = (
    "合同", "证据", "佐证", "在卷", "协议", "诉讼", "裁判", "本案", "案涉",
    "原告", "被告", "第三人", "本院", "转账", "凭证", "案卷",
)

# 不带公司/集团后缀时，core 级别的代词/数量指代词，命中即误识别。
_ORG_VALUE_NOISE_WITHOUT_SUFFIX = (
    "我", "你", "他", "本", "该", "贵", "此", "两", "两家", "各", "各家",
    "某", "一", "两个", "几家", "见两个",
)


def _org_core_is_false(core: str) -> bool:
    """检查去掉法律后缀后的品牌核心是否为误识别。"""
    # ── 过滤由常用代词、语气词或国家/通用指代代词构成的伪字号 ──
    if core in _ORG_FALSE_CORE_PREFIXES:
        return True
    if len(core) < 2:
        return True
    if "我" in core or "两家" in core or core.endswith(("等", "等公司")):
        return True
    if core.endswith(("省", "市", "区", "县", "旗", "镇", "乡", "街道", "村", "社区")):
        return True
    if re.fullmatch(r"[一-龥]{2,3}", core) and core[0] in _COMMON_SURNAME_CHARS:
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
    return False


def _org_value_is_false_without_suffix(value: str) -> bool:
    # 如果不带公司/集团后缀，直接检查 core 级别的非地理/动作词
    if any(noise in value for noise in _ORG_VALUE_NOISE_WITHOUT_SUFFIX):
        return True
    if _core_has_action_verb_noise(value, _ORG_ACTION_VERBS):
        return True
    return False


def is_false_org(value: str) -> bool:
    """检查清理后的公司名是否为误识别（如"家具有限公司"、"有限责任公司"）。"""
    if _org_has_disclaimer_or_contract_ref(value):
        return True

    # 纯法律后缀，无品牌
    if value in _PURE_LEGAL_SUFFIXES:
        return True
    if _org_bracket_shape_invalid(value):
        return True

    # 过滤带有明显合同、证据、诉讼等非机构特征的长句。
    if any(noise in value for noise in _ORG_LONG_SENTENCE_NOISE):
        return True

    # 去掉法律后缀后，检查剩余部分
    for sfx in sorted(_PURE_LEGAL_SUFFIXES, key=len, reverse=True):
        if value.endswith(sfx) and len(value) > len(sfx):
            if _org_core_is_false(value[:-len(sfx)]):
                return True
            break
    else:
        if _org_value_is_false_without_suffix(value):
            return True

    return False


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


def clean_organization_text(value: str) -> str:
    value = value.strip(" ：:，,。、；;\n\t（）()")
    value = _clean_unbalanced_brackets(value)
    value = re.sub(r"(有限责任公司|股份有限公司|集团有限公司|有限公司)公司$", r"\1", value)
    _org_sfx = ["有限责任公司","股份有限公司","集团有限公司","有限公司",
                "律师事务所","会计师事务所","公司","集团","经营部",
                "安装部","安装队","经销处","商行","工作室","委员会",
                "管理局","公安局","税务局","中心","医院","学校",
                "幼儿园","银行","个体工商户","厂","店"]
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
    value = _strip_org_narrative_prefixes(value)
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


# 文书叙述前缀：明确不属于机构本体（“到…公司”“原…公司”“设立的…公司”）
_ORG_NARRATIVE_PREFIX_RE = re.compile(
    r"^(?:"
    r"设立的|成立的|注册的|组建的|"
    r"设立|成立|注册|"
    r"到(?=[\u4e00-\u9fa5A-Za-z0-9()（）·]{4,}"
    r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司|集团))|"
    r"原(?=[\u4e00-\u9fa5]{4,}"
    r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司))"
    r")"
)

# “人名 + 与/和/及 + 机构”叙述：清洗时只保留机构本体
_PERSON_WITH_ORG_RE = re.compile(
    r"^(?P<person>[\u4e00-\u9fa5·]{2,4})(?:与|和|及)(?P<rest>.+)$"
)
_ORG_SURFACE_MARKERS = (
    "有限责任公司",
    "股份有限公司",
    "集团有限公司",
    "有限公司",
    "律师事务所",
    "会计师事务所",
    "公司",
    "集团",
    "银行",
    "分行",
    "支行",
)


def _strip_org_narrative_prefixes(value: str) -> str:
    """循环剥离机构表面形式左侧的明确叙述前缀与“人名与机构”连接。"""
    changed = True
    while value and changed:
        changed = False
        stripped = _ORG_NARRATIVE_PREFIX_RE.sub("", value, count=1).strip(" ：:，,。、；;\n\t")
        if stripped != value:
            value = stripped
            changed = True
            continue
        person_org = _PERSON_WITH_ORG_RE.match(value)
        if not person_org:
            break
        person = person_org.group("person")
        rest = person_org.group("rest").strip(" ：:，,。、；;\n\t")
        if (
            rest
            and not any(marker in person for marker in _ORG_SURFACE_MARKERS)
            and any(marker in rest for marker in _ORG_SURFACE_MARKERS)
        ):
            value = rest
            changed = True
    return value


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

# 文书指代/程序性前缀：整段或以它们起头的“地名”不是真实行政区划
# （如 案涉小区市、周边小区、目前市）。可维护扩展，避免单字特判。
_FALSE_LOCATION_REFERENCE_PREFIXES = (
    "案涉",
    "周边",
    "目前",
    "本案",
    "该案",
    "上述",
    "涉案",
    "本市",
    "本省",
    "本区",
    "本县",
    "本村",
)

# 去掉行政区划后缀后仍属非地名词核（含残缺截断如“案涉小”）
_FALSE_LOCATION_NON_PLACE_CORES = frozenset(
    {
        "周边",
        "案涉",
        "目前",
        "案涉小",
        "案涉小区",
        "周边小区",
        "本案",
        "该案",
        "上述",
        "涉案",
    }
)



def looks_like_false_location(text: str, start: int, end: int, raw: str) -> bool:
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
    if raw in _FALSE_LOCATION_NON_PLACE_CORES or raw_stripped in _FALSE_LOCATION_NON_PLACE_CORES:
        return True
    if any(raw.startswith(prefix) for prefix in _FALSE_LOCATION_REFERENCE_PREFIXES):
        return True
    if any(raw_stripped.startswith(prefix) for prefix in _FALSE_LOCATION_REFERENCE_PREFIXES):
        return True
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
    if body in _FALSE_LOCATION_NON_PLACE_CORES:
        return True
    if body and any(body.startswith(prefix) for prefix in _FALSE_LOCATION_REFERENCE_PREFIXES):
        return True
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
