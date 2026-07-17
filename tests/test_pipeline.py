"""集成测试：使用样例文书验证脱敏 pipeline。"""

from dataclasses import replace
from unittest.mock import patch
from legal_redactor.config import PipelineConfig, RedactionProfile
from legal_redactor.pipeline import RedactionPipeline


_SAMPLE_LABOR = """浙江省杭州市西湖区人民法院
民事判决书
（2024）浙0106民初1234号

原告：张三，男，1985年1月1日出生，汉族，公民身份号码330106198501012345。
被告：杭州某某科技有限公司，统一社会信用代码91330106MA2ABCDEFG。
"""


@patch("legal_redactor._samples.load_all_samples", return_value=({}, set()))
def test_pipeline_without_llm(mock_load_samples):
    config = PipelineConfig.offline_without_llm()
    pipeline = RedactionPipeline(config=config)
    result = pipeline.redact(_SAMPLE_LABOR, mode="normal", source_file="test.txt")

    # 人名应被脱敏
    assert "张三" not in result.redacted_text
    # 身份证号应被脱敏
    assert "330106198501012345" not in result.redacted_text
    # 统一社会信用代码不属于默认自动范围；案号仍应随机替换
    assert "91330106MA2ABCDEFG" in result.redacted_text
    assert "（2024）浙0106民初1234号" not in result.redacted_text

    # 非敏感内容应保留
    assert "民事判决书" in result.redacted_text
    assert "汉族" in result.redacted_text

    # 应有映射表
    assert len(result.redaction_map.mappings) > 0


@patch("legal_redactor._samples.load_all_samples", return_value=({}, set()))
@patch("legal_redactor.hanlp_ner.detect_hanlp_ner_candidates")
def test_hanlp_adds_unmatched_person_without_displacing_rule_organization(mock_hanlp, mock_load_samples):
    from legal_redactor.models import Candidate

    text = "经审理查明，李明华负责现场管理。中国农业银行股份有限公司石家庄广安支行提交证据。"
    mock_hanlp.return_value = ([
        Candidate(
            type="person",
            text="李明华",
            start=text.index("李明华"),
            end=text.index("李明华") + len("李明华"),
            source="hanlp_ner",
            confidence=0.88,
            risk_level="medium",
            auto_redact=True,
        ),
    ], None)

    config = replace(PipelineConfig.offline_without_llm(), enable_hanlp_ner=True)
    result = RedactionPipeline(config=config).redact(text, source_file="hanlp.txt")
    originals = {mapping.original for mapping in result.redaction_map.mappings}

    assert "李明华" in originals
    assert "中国农业银行股份有限公司石家庄广安支行" in originals
    mock_hanlp.assert_called_once()


@patch("legal_redactor._samples.load_all_samples", return_value=({}, set()))
@patch("legal_redactor.hanlp_ner.detect_hanlp_ner_candidates")
def test_hanlp_does_not_auto_redact_street_level_location(mock_hanlp, mock_load_samples):
    from legal_redactor.models import Candidate

    text = "项目位于杭州市西湖区文三路。"
    mock_hanlp.return_value = ([
        Candidate(
            type="location",
            text="文三路",
            start=text.index("文三路"),
            end=text.index("文三路") + len("文三路"),
            source="hanlp_ner",
            confidence=0.88,
            risk_level="medium",
            auto_redact=True,
        ),
    ], None)

    config = replace(PipelineConfig.offline_without_llm(), enable_hanlp_ner=True)
    result = RedactionPipeline(config=config).redact(text, source_file="hanlp-location.txt")

    assert "文三路" not in {mapping.original for mapping in result.redaction_map.mappings}
    assert "文三路" in result.redacted_text
    mock_hanlp.assert_called_once()


@patch("legal_redactor._samples.load_all_samples", return_value=({}, set()))
@patch("legal_redactor.hanlp_ner.detect_hanlp_ner_candidates")
def test_hanlp_does_not_redact_court_personnel(mock_hanlp, mock_load_samples):
    from legal_redactor.models import Candidate

    text = "审判长陈志远、书记员周雅婷宣布开庭。"
    mock_hanlp.return_value = ([
        Candidate(
            type="person",
            text="陈志远",
            start=text.index("陈志远"),
            end=text.index("陈志远") + len("陈志远"),
            source="hanlp_ner",
            confidence=0.88,
            risk_level="medium",
            auto_redact=True,
        ),
        Candidate(
            type="person",
            text="周雅婷",
            start=text.index("周雅婷"),
            end=text.index("周雅婷") + len("周雅婷"),
            source="hanlp_ner",
            confidence=0.88,
            risk_level="medium",
            auto_redact=True,
        ),
    ], None)

    config = replace(PipelineConfig.offline_without_llm(), enable_hanlp_ner=True)
    result = RedactionPipeline(config=config).redact(text, source_file="hanlp-court.txt")

    assert "陈志远" not in {mapping.original for mapping in result.redaction_map.mappings}
    assert "周雅婷" not in {mapping.original for mapping in result.redaction_map.mappings}
    assert "陈志远" in result.redacted_text
    assert "周雅婷" in result.redacted_text
    mock_hanlp.assert_called_once()


def test_scan_high_risk_leaks():
    config = PipelineConfig.offline_without_llm()
    pipeline = RedactionPipeline(config=config)
    text_with_phone = "联系电话：13812345678，请回电。"
    result = pipeline.redact(text_with_phone, mode="normal")

    # 脱敏后不应有手机号泄漏
    assert "13812345678" not in result.redacted_text
    # 如果没有映射到，leaks 中应有记录
    # （注意：这取决于模式是否为 semantic_llm_first）
    if result.leaks:
        assert any(leak.type == "phone" for leak in result.leaks)


