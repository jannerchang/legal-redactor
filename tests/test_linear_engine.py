from __future__ import annotations

from dataclasses import dataclass, replace

import pytest
from unittest.mock import patch

from legal_redactor.counters import TypeCounters
from legal_redactor.candidate_collector import (
    CandidateCollectionContext,
    CandidateCollector,
)
from legal_redactor.candidate_resolution import resolve_candidate_overlaps
from legal_redactor.linear_engine import LinearRuleEngine
from legal_redactor.org_masking import (
    derived_organization_alias_cores,
    explicit_organization_aliases,
    has_explicit_bare_brand_alias,
)
from legal_redactor.location_utils import get_location_core, location_suffix, strip_leading_locations
from legal_redactor.models import Candidate, MappingEntry, sort_mapping_entries
from legal_redactor.config import PipelineConfig
from legal_redactor.pipeline import RedactionPipeline


@dataclass
class _Profile:
    redact_locations: bool = True
    redact_persons: bool = True
    redact_organizations: bool = True
    redact_projects: bool = True


def _engine(*, sample_blacklist: set[str] | None = None) -> LinearRuleEngine:
    counters = TypeCounters()
    prefixes: dict[str, str] = {}

    def get_location_prefix(name: str) -> str:
        core = get_location_core(name)
        if core not in prefixes:
            prefixes[core] = counters.next("location")
        return prefixes[core]

    return LinearRuleEngine(
        counters=counters,
        profile=_Profile(),
        sample_blacklist=sample_blacklist or set(),
        get_location_prefix=get_location_prefix,
    )


def _discover(
    text: str,
    *,
    candidates: list[Candidate],
    llm_analysis: dict | None = None,
    sample_blacklist: set[str] | None = None,
) -> list[MappingEntry]:
    return _engine(sample_blacklist=sample_blacklist).discover(
        text,
        candidates,
        llm_analysis or {},
    )


def test_get_location_core_recursively_strips_admin_suffixes() -> None:
    assert get_location_core("起航小镇") == "起航小镇"
    assert get_location_core("石家庄市裕华区") == "石家庄市裕华"
    assert get_location_core("河北省") == "河北"
    assert get_location_core("河北省石家庄市") == "河北省石家庄"


def test_location_suffix_prefers_longest_admin_suffix() -> None:
    assert location_suffix("河北省") == "省"
    assert location_suffix("祥云御福澜庭") == "地"


def test_strip_leading_locations_removes_multiple_known_prefixes() -> None:
    known = {
        "河北省": "甲省",
        "石家庄市": "乙市",
    }
    prefix, body = strip_leading_locations("河北省石家庄市星河建设有限公司", known)
    assert prefix == "甲省乙市"
    assert body == "星河建设有限公司"


def test_company_mask_omits_city_prefix_and_does_not_invent_country_place_prefix():
    engine = _engine()
    engine.source_text = (
        "石家庄融创贵和房地产开发有限公司与"
        "中国建筑第二工程局有限公司签订合同。"
    )
    for value in ("石家庄融创贵和房地产开发有限公司", "中国建筑第二工程局有限公司"):
        engine.accept_organization(
            Candidate(
                type="organization",
                text=value,
                start=engine.source_text.index(value),
                end=engine.source_text.index(value) + len(value),
                source="linear_llm_exact",
                confidence=0.95,
                risk_level="medium",
                auto_redact=True,
            )
        )

    by_original = {mapping.original: mapping.masked for mapping in engine.mappings}

    assert by_original["石家庄融创贵和房地产开发有限公司"] == "甲房地产开发公司"
    assert by_original["中国建筑第二工程局有限公司"] == "乙公司"




def test_derived_organization_alias_cores_includes_brand_and_number_aliases() -> None:
    cores = derived_organization_alias_cores("河北省电力建设第二工程公司")
    assert "电建" in cores
    assert "二建" in cores


def test_explicit_organization_aliases_finds_former_name_and_short_name() -> None:
    text = (
        "石家庄裕华精密铸造有限公司（原名称：鹿泉市裕华精密铸造有限公司）签订合同，"
        "以下简称裕华公司。"
    )
    aliases = explicit_organization_aliases(text, "石家庄裕华精密铸造有限公司")
    assert "鹿泉市裕华精密铸造有限公司" in aliases
    assert "裕华公司" in aliases


