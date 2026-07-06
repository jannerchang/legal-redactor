"""Shared lexicon constants and compiled patterns for legal redaction."""

from __future__ import annotations

import re

LEGAL_SUFFIXES = (
    "有限责任公司",
    "股份有限公司",
    "集团有限公司",
    "有限公司",
    "幼儿园",
    "公司",
    "集团",
)

INSTITUTION_SUFFIXES = (
    "保险股份有限公司",
    "保险有限公司",
    "保险公司",
    "商业银行股份有限公司",
    "股份制商业银行",
    "农村商业银行",
    "商业银行",
    "银行",
    "人民法院",
    "人民检察院",
    "公安局",
    "税务局",
)

INDUSTRY_TERMS = (
    "房地产开发",
    "饮料",
    "建筑工程",
    "建设工程",
    "电力建设",
    "电力工程",
    "园林绿化工程",
    "装饰工程",
    "设计",
    "新能源",
    "运输",
    "物流",
    "科技",
    "教育科技",
    "文化传媒",
    "物业管理",
    "人力资源服务",
    "燃气",
    "水务",
    "医药",
    "药业",
    "钢铁",
    "电子商务",
    "贸易",
    "商贸",
    "咨询",
    "服务",
)

INDUSTRY_TERMS_BY_LEN = tuple(sorted(INDUSTRY_TERMS, key=len, reverse=True))

PROVINCE_NAMES = (
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
    "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
    "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
)

ORG_FULL_RE = re.compile(
    r"(?:^|(?<=[\s，,。；;：:、（(与和及由向对给找]))"
    r"[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,30}?"
    r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司|"
    r"律师事务所|会计师事务所|保险公司|商业银行|幼儿园|公司|集团|银行)"
)

BARE_COMPANY_ALIAS_RE = re.compile(
    r"(?:^|[，。；、\n：:]|找到的|从未找|未找|直接找|找|与|和|由|对|"
    r"证据[一二三四五六七八九十\d]+中|"
    r"原告|被告[一二三四五六七八九十\d]?|第三人)"
    r"(?P<alias>(?!(?:原告|被告|第三人|从未找|未找|直接找|找|聊天记录首先|证据[一二三四五六七八九十\d]+中))"
    r"[\u4e00-\u9fa5A-Za-z0-9·]{2,8}(?:公司|集团))"
)

FACT_SECTION_BOUNDARY_RE = re.compile(r"本院(?:经审理|经审查|审理)?认为")

# Common Chinese surnames (single + compound) for person-name validation.
# Shared between detectors.py fallback matching and false-person filtering.
COMMON_SURNAMES = frozenset(
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

# Generic industry/brand words that should not be treated as company brand names.
# Consolidated from pipeline.GENERIC_BRAND_BLACKLIST and detectors._FALSE_ORG_BRANDS.
GENERIC_BRAND_BLACKLIST = frozenset({
    "开发", "建设", "工程", "集团", "贸易", "商贸", "物业", "投资", "科技",
    "信息", "网络", "电子商务", "电子", "新材料", "服务", "咨询", "代理",
    "管理", "资产", "金融", "工业", "农业", "商业", "联合", "发展", "实业",
    "劳务", "建筑", "装饰", "物流", "运输", "环保", "能源", "置业", "产业",
    "燃气", "水务", "热力", "供热", "供水", "排水", "电力", "交通",
    "家具", "家居", "设备", "材料", "建材", "食品", "服装", "药品", "商品",
    "货物", "物品", "物资", "器材", "器械", "用品", "产品", "配件", "零件",
    "购买", "销售", "生产", "加工", "制造", "维修", "安装", "承包",
    "租赁", "出租", "策划",
    "有限", "责任", "股份",
    "检测", "检验", "造价", "质检",
})

# Words that should never be recognized as person names (legal/case
# vocabulary, procedural verbs, colloquial generics, high-frequency
# mis-recognition terms). Shared by detectors._is_false_person and
# pipeline. Members preserved verbatim from the former detectors copy.
FALSE_PERSON_WORDS = frozenset({
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

# Curated subset of single-character common surnames used by
# detectors._is_false_org to reject 2-3 char company cores whose first
# char is a surname (i.e. a person name misread as an org brand). This is
# deliberately *smaller* than COMMON_SURNAMES: using the full set would
# over-suppress real short company names. Not derivable from
# COMMON_SURNAMES — kept as its own curated list.
COMMON_SURNAME_CHARS = frozenset(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜谢范彭马苗方袁唐薛雷贺倪汤罗郝安常于傅康伍余顾孟黄萧尹姚邵汪毛董梁杜阮贾路江郭梅林钟徐邱骆高夏蔡田胡万卢莫曾白王"
)

# Generic non-brand words: when these appear as the "brand" portion of a
# company name it is a mis-recognition. Used by detectors._is_false_org.
# Members preserved verbatim; intentionally NOT unioned with
# GENERIC_BRAND_BLACKLIST (that would over-kill real companies such as
# "甲科技有限公司" via the endswith+short-prefix rule).
FALSE_ORG_BRANDS = frozenset({
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

# Multi-word exact cores that are false organizations when matched exactly.
# Used by detectors._is_false_org. Note: "策划" also appears in
# GENERIC_BRAND_BLACKLIST and FALSE_ORG_BRANDS; kept here because the
# exact-core check is a distinct semantic role.
FALSE_ORG_EXACT_CORES = frozenset({
    "工程", "建筑劳务", "建设", "房地产", "房地产开发", "技术", "科技", "燃气",
    "药业", "生态环境", "独资", "留存", "完善", "扩大适用",
    "检测技术", "检测技术服务", "工程质检技术",
    # ── 新增：从黑名单分析出的纯行业词核心 ──
    "建筑材料设备检验", "工程造价", "建工技术", "电子", "声旺",
    "建筑安装", "建筑科技", "建设工程", "水电开发", "企业发展",
    "流域水电", "网络技术", "信息技术", "策划",
})

# Industry/business suffix words that coincide with action verbs but must
# NOT trigger the action-verb noise kill in detectors._core_has_action_verb_noise.
# Distinct from INDUSTRY_TERMS (which feeds pipeline detection); only 7 items
# overlap. Members preserved verbatim.
INDUSTRY_CORE_SUFFIXES = frozenset({
    "运输", "建设", "工程", "制造", "销售", "租赁", "装饰", "物流", "物业",
    "开发", "投资", "科技", "信息", "服务", "咨询", "代理", "管理", "贸易",
    "商贸", "建筑", "劳务", "环保", "能源", "置业", "产业", "电力", "水利",
})