@patch("legal_redactor._samples.load_all_samples", return_value=({}, set()))
def test_batch_redaction(mock_load_samples):
    config = PipelineConfig.offline_without_llm()
    pipeline = RedactionPipeline(config=config)
    docs = [
        ("doc1.txt", _SAMPLE_LABOR),
        ("doc2.txt", "原告李四诉被告杭州某某科技有限公司。"),
    ]
    result = pipeline.redact_many(docs, mode="normal")

    assert len(result.documents) == 2
    assert "张三" not in result.documents[0].redacted_text
    # 两个文档使用同一映射表，"杭州某某科技有限公司" 应有相同脱敏标签
    masked_in_doc1 = _find_masked_for(result.redaction_map, "杭州某某科技有限公司")
    masked_in_doc2 = _find_masked_for(result.redaction_map, "杭州某某科技有限公司")
    assert masked_in_doc1 == masked_in_doc2


def test_case_number_mapping():
    config = PipelineConfig.offline_without_llm()
    pipeline = RedactionPipeline(config=config)
    
    # Supreme Court case numbers must remain untouched
    text_sup = "最高人民法院民事判决书，案号（2022）最高法民终123号。"
    res_sup = pipeline.redact(text_sup, mode="normal")
    assert "最高法民终123号" in res_sup.redacted_text

    text_sup2 = "最高院案号（2023）最高院民申456号。"
    res_sup2 = pipeline.redact(text_sup2, mode="normal")
    assert "最高院民申456号" in res_sup2.redacted_text
    
    # Regional case numbers must have their province abbreviation replaced
    text_reg = "北京市第一中级人民法院，案号（2021）京01民初456号。"
    res_reg = pipeline.redact(text_reg, mode="normal")
    # "京" should be replaced by a different province abbreviation, so the original case number should not exist
    assert "京01民初456号" not in res_reg.redacted_text


def test_batch_case_number_consistency():
    config = PipelineConfig.offline_without_llm()
    pipeline = RedactionPipeline(config=config)
    
    docs = [
        ("doc1.txt", "（2024）浙0106民初1234号"),
        ("doc2.txt", "（2024）浙0106民初5678号"),
    ]
    res_batch = pipeline.redact_many(docs, mode="normal")
    
    # The abbreviation "浙" should be replaced by the SAME random abbreviation in both documents.
    masked1 = _find_masked_for(res_batch.redaction_map, "（2024）浙0106民初1234号")
    masked2 = _find_masked_for(res_batch.redaction_map, "（2024）浙0106民初5678号")
    
    assert masked1 is not None
    assert masked2 is not None
    
    # Extract the province character from both masked case numbers
    # For example, if mapped to "京", both should have "京" at index 6 (or whatever index it lands on after replacement)
    # Let's extract the character at the index of "浙" in the original (which is 6: "(2024)浙")
    # Actually, the original is "（2024）浙...", where "（" and "）" are full-width parens.
    # Original char 6 is "浙". Let's check that both mapped strings have the SAME mapped province character.
    p1 = masked1[6]
    p2 = masked2[6]
    assert p1 == p2
    assert p1 != "浙"


@patch("legal_redactor._samples.load_all_samples", return_value=({}, set()))
def test_pipeline_analyze_returns_web_confirmation_shape(mock_load_samples):
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())

    analysis = pipeline.analyze("原告张三诉被告杭州某某科技有限公司。")

    groups = analysis["entity_groups"]
    assert any(group["type"] == "person" and group["full_name"] == "张三" for group in groups)
    assert any(
        group["type"] == "organization" and group["full_name"] == "杭州某某科技有限公司"
        for group in groups
    )
    assert isinstance(analysis["locations"], list)


def test_max_effect_llm_failure_falls_back_to_rule_mode():
    pipeline = RedactionPipeline(config=PipelineConfig.max_effect())
    text = "原告张三提交证据，联系电话：13812345678。"
    analysis = {
        "locations": [],
        "companies": [],
        "persons": [],
        "projects": [],
        "reject": [],
        "calibrate": {},
        "error": "simulated failure",
    }

    with patch("legal_redactor.llm.LegalEntityAuditor.extract_sentence_entities", return_value=analysis):
        with patch("legal_redactor.llm.LegalEntityAuditor.audit_and_verify") as audit_and_verify:
            result = pipeline.redact(text)

    audit_and_verify.assert_not_called()
    assert "13812345678" not in result.redacted_text
    assert any("已降级为规则模式" in warning for warning in result.warnings)


def _find_masked_for(redaction_map, original: str) -> str | None:
    for m in redaction_map.mappings:
        if m.original == original:
            return m.masked
    return None