def test_explicit_organization_aliases_finds_bare_short_name() -> None:
    text = "华北制药股份有限公司（以下简称华药）与中技公司签订合同。华药确认事实。"

    aliases = explicit_organization_aliases(text, "华北制药股份有限公司")

    assert "华药" in aliases


def test_explicit_organization_aliases_does_not_cross_contaminate_party_short_names() -> None:
    text = (
        "河北云厚建筑装饰工程有限公司（以下简称云厚公司）与"
        "河北兴代建筑安装工程有限公司（以下简称兴代公司）及"
        "石家庄方卫信息系统技术有限公司（以下简称方卫公司）签订合同。"
    )

    assert explicit_organization_aliases(text, "云厚公司") == []
    assert explicit_organization_aliases(text, "兴代公司") == []
    assert explicit_organization_aliases(text, "河北云厚建筑装饰工程有限公司") == ["云厚公司"]
    assert explicit_organization_aliases(text, "河北兴代建筑安装工程有限公司") == ["兴代公司"]


def test_has_explicit_bare_brand_alias_detects_parenthetical_short_name() -> None:
    text = "河北豪木山运输有限公司（以下简称豪木山）签订合同。"
    assert has_explicit_bare_brand_alias(text, "豪木山") is True
    assert has_explicit_bare_brand_alias(text, "豪木山运输") is False


@pytest.mark.parametrize(
    ("value", "suffix"),
    [
        ("高新区泽行机械设备安装队", "安装队"),
        ("藁城区尚远机械设备安装部", "安装部"),
        ("泽新经销处", "经销处"),
    ],
)
def test_accept_organization_masks_named_business_outlets(value: str, suffix: str) -> None:
    engine = _engine()
    engine.source_text = value

    engine.accept_organization(
        Candidate(
            type="organization",
            text=value,
            start=0,
            end=len(value),
            source="full_document_llm",
            confidence=0.9,
            risk_level="medium",
            auto_redact=True,
        )
    )

    assert [(mapping.original, mapping.masked) for mapping in engine.mappings] == [
        (value, f"甲{suffix}")
    ]


def test_accept_location_maps_full_name_and_core() -> None:
    engine = _engine()
    candidate = Candidate(
        type="location",
        text="河北省",
        start=0,
        end=3,
        source="test",
        confidence=0.9,
        risk_level="low",
        auto_redact=True,
    )
    engine.source_text = "河北省某公司"
    engine.accept_location(candidate)

    originals = {mapping.original for mapping in engine.mappings}
    assert "河北省" in originals


def test_accept_person_masks_repeated_name() -> None:
    engine = _engine()
    engine.source_text = "原告张云峰提交证据。张云峰到庭。"
    for start in (2, 11):
        engine.accept_person(
            Candidate(
                type="person",
                text="张云峰",
                start=start,
                end=start + 3,
                source="party_section",
                confidence=0.95,
                risk_level="low",
                auto_redact=True,
            )
        )
    assert len(engine.mappings) == 1
    assert engine.mappings[0].masked.startswith("张某")


def test_accept_organization_skips_bare_brand_without_alias_context() -> None:
    engine = _engine()
    engine.source_text = "石家庄誉烁建筑工程有限公司签订合同。"
    engine.accept_organization(
        Candidate(
            type="organization",
            text="石家庄誉烁建筑工程有限公司",
            start=0,
            end=14,
            source="linear_full_org",
            confidence=0.9,
            risk_level="medium",
            auto_redact=True,
        )
    )
    originals = {mapping.original for mapping in engine.mappings}
    assert "石家庄誉烁建筑工程有限公司" in originals
    assert "石家庄誉烁" not in originals


def test_accept_organization_adds_bare_brand_with_explicit_alias_context() -> None:
    engine = _engine()
    engine.source_text = "河北豪木山运输有限公司（以下简称豪木山）签订合同。豪木山负责运输。"
    engine.accept_organization(
        Candidate(
            type="organization",
            text="河北豪木山运输有限公司",
            start=0,
            end=12,
            source="linear_full_org",
            confidence=0.9,
            risk_level="medium",
            auto_redact=True,
        )
    )
    originals = {mapping.original for mapping in engine.mappings}
    assert "河北豪木山运输有限公司" in originals
    assert "豪木山" in originals


def test_accept_organization_masks_institution_with_known_location() -> None:
    engine = _engine()
    engine.known_locations = {"河北省": "甲省", "河北": "甲省"}
    engine.source_text = "中国建设银行河北省分行签订合同。"
    engine.accept_organization(
        Candidate(
            type="organization",
            text="中国建设银行河北省分行",
            start=0,
            end=12,
            source="linear_full_org",
            confidence=0.9,
            risk_level="medium",
            auto_redact=True,
        )
    )
    assert engine.mappings
    assert engine.mappings[0].masked == "中国建设银行甲省分行"


def test_apply_llm_verdicts_rejects_and_calibrates_candidates() -> None:
    text = "办公区完成调整，某人无权代表星河公司签字。"
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
    analysis = {
        "reject": ["办公区"],
        "calibrate": {"某人无权代表星河公司": "星河公司"},
    }
    reviewed = LinearRuleEngine._apply_llm_verdicts([candidate], text, analysis)
    assert [item.text for item in reviewed] == ["星河公司"]


def test_resolve_candidate_overlaps_prefers_higher_priority_source() -> None:
    organization = Candidate(
        type="organization",
        text="星河建设有限公司",
        start=10,
        end=18,
        source="party_section",
        confidence=0.95,
        risk_level="low",
        auto_redact=True,
    )
    person = Candidate(
        type="person",
        text="星河建设有限公司",
        start=10,
        end=18,
        source="hanlp_ner",
        confidence=0.99,
        risk_level="medium",
        auto_redact=True,
    )
    resolved = resolve_candidate_overlaps([person, organization])
    assert len(resolved) == 1
    assert resolved[0].source == "party_section"


def test_resolve_candidate_overlaps_prefers_full_document_exact_person_boundary() -> None:
    rule = Candidate(
        type="person",
        text="许永亮因",
        start=2,
        end=6,
        source="party_section",
        confidence=1.0,
        risk_level="high",
        auto_redact=True,
    )
    registry = Candidate(
        type="person",
        text="许永亮",
        start=2,
        end=5,
        source="full_document_llm",
        confidence=0.9,
        risk_level="medium",
        auto_redact=True,
    )

    resolved = resolve_candidate_overlaps([rule, registry])

    assert [(candidate.text, candidate.source) for candidate in resolved] == [
        ("许永亮", "full_document_llm")
    ]



def test_collect_keeps_higher_confidence_for_same_span() -> None:
    lower = Candidate(
        type="organization",
        text="兴代公司",
        start=5,
        end=9,
        source="linear_full_org",
        confidence=0.9,
        risk_level="medium",
        auto_redact=True,
    )
    higher = Candidate(
        type="organization",
        text="兴代公司",
        start=5,
        end=9,
        source="linear_bare_org_alias",
        confidence=0.91,
        risk_level="medium",
        auto_redact=True,
    )

    result = CandidateCollector().collect(
        CandidateCollectionContext(text="兴代公司", seed_candidates=[lower, higher])
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].source == "linear_bare_org_alias"
    assert result.candidates[0].confidence == 0.91


def test_collector_owns_detector_discovery() -> None:
    candidate = Candidate(
        type="location",
        text="广东省",
        start=0,
        end=3,
        source="china_admin_db",
        confidence=1.0,
        risk_level="medium",
        auto_redact=True,
    )

    class Detector:
        def detect(self, text: str) -> list[Candidate]:
            assert text == "广东省深圳市"
            return [candidate]

    result = CandidateCollector().collect(
        CandidateCollectionContext(
            text="广东省深圳市",
            detectors=(Detector(),),
        )
    )

    assert result.candidates == [candidate]


def test_resolve_candidate_overlaps_prefers_clean_nested_org_alias() -> None:
    outer = Candidate(
        type="organization",
        text="到的拓欧公司",
        start=18,
        end=24,
        source="linear_full_org",
        confidence=0.9,
        risk_level="medium",
        auto_redact=True,
    )
    inner = Candidate(
        type="organization",
        text="拓欧公司",
        start=20,
        end=24,
        source="linear_bare_org_alias",
        confidence=0.91,
        risk_level="medium",
        auto_redact=True,
    )
    resolved = resolve_candidate_overlaps([outer, inner])
    assert len(resolved) == 1
    assert resolved[0].text == "拓欧公司"