def test_merge_organization_alias_mappings_unifies_batch_company_variants():
    from legal_redactor.models import MappingEntry
    from legal_redactor.postprocess import _merge_organization_alias_mappings

    def org(original: str, masked: str, source: str = "linear:hanlp_ner", role: str | None = None) -> MappingEntry:
        return MappingEntry(
            type="organization",
            original=original,
            masked=masked,
            role=role,
            source=source,
            confidence=0.9,
            restore_by_default=True,
        )

    mappings = [
        org("安徽拓欧建设工程有限公司", "丁省15建设工程公司"),
        org("安徽拓欧建设集团有限公司", "丁省丁公司", source="linear:party_section", role="被告"),
        org("拓欧建设工程有限公司", "癸建设工程公司", source="linear:linear_llm_exact"),
        org("安徽拓欧公司", "丁省11公司"),
        org("拓欧公司", "丁省丁公司", source="linear:party_section", role="被告"),
        org("江苏路达电力工程有限公司", "丙省甲电力工程公司", source="linear:party_section", role="原告"),
        org("江苏载道电力工程有限公司", "己省乙电力工程公司"),
        org("淮安载道电力工程有限公司", "庚省乙电力工程公司", source="linear:party_section", role="原告"),
        org("载道电力工程有限公司", "壬电力工程公司"),
        org("淮安载道公司", "乙公司"),
        org("载道公司", "己公司"),
        org("大唐来安新能源有限公司", "丙新能源公司", source="linear:party_section", role="被告"),
        org("大唐来安新能源公司", "14新能源公司"),
        org("大唐来安公司", "丙公司"),
        org("大唐公司", "丙新能源公司", source="linear:party_section", role="被告"),
        org("河北省电力建设第二工程公司", "甲省电力建设第二工程公司", source="linear:party_section", role="被告"),
        org("河北电建二公司", "甲省11公司", source="linear:linear_llm_exact"),
        org("电建二公司", "11公司", source="linear:linear_llm_exact"),
        org("二建公司", "癸公司"),
        org("河北二建", "12机构", source="linear:linear_llm_exact"),
        org("河北二十冶建设有限公司", "乙省甲公司", source="linear:party_section", role="被告"),
        org("二十冶建设公司", "丁公司"),
        org("沈阳银球建筑工程集团有限公司", "甲公司", source="linear:party_section", role="被告"),
        org("银球建筑公司", "己公司"),
        org("沈阳银球钢结构工程有限公司", "戊公司", source="linear:party_section", role="被告"),
    ]

    merged = _merge_organization_alias_mappings(mappings)
    masks = {mapping.original: mapping.masked for mapping in merged}

    assert masks["安徽拓欧建设工程有限公司"] == "丁省丁公司"
    assert masks["安徽拓欧建设集团有限公司"] == "丁省丁公司"
    assert masks["拓欧建设工程有限公司"] == "丁省丁公司"
    assert masks["安徽拓欧公司"] == "丁公司"
    assert masks["拓欧公司"] == "丁公司"
    assert masks["江苏载道电力工程有限公司"] == "己省乙电力工程公司"
    assert masks["淮安载道电力工程有限公司"] == "庚省乙电力工程公司"
    assert masks["载道电力工程有限公司"] == "庚省乙电力工程公司"
    assert masks["淮安载道公司"] == "乙公司"
    assert masks["载道公司"] == "乙公司"
    assert masks["江苏路达电力工程有限公司"] == "丙省甲电力工程公司"
    assert masks["大唐来安新能源有限公司"] == "丙新能源公司"
    assert masks["大唐来安新能源公司"] == "丙新能源公司"
    assert masks["大唐来安公司"] == "丙公司"
    assert masks["大唐公司"] == "丙公司"
    assert masks["河北省电力建设第二工程公司"] == "甲省电力建设第二工程公司"
    assert masks["河北电建二公司"] == "甲公司"
    assert masks["电建二公司"] == "甲公司"
    assert masks["二建公司"] == "甲公司"
    assert masks["河北二建"] == "甲省电力建设第二工程公司"
    assert masks["河北二十冶建设有限公司"] == "乙省甲公司"
    assert masks["二十冶建设公司"] == "甲公司"
    assert masks["沈阳银球建筑工程集团有限公司"] == "甲公司"
    assert masks["银球建筑公司"] == "甲公司"
    assert masks["沈阳银球钢结构工程有限公司"] == "戊公司"


def test_redact_with_existing_mapping():
    from legal_redactor.models import RedactionMap, MappingEntry
    config = PipelineConfig.offline_without_llm()
    pipeline = RedactionPipeline(config=config)
    
    # 1. Create a base redaction map with manual mappings
    base_map = RedactionMap.create(
        mappings=[
            MappingEntry(type="person", original="张三", masked="张某特别代号", role=None, source="test", confidence=1.0, restore_by_default=True),
            MappingEntry(type="location", original="杭州市", masked="甲市", role=None, source="test", confidence=1.0, restore_by_default=True)
        ],
        mode="standard"
    )
    
    # 2. Redact text containing both mapped entities and a new entity (e.g. 李四)
    text = """原告：张三，住杭州市。
被告：李四，住宁波市。"""
    result = pipeline.redact(text, mode="normal", base_redaction_map=base_map)
    
    # 3. Mapped entities must maintain their previous masks exactly
    assert "张某特别代号" in result.redacted_text
    assert "甲市" in result.redacted_text
    assert "张三" not in result.redacted_text
    assert "杭州市" not in result.redacted_text
    
    # 4. New entity must be detected and mapped to a new mask
    assert "李四" not in result.redacted_text
    assert "宁波市" not in result.redacted_text
    assert "李某" in result.redacted_text