def test_engine_masks_named_factory_and_preserves_ocr_spaced_company_surface() -> None:
    text = "平山县永鸿金属制品厂与赛 城投资公司签订合同。"
    candidates = [
        Candidate(
            type="organization",
            text=value,
            start=text.index(value),
            end=text.index(value) + len(value),
            source="full_document_llm",
            confidence=0.95,
            risk_level="medium",
            auto_redact=True,
        )
        for value in ("平山县永鸿金属制品厂", "赛 城投资公司")
    ]

    mappings = {mapping.original: mapping for mapping in _discover(text, candidates=candidates)}

    assert mappings["平山县永鸿金属制品厂"].masked.endswith("厂")
    assert mappings["赛 城投资公司"].masked.endswith("公司")
    assert "城投资公司" not in mappings


def test_engine_accepts_precollected_candidates_and_calibrates_before_overlap() -> None:
    text = "办公区完成调整，某人无权代表星河公司签字。"
    noisy = Candidate(
        type="organization",
        text="某人无权代表星河公司",
        start=text.index("某人"),
        end=text.index("公司") + 2,
        source="linear_full_org",
        confidence=0.9,
        risk_level="medium",
        auto_redact=True,
    )
    competing = Candidate(
        type="person",
        text="星河公司",
        start=text.index("星河公司"),
        end=text.index("星河公司") + 4,
        source="hanlp_ner",
        confidence=0.99,
        risk_level="medium",
        auto_redact=True,
    )
    analysis = {
        "reject": ["办公区"],
        "calibrate": {"某人无权代表星河公司": "星河公司"},
    }

    # Without calibrate-before-overlap the long org span would win and drop 星河公司.
    assert [item.text for item in resolve_candidate_overlaps([noisy, competing])] == ["某人无权代表星河公司"]

    mappings = _engine().discover(text, [noisy, competing], analysis)
    by_original = {mapping.original: mapping for mapping in mappings}

    assert "某人无权代表星河公司" not in by_original
    assert "星河公司" in by_original
    assert by_original["星河公司"].type == "organization"
    assert by_original["星河公司"].source.endswith("linear_llm_calibrated")


def test_discover_only_accepts_explicit_precollected_candidates() -> None:
    text = "被告否认其与兴代公司系关联公司，兴代公司辩称双方无关联。"
    start = text.index("兴代公司")
    mappings = _discover(
        text,
        candidates=[
            Candidate(
                type="organization",
                text="兴代公司",
                start=start,
                end=start + len("兴代公司"),
                source="full_document_llm",
                confidence=0.95,
                risk_level="medium",
                auto_redact=True,
            )
        ],
    )
    originals = {mapping.original for mapping in mappings}
    assert originals == {"兴代公司"}


def test_full_document_recognition_is_required_for_new_discovery() -> None:
    from legal_redactor.pipeline import RecognitionUnavailableError

    with pytest.raises(RecognitionUnavailableError, match="全文 LLM 识别未启用"):
        RedactionPipeline(config=PipelineConfig.mapping_only()).redact("原告张三。")


def test_full_document_failure_stops_without_sentence_or_rule_fallback() -> None:
    from legal_redactor.llm import FullDocumentRegistryExtraction
    from legal_redactor.pipeline import RecognitionUnavailableError

    config = replace(
        PipelineConfig.max_effect(recognition_mode="full_document"),
        enable_hebei_admin_db=False,
        enable_china_admin_db=False,
    )
    with (
        patch(
            "legal_redactor.llm.LegalEntityAuditor.extract_full_document_registry",
            return_value=FullDocumentRegistryExtraction(status="fallback", reason="http_503"),
        ),
        patch.object(
            CandidateCollector,
            "collect",
            wraps=CandidateCollector().collect,
        ) as collect,
    ):
        with pytest.raises(RecognitionUnavailableError, match="http_503"):
            RedactionPipeline(config=config).redact("原告张三，电话13800138000。")

    assert collect.call_count == 1
    assert collect.call_args.args[0].registry_materialization is None


def test_batch_full_document_failure_returns_no_partial_result() -> None:
    from legal_redactor.entity_registry import FullDocumentEntityRegistry, RegistryEntity, RegistryValidationResult
    from legal_redactor.llm import FullDocumentRegistryExtraction
    from legal_redactor.pipeline import RecognitionUnavailableError

    success = FullDocumentRegistryExtraction(
        validation=RegistryValidationResult(
            registry=FullDocumentEntityRegistry(
                entities=(RegistryEntity("person-1", "person", "张三", ("张三",)),)
            )
        )
    )
    failure = FullDocumentRegistryExtraction(status="fallback", reason="timeout")
    config = replace(
        PipelineConfig.max_effect(),
        enable_hebei_admin_db=False,
        enable_china_admin_db=False,
    )
    with patch(
        "legal_redactor.llm.LegalEntityAuditor.extract_full_document_registry",
        side_effect=[success, failure],
    ):
        with pytest.raises(RecognitionUnavailableError, match="timeout"):
            RedactionPipeline(config=config).redact_many(
                [("a.txt", "原告张三。"), ("b.txt", "被告李四。")]
            )




def test_full_document_registry_redacts_complete_document_end_to_end() -> None:
    from legal_redactor.entity_registry import FullDocumentEntityRegistry, RegistryEntity, RegistryValidationResult
    from legal_redactor.llm import FullDocumentRegistryExtraction

    text = "河北省某人民法院民事判决书。原告张三，电话13800138000。被告星河建设有限公司。张三诉称双方签订施工合同。"
    extraction = FullDocumentRegistryExtraction(
        validation=RegistryValidationResult(
            registry=FullDocumentEntityRegistry(
                entities=(
                    RegistryEntity("person-1", "person", "张三", ("张三",)),
                    RegistryEntity(
                        "org-1",
                        "organization",
                        "星河建设有限公司",
                        ("星河建设有限公司",),
                    ),
                )
            )
        )
    )
    config = replace(
        PipelineConfig.max_effect(),
        enable_hebei_admin_db=False,
        enable_china_admin_db=False,
    )

    with patch(
        "legal_redactor.llm.LegalEntityAuditor.extract_full_document_registry",
        return_value=extraction,
    ):
        result = RedactionPipeline(config=config).redact(text, source_file="judgment.txt")

    originals = {mapping.original for mapping in result.redaction_map.mappings}
    assert {"张三", "星河建设有限公司", "电话13800138000"}.issubset(originals)
    assert "张三" not in result.redacted_text
    assert "星河建设有限公司" not in result.redacted_text
    assert "13800138000" not in result.redacted_text
    assert "施工合同" in result.redacted_text
    assert result.recognition_stats is not None
    assert result.recognition_stats.status == "success"


def test_full_document_registry_covers_entities_after_court_reasoning_boundary() -> None:
    from legal_redactor.entity_registry import FullDocumentEntityRegistry, RegistryEntity, RegistryValidationResult
    from legal_redactor.llm import FullDocumentRegistryExtraction

    text = "原告张三诉称合同无效。本院认为，被告李四应返还款项。"
    captured: list[str] = []
    extraction = FullDocumentRegistryExtraction(
        validation=RegistryValidationResult(
            registry=FullDocumentEntityRegistry(
                entities=(
                    RegistryEntity("person-1", "person", "张三", ("张三",)),
                    RegistryEntity("person-2", "person", "李四", ("李四",)),
                )
            )
        )
    )

    def extract(document_text: str, *, enable_samples: bool):
        assert enable_samples is False
        captured.append(document_text)
        return extraction

    config = replace(
        PipelineConfig.max_effect(),
        enable_hebei_admin_db=False,
        enable_china_admin_db=False,
    )
    with patch(
        "legal_redactor.llm.LegalEntityAuditor.extract_full_document_registry",
        side_effect=extract,
    ):
        result = RedactionPipeline(config=config).redact(text)

    assert captured == [text]
    assert "张三" not in result.redacted_text
    assert "李四" not in result.redacted_text