def test_heuristic_optimization_rules():
    from legal_redactor.detectors import (
        _clean_person_name,
        _is_false_person,
        _is_false_org,
        _looks_like_false_location,
        _clean_location_text,
        _clean_organization_text,
        detect_heuristic_ner_candidates,
        parse_party_line,
        _clean_org_simple
    )
    from legal_redactor.hebei_admin import HebeiAdminDivisionDetector
    
    # 1. Trailing particles stripping in person names
    assert _clean_person_name("韩君及") == "韩君"
    assert _clean_person_name("韩君辩") == "韩君"
    assert _clean_person_name("王五等") == "王五"
    assert _clean_org_simple("返还立生公司") == "立生公司"
    assert _clean_org_simple("通知河北友成建工") == "河北友成建工"
    
    # 2. False person validations
    assert _is_false_person("还清原告借款本息") is True
    assert _is_false_person("张三的委托人") is True
    assert _is_false_person("明确") is True
    assert _is_false_person("法庭") is True
    assert _is_false_person("包含") is True
    assert _is_false_person("徐闯提") is True
    assert _is_false_person("方也未") is True
    assert _is_false_person("施工内") is True
    assert _is_false_person("水采暖") is True
    assert _is_false_person("水配管") is True
    assert _is_false_person("水管道") is True
    assert _is_false_person("水管清") is True
    assert _is_false_person("时期其") is True
    assert _is_false_person("应检测") is True
    assert _is_false_person("应实体") is True
    assert _is_false_person("安装费") is True
    assert _is_false_person("法官反") is True
    assert _is_false_person("齐齐聊") is True
    assert _is_false_person("仲裁委") is True
    assert _is_false_person("仲裁时") is True
    assert _is_false_person("应以存") is True
    assert _clean_person_name("钱吗") == "钱"
    assert _is_false_person("钱吗") is True
    assert _is_false_person("李某") is False  # Valid person
    
    # 3. False locations matching check
    assert _looks_like_false_location("进行城中村", 0, 5, "进行城中村") is True
    assert _looks_like_false_location("产权归村", 0, 4, "产权归村") is True
    assert _looks_like_false_location("院丝毫未区", 0, 5, "院丝毫未区") is True
    assert _looks_like_false_location("农业农村部门", 0, 4, "农业农村") is True
    assert _looks_like_false_location("一年期贷款市", 0, 6, "一年期贷款市") is True
    assert _looks_like_false_location("其他村并非具体地点", 0, 3, "其他村") is True
    assert _looks_like_false_location("告井陉县", 0, 4, "告井陉县") is True
    assert _looks_like_false_location("府各部门城中村", 0, 7, "府各部门城中村") is True
    assert _looks_like_false_location("票权利人深圳市", 0, 7, "票权利人深圳市") is True
    assert _looks_like_false_location("三个七里村", 0, 5, "三个七里村") is True
    assert _looks_like_false_location("东地块地上公区", 0, 7, "东地块地上公区") is True
    assert _looks_like_false_location("停工前东区", 0, 5, "停工前东区") is True
    assert _looks_like_false_location("应按照市", 0, 4, "应按照市") is True
    assert _looks_like_false_location("故西区", 0, 3, "故西区") is True
    assert _looks_like_false_location("重新确认市", 0, 5, "重新确认市") is True
    assert _looks_like_false_location("技术产业开发区", 0, 7, "技术产业开发区") is True
    assert _looks_like_false_location("融创集团区", 0, 5, "融创集团区") is True
    assert _looks_like_false_location("老宅基地村", 0, 5, "老宅基地村") is True
    assert _looks_like_false_location("城一层国医馆区", 0, 7, "城一层国医馆区") is True
    assert _looks_like_false_location("起航小镇", 0, 4, "起航小镇") is False
    assert _looks_like_false_location("日照市", 0, 3, "日照市") is False
    for false_location in ("周边小区", "案涉小", "案涉小区", "案涉小区市", "目前", "目前市"):
        assert _looks_like_false_location(false_location, 0, len(false_location), false_location) is True
    
    # 4. Project/Address prefixes stripping
    assert _clean_location_text("项目地点井陉县") == "井陉县"
    assert _clean_location_text("人员进驻长岗村") == "长岗村"
    assert _clean_location_text("提交石家庄市") == "石家庄市"
    
    # 5. False organization action verbs check
    assert _is_false_org("资发放银行") is True
    assert _is_false_org("赵鹏不接受公司") is True
    assert _is_false_org("遵循公司") is True
    assert _is_false_org("根据公司") is True
    assert _is_false_org("房地产开发有限公司") is True
    assert _is_false_org("技术有限公司") is True
    assert _is_false_org("检测技术服务有限公司") is True
    assert _is_false_org("检测技术有限公司") is True
    assert _is_false_org("药业有限公司") is True
    assert _is_false_org("任何公司") is True
    assert _is_false_org("白绍谦公司") is True
    assert _is_false_org("知天煜公司") is True
    assert _is_false_org("否认其与兴代公司系关联公司") is True
    assert _is_false_org("合同一") is True
    assert _is_false_org("纪（天津有限公司") is True
    assert _clean_organization_text("白绍谦无权代表友成公司") == "白绍谦无权代表友成公司"
    assert _clean_organization_text("白绍谦系河北豪木山有限公司") == "白绍谦系河北豪木山有限公司"
    assert _clean_organization_text("解友成公司") == "解友成公司"
    assert _clean_organization_text("说中土公司") == "说中土公司"
    assert _clean_organization_text("非中土公司") == "非中土公司"
    assert _clean_organization_text("借用中土公司") == "借用中土公司"
    assert _clean_organization_text("、腾越建筑科技集团有限公司") == "腾越建筑科技集团有限公司"
    assert _clean_organization_text("世耀包装公司") == "世耀包装公司"
    assert _clean_organization_text("可口可乐公司") == "可口可乐公司"
    assert _clean_organization_text("三快科技有限公司") == "三快科技有限公司"
    assert _clean_organization_text("亿龙建筑工程有限公司") == "亿龙建筑工程有限公司"
    assert _clean_organization_text("中粮可口可乐饮料（天津）有限公司") == "中粮可口可乐饮料（天津）有限公司"
    assert _clean_organization_text("中国建筑第二工程局有限公司") == "中国建筑第二工程局有限公司"
    assert _clean_organization_text("幸福树幼儿园") == "幸福树幼儿园"
    assert _clean_organization_text("到中国二十二冶集团有限公司") == "中国二十二冶集团有限公司"
    assert _clean_organization_text("原沈阳银球钢结构工程有限公司") == "沈阳银球钢结构工程有限公司"
    assert _clean_organization_text("设立的河北二十冶工程技术有限公司") == "河北二十冶工程技术有限公司"
    assert _clean_organization_text("李书玲与中国农业银行股份有限公司石家庄广安支行") == (
        "中国农业银行股份有限公司石家庄广安支行"
    )
    assert not [
        c for c in detect_heuristic_ner_candidates("融创集团区项目")
        if c.text == "融创集团" and c.type == "organization"
    ]
    
    # 6. Party parser protection (sentences starting with a role name are rejected)
    assert parse_party_line("原告还清原告借款本息。") is None
    
    # 7. Single character administrative names prevention
    detector = HebeiAdminDivisionDetector()
    # Mock adding a single character term and verify it is ignored
    terms = {}
    detector._add_term(terms, "镇", "正定镇", "130123", "township", "location", 0.9)
    assert "镇" not in terms


def test_pipeline_llm_calibration():
    from dataclasses import replace
    from legal_redactor.config import PipelineConfig
    from legal_redactor.pipeline import RedactionPipeline
    from legal_redactor.models import Candidate

    # Set up config with LLM enabled
    config = PipelineConfig.offline_without_llm()
    # PipelineConfig is frozen, so use dataclasses.replace
    llm_cfg = replace(config.llm, enabled=True)
    config = replace(config, enable_llm=True, llm=llm_cfg)

    pipeline = RedactionPipeline(config=config)

    # We will mock the auditor and patch it
    mock_audit_res = {
        "locations": [],
        "companies": [{"brand": "友成公司", "variants": []}],
        "persons": [],
        "reject": [],
        "calibrate": {
            "白绍谦无权代表友成公司": "友成公司"
        }
    }

    with patch("legal_redactor.llm.LegalEntityAuditor.audit_and_verify", return_value=mock_audit_res):
        # We simulate candidate detection finding the greedy match
        # Let's mock detect_heuristic_ner_candidates to return the greedy company match
        greedy_candidate = Candidate(
            type="organization",
            text="白绍谦无权代表友成公司",
            start=10,
            end=31,
            source="heuristic_ner",
            confidence=0.8,
            risk_level="high",
            auto_redact=True
        )
        
        with patch(
            "legal_redactor.candidate_collector.detect_party_candidates",
            return_value=([greedy_candidate], []),
        ):
            text = "此案中，白绍谦无权代表友成公司签署协议。"
            res = pipeline.redact(text, mode="normal")
            
            # The final redacted text should NOT contain "友成公司"
            # It should have mapped "友成公司" instead of "白绍谦无权代表友成公司"
            assert "友成公司" not in res.redacted_text
            assert "白绍谦" in res.redacted_text  # since it was calibrated out and not otherwise detected
            
            # Let's check the mappings
            mappings = res.redaction_map.mappings
            # There should be a mapping for "友成公司"
            original_entities = [m.original for m in mappings]
            assert "友成公司" in original_entities
            assert "白绍谦无权代表友成公司" not in original_entities


def test_pipeline_llm_does_not_drop_unlisted_fallback_candidate():
    from dataclasses import replace
    from legal_redactor.config import PipelineConfig
    from legal_redactor.pipeline import RedactionPipeline
    from legal_redactor.models import Candidate

    config = PipelineConfig.offline_without_llm()
    config = replace(
        config,
        enable_llm=True,
        llm=replace(config.llm, enabled=True),
    )
    pipeline = RedactionPipeline(config=config)
    candidate = Candidate(
        type="person",
        text="陈戊靖",
        start=3,
        end=6,
        source="fallback_person",
        confidence=0.7,
        risk_level="medium",
        auto_redact=True,
    )
    audit_result = {
        "locations": [],
        "companies": [],
        "persons": [],
        "reject": [],
        "calibrate": {},
    }

    with (
        patch("legal_redactor.llm.LegalEntityAuditor.audit_and_verify", return_value=audit_result),
        patch("legal_redactor.candidate_collector.detect_fallback_person_candidates", return_value=[candidate]),
    ):
        result = pipeline.redact("经核实陈戊靖负责审计。", mode="normal")

    assert "陈戊靖" not in result.redacted_text


def test_pipeline_ignores_calibration_not_found_near_candidate():
    from dataclasses import replace
    from legal_redactor.config import PipelineConfig
    from legal_redactor.pipeline import RedactionPipeline
    from legal_redactor.models import Candidate

    config = PipelineConfig.offline_without_llm()
    config = replace(
        config,
        enable_llm=True,
        llm=replace(config.llm, enabled=True),
    )
    pipeline = RedactionPipeline(config=config)
    candidate = Candidate(
        type="organization",
        text="友成公司",
        start=3,
        end=7,
        source="heuristic_ner",
        confidence=0.8,
        risk_level="high",
        auto_redact=True,
    )
    audit_result = {
        "locations": [],
        "companies": [],
        "persons": [],
        "reject": [],
        "calibrate": {"友成公司": "不存在公司"},
    }

    with patch("legal_redactor.llm.LegalEntityAuditor.audit_and_verify", return_value=audit_result):
        with patch(
            "legal_redactor.candidate_collector.detect_party_candidates",
            return_value=([candidate], []),
        ):
            result = pipeline.redact("原告友成公司提交证据。", mode="normal")

    originals = {mapping.original for mapping in result.redaction_map.mappings}
    assert "不存在公司" not in originals
    assert "友成公司" in originals


def test_linear_pipeline_expands_locations_and_company_aliases():
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    text = (
        "中国建设银行河北省分行与河北豪木山运输有限公司签订合同。"
        "豪木山公司负责运输，项目位于河北省。"
    )

    result = pipeline.redact(text)

    assert "中国建设银行甲省分行" in result.redacted_text
    assert "甲省甲运输公司" in result.redacted_text
    assert "甲公司负责运输" in result.redacted_text
    assert result.redacted_text.count("甲省") == 3


def test_redact_many_reuses_atomic_location_mappings_across_documents():
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())

    result = pipeline.redact_many(
        [
            ("first.txt", "住所地河北省石家庄市长安区。"),
            ("second.txt", "河北省与石家庄市再次出现。"),
        ]
    )

    masks = {
        mapping.original: mapping.masked
        for mapping in result.redaction_map.mappings
        if mapping.type == "location"
    }
    assert masks["河北省"] == "甲省"
    assert masks["石家庄市"] == "乙市"
    assert masks["长安区"] == "丙区"
    assert result.documents[0].redacted_text == "住所地甲省乙市丙区。"
    assert result.documents[1].redacted_text == "甲省与乙市再次出现。"


def test_linear_pipeline_does_not_add_bare_org_brand_without_alias_context():
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    text = "石家庄誉烁建筑工程有限公司与发包人签订合同。工程款按约支付。"

    result = pipeline.redact(text)
    originals = {mapping.original for mapping in result.redaction_map.mappings}

    assert "石家庄誉烁建筑工程有限公司" in originals
    assert "石家庄誉烁" not in originals


def test_linear_pipeline_adds_bare_org_brand_for_explicit_alias_context():
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    text = "河北豪木山运输有限公司（以下简称豪木山）签订合同。豪木山负责运输。"

    result = pipeline.redact(text)
    originals = {mapping.original for mapping in result.redaction_map.mappings}

    assert "河北豪木山运输有限公司" in originals
    assert "豪木山" in originals
    assert "豪木山负责运输" not in result.redacted_text