def test_false_same_entities_person_claim_keeps_opposing_parties_separate() -> None:
    from legal_redactor.entity_registry import parse_full_document_registry, validate_registry_against_text
    from legal_redactor.llm import FullDocumentRegistryExtraction

    text = "原告张三诉称合同无效。本院认为，被告李四应返还款项。"
    parsed = parse_full_document_registry(
        {
            "persons": ["张三", "李四"],
            "organizations": [],
            "locations": [],
            "same_entities": [["张三", "李四"]],
        }
    )
    validation = validate_registry_against_text(text, parsed)
    config = replace(
        PipelineConfig.max_effect(),
        enable_hebei_admin_db=False,
        enable_china_admin_db=False,
    )

    with patch(
        "legal_redactor.llm.LegalEntityAuditor.extract_full_document_registry",
        return_value=FullDocumentRegistryExtraction(validation=validation),
    ):
        result = RedactionPipeline(config=config).redact(text)

    person_mappings = {
        mapping.original: mapping
        for mapping in result.redaction_map.mappings
        if mapping.type == "person"
    }
    assert person_mappings["张三"].entity_id != person_mappings["李四"].entity_id
    assert person_mappings["张三"].masked != person_mappings["李四"].masked
    assert person_mappings["李四"].entity_id in person_mappings["张三"].do_not_merge
    assert person_mappings["张三"].entity_id in person_mappings["李四"].do_not_merge
    assert "张三" not in result.redacted_text
    assert "李四" not in result.redacted_text