def test_linear_pipeline_merges_explicit_former_name_and_company_short_name():
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    text = (
        "石家庄裕华精密铸造有限公司（原名称：鹿泉市裕华精密铸造有限公司）签订合同，"
        "以下简称裕华公司。裕华公司提交证据。"
    )

    result = pipeline.redact(text)

    assert "石家庄裕华精密铸造有限公司" not in result.redacted_text
    assert "鹿泉市裕华精密铸造有限公司" not in result.redacted_text
    assert "裕华公司" not in result.redacted_text
    assert result.redacted_text.count("甲公司") == 4


def test_linear_pipeline_detects_short_company_and_group_names():
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    text = "世耀包装公司提交合同，石药集团出具说明。"

    result = pipeline.redact(text)
    originals = {mapping.original for mapping in result.redaction_map.mappings}

    assert "世耀包装公司" in originals
    assert "石药集团" in originals
    assert "世耀包装公司" not in result.redacted_text
    assert "石药集团" not in result.redacted_text
    assert "公司" in result.redacted_text
    assert "集团" in result.redacted_text


def test_linear_pipeline_detects_complete_bank_branch_and_hospital_names():
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    bank = "中国农业银行股份有限公司石家庄广安支行"
    hospital = "中国人民解放军白求恩国际和平医院"

    result = pipeline.redact(f"原告{bank}与{hospital}提交证据。")

    originals = {mapping.original for mapping in result.redaction_map.mappings}
    assert bank in originals
    assert hospital in originals
    assert "中国农业银行" not in originals
    assert bank not in result.redacted_text
    assert hospital not in result.redacted_text


def test_linear_pipeline_preserves_org_brand_boundary_characters():
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    text = (
        "可口可乐公司、三快科技有限公司、中粮可口可乐饮料（天津）有限公司、"
        "亿龙建筑工程有限公司、中国建筑第二工程局有限公司、幸福树幼儿园提交证据。"
    )

    result = pipeline.redact(text)
    originals = {mapping.original for mapping in result.redaction_map.mappings}

    assert "可口可乐公司" in originals
    assert "三快科技有限公司" in originals
    assert "中粮可口可乐饮料（天津）有限公司" in originals
    assert "亿龙建筑工程有限公司" in originals
    assert "中国建筑第二工程局有限公司" in originals
    assert "幸福树幼儿园" in originals
    assert "可口可乐公司" not in result.redacted_text
    assert "幸福树幼儿园" not in result.redacted_text


def test_standard_profile_keeps_project_location_for_manual_selection():
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    text = "张三住起航小镇，起航小镇项目发生争议。"

    result = pipeline.redact(text)
    originals = {mapping.original for mapping in result.redaction_map.mappings}

    assert "起航小镇" in result.redacted_text
    assert "起航小镇" not in originals
    assert "起航小" not in originals


def test_linear_pipeline_preserves_sample_derived_generic_entity_terms():
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    negatives = (
        "01补鉴定意见书",
        "41#地项目",
        "分包单位",
        "发包人",
        "合同协议书",
        "总包单位",
        "本工程",
        "监理",
        "第三方",
        "交叉施工项目",
        "分包工程",
        "本项目",
        "案涉项目",
        "涉案工程",
    )

    for text in negatives:
        result = pipeline.redact(text)
        assert result.redaction_map.mappings == [], text


def test_linear_pipeline_does_not_fragment_institution_to_admin_division():
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    bank = "中国农业银行股份有限公司石家庄广安支行"
    hospital = "中国人民解放军白求恩国际和平医院"

    result = pipeline.redact(f"{bank}与{hospital}提交证据。")

    originals = {mapping.original for mapping in result.redaction_map.mappings}
    assert bank in originals
    assert hospital in originals
    assert "石家庄" not in originals


def test_linear_pipeline_discovers_person_then_replaces_full_text():
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    text = "原告：张云峰。经审理查明，张云峰提交证据。张云峰称合同有效。"

    result = pipeline.redact(text)

    assert "张云峰" not in result.redacted_text
    assert result.redacted_text.count("张某甲") == 3


def test_location_inside_company_name_is_not_mapped_separately():
    from legal_redactor.models import MappingEntry, RedactionMap

    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    text = "深圳市声旺公司提交材料。"
    base_map = RedactionMap.create(
        mappings=[
            MappingEntry(type="organization", original="深圳市声旺公司", masked="甲公司", role=None, source="test", confidence=1.0, restore_by_default=True),
            MappingEntry(type="location", original="深圳市", masked="甲市", role=None, source="test", confidence=1.0, restore_by_default=True),
        ]
    )

    result = pipeline.redact(text, base_redaction_map=base_map)
    originals = {mapping.original for mapping in result.redaction_map.mappings}

    assert "深圳市声旺公司" in originals
    assert "深圳市" not in originals


def test_location_outside_company_name_is_still_mapped():
    from legal_redactor.models import MappingEntry, RedactionMap

    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    text = "深圳市声旺公司提交材料。项目位于深圳市。"
    base_map = RedactionMap.create(
        mappings=[
            MappingEntry(type="organization", original="深圳市声旺公司", masked="甲公司", role=None, source="test", confidence=1.0, restore_by_default=True),
            MappingEntry(type="location", original="深圳市", masked="甲市", role=None, source="test", confidence=1.0, restore_by_default=True),
        ]
    )

    result = pipeline.redact(text, base_redaction_map=base_map)
    originals = {mapping.original for mapping in result.redaction_map.mappings}

    assert "深圳市声旺公司" in originals
    assert "深圳市" in originals


def test_location_inside_blacklisted_phrase_is_not_mapped_separately():
    from legal_redactor.models import MappingEntry
    from legal_redactor.postprocess import _filter_locations_inside_organizations

    mappings = [
        MappingEntry(type="location", original="深圳市", masked="甲市", role=None, source="test", confidence=1.0, restore_by_default=True),
    ]

    filtered = _filter_locations_inside_organizations(
        "深圳市声旺提交材料。",
        mappings,
        {"深圳市声旺"},
    )
    assert filtered == []

    kept = _filter_locations_inside_organizations(
        "深圳市声旺提交材料。项目位于深圳市。",
        mappings,
        {"深圳市声旺"},
    )
    assert [entry.original for entry in kept] == ["深圳市"]