def test_manager_transport_posts_logical_model_and_parses_completion(monkeypatch) -> None:
    import json

    from legal_redactor.config import LLMAPIConfig


    from legal_redactor.llm import LegalEntityAuditor

    requests: list[tuple[str, str, int, dict]] = []

    class FakeResponse:
        status = 200

        @staticmethod
        def read() -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": '{"locations":[]}'}}]}
            ).encode("utf-8")

    class FakeConnection:
        def __init__(self, host: str, port: int, *, timeout: int) -> None:
            requests.append(("connect", host, port, {"timeout": timeout}))

        def request(self, method: str, path: str, *, body: bytes, headers: dict[str, str]) -> None:
            requests.append((method, path, 0, {"body": json.loads(body), "headers": headers}))

        @staticmethod
        def getresponse() -> FakeResponse:
            return FakeResponse()

        @staticmethod
        def close() -> None:
            return None

    monkeypatch.setattr("legal_redactor.llm.http.client.HTTPConnection", FakeConnection)
    auditor = LegalEntityAuditor(
        LLMAPIConfig(model="bonsai-27b", model_manager_host="manager.example.test", model_manager_port=18080, timeout_seconds=9)
    )

    payload = auditor._call_model_manager("return JSON", max_tokens=321)
    assert payload["locations"] == []
    assert requests == [
        ("connect", "manager.example.test", 18080, {"timeout": 9}),
        (
            "POST",
            "/v1/chat/completions",
            0,
            {
                "body": {
                    "model": "bonsai-27b",
                    "messages": [{"role": "user", "content": "return JSON"}],
                    "stream": False,
                    "temperature": 0.0,
                    "max_tokens": 321,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                "headers": {"Content-Type": "application/json"},
            },
        ),
    ]





def test_mapping_sort_groups_entity_types_for_review() -> None:
    mappings = [
        MappingEntry("project", "起航小镇", "甲小镇", None, "test", 1.0, True),
        MappingEntry("organization", "云厚公司", "甲公司", None, "test", 1.0, True),
        MappingEntry("location", "石家庄市", "甲市", None, "test", 1.0, True),
        MappingEntry("person", "张三", "张某甲", None, "test", 1.0, True),
    ]

    assert [item.type for item in sort_mapping_entries(mappings)] == [
        "organization",
        "location",
        "person",
        "project",
    ]







def test_sentence_window_mode_is_rejected_before_recognition() -> None:
    with pytest.raises(ValueError, match="unsupported recognition mode"):
        PipelineConfig.balanced_llm(recognition_mode="sentence_windows")





def test_apply_mappings_skips_bare_alias_inside_unmapped_company_name() -> None:
    from legal_redactor.config import PipelineConfig
    from legal_redactor.pipeline import RedactionPipeline

    text = "华药公司认可事实，华药生物公司另行提交材料，华药继续陈述。"
    mappings = [
        MappingEntry("organization", "华药公司", "甲公司", None, "test", 1.0, True),
        MappingEntry("organization", "华药", "甲公司", None, "test", 1.0, True),
    ]

    redacted = RedactionPipeline(config=PipelineConfig.mapping_only()).apply_mappings(text, mappings)

    assert "甲公司认可事实" in redacted
    assert "华药生物公司" in redacted
    assert "甲公司生物公司" not in redacted
    assert "甲公司继续陈述" in redacted


def test_accept_organization_reuses_brand_across_different_location_prefixes() -> None:
    engine = _engine()
    engine.source_text = (
        "原告江苏载道电力工程有限公司，后更名为淮安载道电力工程有限公司。"
        "载道公司亦参与诉讼。"
    )
    names = [
        "江苏载道电力工程有限公司",
        "淮安载道电力工程有限公司",
        "载道公司",
        "载道电力工程有限公司",
    ]
    for name in names:
        engine.accept_organization(
            Candidate(
                type="organization",
                text=name,
                start=engine.source_text.index(name),
                end=engine.source_text.index(name) + len(name),
                source="linear_llm_exact",
                confidence=0.95,
                risk_level="medium",
                auto_redact=True,
            )
        )

    by_original = {mapping.original: mapping.masked for mapping in engine.mappings}
    assert by_original["江苏载道电力工程有限公司"] == "甲电力工程公司"
    assert by_original["淮安载道电力工程有限公司"] == "甲电力工程公司"
    assert by_original["载道公司"] == "甲公司"


def test_accept_organization_reuses_brand_mask_for_short_and_full_names() -> None:
    engine = _engine()
    engine.source_text = (
        "河北云厚建筑装饰工程有限公司（以下简称云厚公司）与"
        "河北兴代建筑安装工程有限公司（以下简称兴代公司）及"
        "石家庄方卫信息系统技术有限公司（以下简称方卫公司）签订合同。"
    )
    names = [
        "云厚公司",
        "兴代公司",
        "方卫公司",
        "河北云厚建筑装饰工程有限公司",
        "河北兴代建筑安装工程有限公司",
        "石家庄方卫信息系统技术有限公司",
    ]
    for name in names:
        engine.accept_organization(
            Candidate(
                type="organization",
                text=name,
                start=engine.source_text.index(name),
                end=engine.source_text.index(name) + len(name),
                source="linear_llm_exact",
                confidence=0.95,
                risk_level="medium",
                auto_redact=True,
            )
        )

    by_original = {mapping.original: mapping.masked for mapping in engine.mappings}
    assert by_original["云厚公司"] == "甲公司"
    assert by_original["兴代公司"] == "乙公司"
    assert by_original["方卫公司"] == "丙公司"
    assert by_original["河北云厚建筑装饰工程有限公司"] == "甲装饰工程公司"
    assert by_original["河北兴代建筑安装工程有限公司"] == "乙公司"
    assert by_original["石家庄方卫信息系统技术有限公司"] == "丙公司"


def test_accept_organization_keeps_different_company_short_names_separate() -> None:
    engine = _engine()
    engine.source_text = (
        "河北星河建设有限公司与北京星河科技有限公司签订合同。"
        "星河建设公司提交说明，星河科技公司提交说明。"
    )
    for name in (
        "河北星河建设有限公司",
        "北京星河科技有限公司",
        "星河建设公司",
        "星河科技公司",
    ):
        engine.accept_organization(
            Candidate(
                type="organization",
                text=name,
                start=engine.source_text.index(name),
                end=engine.source_text.index(name) + len(name),
                source="linear_llm_exact",
                confidence=0.95,
                risk_level="medium",
                auto_redact=True,
            )
        )

    by_original = {mapping.original: mapping.masked for mapping in engine.mappings}
    assert by_original["星河建设公司"] != by_original["星河科技公司"]
    assert by_original["星河建设公司"] == "甲公司"
    assert by_original["星河科技公司"] == "乙公司"


def test_merge_organization_alias_mappings_keeps_different_company_short_names_separate() -> None:
    from legal_redactor.postprocess import _merge_organization_alias_mappings

    mappings = [
        MappingEntry("organization", "河北星河建设有限公司", "甲省甲公司", None, "linear:linear_llm_exact", 0.95, True),
        MappingEntry("organization", "星河建设公司", "甲公司", None, "linear:linear_llm_exact", 0.95, True),
        MappingEntry("organization", "北京星河科技有限公司", "乙省乙科技公司", None, "linear:linear_llm_exact", 0.95, True),
        MappingEntry("organization", "星河科技公司", "乙公司", None, "linear:linear_llm_exact", 0.95, True),
    ]

    merged = _merge_organization_alias_mappings(mappings)
    by_original = {mapping.original: mapping.masked for mapping in merged}

    assert by_original["星河建设公司"] == "甲公司"
    assert by_original["星河科技公司"] == "乙公司"
    assert by_original["星河建设公司"] != by_original["星河科技公司"]