def test_filter_noise_entity_mappings_drops_contract_numbers_and_clause_orgs():
    from legal_redactor.models import MappingEntry
    from legal_redactor.postprocess import _filter_noise_entity_mappings

    mappings = [
        MappingEntry(type="organization", original="合同一", masked="甲合同", role=None, source="linear_llm_exact", confidence=1.0, restore_by_default=True),
        MappingEntry(type="organization", original="我与兴代公司", masked="乙公司", role=None, source="linear_llm_exact", confidence=1.0, restore_by_default=True),
        MappingEntry(type="organization", original="兴代公司", masked="乙省丁公司", role=None, source="linear_llm_exact", confidence=1.0, restore_by_default=True),
    ]

    filtered = _filter_noise_entity_mappings(mappings)

    assert [entry.original for entry in filtered] == ["兴代公司"]


def test_linear_pipeline_applies_llm_reject_and_calibration():
    from dataclasses import replace
    from legal_redactor.linear_engine import LinearRuleEngine
    from legal_redactor.models import Candidate

    config = PipelineConfig.offline_without_llm()
    config = replace(
        config,
        enable_llm=True,
        llm=replace(config.llm, enabled=True),
    )
    pipeline = RedactionPipeline(config=config)
    analysis = {
        "locations": [],
        "companies": [],
        "persons": [],
        "reject": ["办公区"],
        "calibrate": {"某人无权代表星河公司": "星河公司"},
    }
    text = "办公区完成调整，某人无权代表星河公司签字。"

    with patch(
        "legal_redactor.llm.LegalEntityAuditor.audit_and_verify",
        return_value=analysis,
    ):
        result = pipeline.redact(text)

    assert "办公区" in result.redacted_text

    candidate = Candidate(
        type="organization",
        text="某人无权代表星河公司",
        start=text.index("某人"),
        end=text.index("公司") + 2,
        source="test",
        confidence=0.8,
        risk_level="medium",
        auto_redact=True,
    )
    reviewed = LinearRuleEngine._apply_llm_verdicts([candidate], text, analysis)
    assert [item.text for item in reviewed] == ["星河公司"]


def test_linear_pipeline_max_effect_uses_sentence_extraction():
    from legal_redactor.llm import build_sentence_windows

    config = PipelineConfig.max_effect()
    pipeline = RedactionPipeline(config=config)
    text = "张三住祥云御福澜庭。中建二局提交说明。艺博华府项目发生争议。"
    analysis = {
        "locations": [{"window": "s1", "full": "祥云御福澜庭", "core": "祥云御福澜庭"}],
        "companies": [{"window": "s2", "name": "中建二局", "variants": ["中建二局"]}],
        "persons": [{"window": "s1", "name": "张三", "surname": "张"}],
        "projects": [{"window": "s3", "name": "艺博华府"}],
        "reject": [],
        "calibrate": {},
        "_sentence_windows": build_sentence_windows(text),
    }

    with (
        patch(
            "legal_redactor.llm.LegalEntityAuditor.extract_sentence_entities",
            return_value=analysis,
        ) as extract_sentence_entities,
        patch("legal_redactor.llm.LegalEntityAuditor.audit_and_verify") as audit_and_verify,
    ):
        result = pipeline.redact(text)

    extract_sentence_entities.assert_called_once()
    audit_and_verify.assert_not_called()
    originals = {mapping.original for mapping in result.redaction_map.mappings}
    assert {"张三", "中建二局"} <= originals
    assert "祥云御福澜庭" not in originals
    assert "艺博华府" not in originals
    assert "张三" not in result.redacted_text
    assert "中建二局" not in result.redacted_text
    assert "祥云御福澜庭" in result.redacted_text
    assert "艺博华府" in result.redacted_text


def test_sentence_llm_exact_entities_ignore_optimization_blacklist():
    from legal_redactor.llm import build_sentence_windows

    config = PipelineConfig.max_effect()
    pipeline = RedactionPipeline(config=config)
    text = "原告江苏路达电力工程有限公司，后更名为淮安载道电力工程有限公司。张三住河北省石家庄市长安区。"
    analysis = {
        "locations": [],
        "companies": [
            {
                "window": "s1",
                "name": "淮安载道电力工程有限公司",
                "variants": ["淮安载道电力工程有限公司"],
            }
        ],
        "persons": [{"window": "s1", "name": "张三", "surname": "张"}],
        "projects": [],
        "reject": [],
        "calibrate": {},
        "_sentence_windows": build_sentence_windows(text),
    }

    with patch(
        "legal_redactor.llm.LegalEntityAuditor.extract_sentence_entities",
        return_value=analysis,
    ):
        result = pipeline.redact(text)

    originals = {mapping.original for mapping in result.redaction_map.mappings}
    assert "淮安载道电力工程有限公司" in originals
    assert "张三" in originals
    assert "淮安载道电力工程有限公司" not in result.redacted_text
    assert "张三" not in result.redacted_text


def test_linear_pipeline_balanced_uses_sentence_extraction():
    from legal_redactor.llm import build_sentence_windows

    config = PipelineConfig.balanced_llm()
    pipeline = RedactionPipeline(config=config)
    text = "经核实陈戊靖负责审计。"
    analysis = {
        "locations": [],
        "companies": [],
        "persons": [{"window": "s1", "name": "陈戊靖", "surname": "陈"}],
        "projects": [],
        "reject": [],
        "calibrate": {},
        "_sentence_windows": build_sentence_windows(text),
    }

    with patch("legal_redactor.llm.LegalEntityAuditor.extract_sentence_entities") as extract_sentence_entities:
        with patch(
            "legal_redactor.llm.LegalEntityAuditor.audit_and_verify",
            return_value=analysis,
        ) as audit_and_verify:
            extract_sentence_entities.return_value = analysis
            result = pipeline.redact(text)

    extract_sentence_entities.assert_called_once()
    audit_and_verify.assert_not_called()
    assert "陈戊靖" not in result.redacted_text


def test_linear_pipeline_max_effect_fallback_keeps_fixed_regex():
    config = PipelineConfig.max_effect()
    pipeline = RedactionPipeline(config=config)
    text = (
        "联系电话：13812345678，"
        "身份号码330106198501012345，"
        "案号（2024）浙0106民初1234号。"
    )
    extraction_error = {
        "locations": [],
        "companies": [],
        "persons": [],
        "projects": [],
        "reject": [],
        "calibrate": {},
        "error": "llm unavailable",
    }
    empty_review = {
        "locations": [],
        "companies": [],
        "persons": [],
        "projects": [],
        "reject": [],
        "calibrate": {},
    }

    with patch(
        "legal_redactor.llm.LegalEntityAuditor.extract_sentence_entities",
        return_value=extraction_error,
    ):
        with patch(
            "legal_redactor.llm.LegalEntityAuditor.audit_and_verify",
            return_value=empty_review,
        ):
            result = pipeline.redact(text)

    assert "13812345678" not in result.redacted_text
    assert "330106198501012345" not in result.redacted_text
    assert "（2024）浙0106民初1234号" not in result.redacted_text
    assert any("llm unavailable" in warning for warning in result.warnings)


def test_standard_profile_limits_automatic_scope_to_people_companies_admin_and_direct_identifiers():
    profile = RedactionProfile.standard()

    assert profile.redact_persons is True
    assert profile.redact_organizations is True
    assert profile.redact_locations is True
    assert profile.redact_id_numbers is True
    assert profile.redact_phones is True
    assert profile.redact_projects is False
    assert profile.redact_addresses is False
    assert profile.redact_bank_accounts is False
    assert profile.redact_uscc is False
    assert profile.redact_emails is False
    assert profile.redact_case_numbers is True


def test_standard_profile_keeps_street_project_and_other_non_scope_identifiers():
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    text = (
        "张三在河北省石家庄市长安区建华大街88号承建起航小镇项目。"
        "邮箱zhang@example.com，统一社会信用代码91110108MA0000000A，"
        "银行账号6222020202020202020，案号（2024）冀0101民初123号。"
        "联系电话：13800138000，身份证号11010519491231002X。"
    )

    result = pipeline.redact(text)
    originals = {mapping.original for mapping in result.redaction_map.mappings}

    assert "张三" in originals
    assert "河北省" in originals
    assert "石家庄市" in originals
    assert "长安区" in originals
    assert "13800138000" in originals
    assert "身份证号11010519491231002X" in originals
    assert "建华大街88号" not in originals
    assert "起航小镇项目" not in originals
    assert "zhang@example.com" not in originals
    assert "91110108MA0000000A" not in originals
    assert "6222020202020202020" not in originals
    assert "（2024）冀0101民初123号" in originals
    assert "建华大街88号" in result.redacted_text
    assert "起航小镇项目" in result.redacted_text
    assert "zhang@example.com" in result.redacted_text
    assert "91110108MA0000000A" in result.redacted_text
    assert "6222020202020202020" in result.redacted_text
    assert "（2024）冀0101民初123号" not in result.redacted_text


def test_standard_profile_keeps_township_and_village_locations_for_manual_selection():
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    text = "张三居住在河北省石家庄市长安区建华街道和平村。"

    result = pipeline.redact(text)
    originals = {mapping.original for mapping in result.redaction_map.mappings}

    assert {"河北省", "石家庄市", "长安区"} <= originals
    assert "建华街道" not in originals
    assert "和平村" not in originals
    assert "建华街道" in result.redacted_text
    assert "和平村" in result.redacted_text


def test_linear_pipeline_rejects_legal_phrases_as_people_or_locations():
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    text = "本院认为应予支持，各方当事人无异议，农业农村部门提交意见。"

    result = pipeline.redact(text)

    assert result.redacted_text == text


def test_linear_pipeline_uses_hanlp_ner_candidates():
    from legal_redactor.models import Candidate

    config = replace(
        PipelineConfig.offline_without_llm(),
        enable_hanlp_ner=True,
    )
    pipeline = RedactionPipeline(config=config)
    text = "庭审中马戈陈述了付款经过。"
    hanlp_candidate = Candidate(
        type="person",
        text="马戈",
        start=text.index("马戈"),
        end=text.index("马戈") + len("马戈"),
        source="hanlp_ner",
        confidence=0.88,
        risk_level="medium",
        auto_redact=True,
    )

    with patch(
        "legal_redactor.hanlp_ner.detect_hanlp_ner_candidates",
        return_value=([hanlp_candidate], None),
    ) as detect_hanlp:
        result = pipeline.redact(text)

    detect_hanlp.assert_called_once()
    assert "马戈" not in result.redacted_text
    assert any(
        mapping.original == "马戈" and mapping.source == "linear:hanlp_ner"
        for mapping in result.redaction_map.mappings
    )


def test_linear_pipeline_filters_latest_sample_boundary_noise():
    config = replace(PipelineConfig.offline_without_llm())
    pipeline = RedactionPipeline(config=config)
    text = (
        "原告原名江苏载道电力工程有限公司。"
        "证据一中大唐公司与河北二建签订合同。"
        "被告二大唐公司的管理要求，大唐公司找到的拓欧公司。"
        "原告从未找拓欧公司主张过工程款。"
        "针对张玉龙这五份微信聊天记录，该聊天记录首先拓公司不知情。"
        "各方是否同意调解\n原告：同意。\n"
        "大唐公司：第一，就案涉项目而言，原告与大唐公司之间不存在合同关系。"
    )

    result = pipeline.redact(text)
    originals = {mapping.original for mapping in result.redaction_map.mappings}

    assert "大唐公司" in originals
    assert "拓欧公司" in originals
    assert "一中大唐公司" not in originals
    assert "二大唐公司" not in originals
    assert "未找拓欧公司" not in originals
    assert "聊天记录首先拓公司" not in originals
    assert "名江苏载道电力工程有限公司" not in originals
    assert "同意" not in originals
    assert "第一" not in originals
