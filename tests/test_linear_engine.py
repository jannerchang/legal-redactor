from __future__ import annotations

from dataclasses import dataclass

from legal_redactor.counters import TypeCounters
from legal_redactor.candidate_collector import (
    CandidateCollectionContext,
    CandidateCollector,
    candidate_needs_llm_review,
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


def _collect(
    text: str,
    *,
    sample_blacklist: set[str] | None = None,
    seed_candidates: list[Candidate] | None = None,
    llm_analysis: dict | None = None,
    llm_primary_discovery: bool = False,
    use_semantic_rules: bool = True,
    use_china_admin_rules: bool = True,
) -> list[Candidate]:
    result = CandidateCollector().collect(
        CandidateCollectionContext(
            text=text,
            seed_candidates=list(seed_candidates or ()),
            llm_analysis=llm_analysis or {},
            llm_primary_discovery=llm_primary_discovery,
            use_semantic_rules=use_semantic_rules,
            use_china_admin_rules=use_china_admin_rules,
        )
    )
    return result.candidates


def _discover(
    text: str,
    *,
    sample_blacklist: set[str] | None = None,
    seed_candidates: list[Candidate] | None = None,
    llm_analysis: dict | None = None,
    llm_primary_discovery: bool = False,
    use_semantic_rules: bool = True,
    use_china_admin_rules: bool = True,
) -> list[MappingEntry]:
    candidates = _collect(
        text,
        sample_blacklist=sample_blacklist,
        seed_candidates=seed_candidates,
        llm_analysis=llm_analysis,
        llm_primary_discovery=llm_primary_discovery,
        use_semantic_rules=use_semantic_rules,
        use_china_admin_rules=use_china_admin_rules,
    )
    return _engine(sample_blacklist=sample_blacklist).discover(
        text,
        candidates,
        llm_analysis,
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


def test_llm_company_variants_trim_narrative_prefix_and_unbalanced_parenthesis():
    from legal_redactor.llm import _company_variant_texts

    assert _company_variant_texts("所属融创集团") == ["融创集团"]
    assert _company_variant_texts(
        "中建二局下游机电安装专业分包单位（河北文凯建筑工程有限公司"
    ) == ["河北文凯建筑工程有限公司"]


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


def test_collect_skips_ambiguous_global_find_when_window_misses() -> None:
    text = "甲公司提交说明。乙公司到庭。"
    result = CandidateCollector().collect(
        CandidateCollectionContext(
            text=text,
            llm_analysis={
                "_sentence_windows": [{"id": "s2", "start": 0, "end": 6}],
                "companies": [{"window": "s2", "name": "乙公司"}],
            },
            llm_primary_discovery=True,
        )
    )

    assert result.candidates == []


def test_collect_uses_single_occurrence_fallback_when_window_misses() -> None:
    text = "原告江苏路达电力工程有限公司，后更名为淮安载道电力工程有限公司。张三住河北省石家庄市长安区。"
    result = CandidateCollector().collect(
        CandidateCollectionContext(
            text=text,
            llm_analysis={
                "_sentence_windows": [{"id": "s1", "start": 0, "end": 32}],
                "persons": [{"window": "s1", "name": "张三"}],
            },
            llm_primary_discovery=True,
        )
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].text == "张三"
    assert result.candidates[0].start == text.index("张三")
    assert result.candidates[0].source == "linear_llm_exact"


def test_collect_rewrites_local_spans_to_document_coordinates() -> None:
    from unittest.mock import patch

    local = [
        Candidate(
            type="person",
            text="张三",
            start=0,
            end=2,
            source="party_section",
            confidence=0.95,
            risk_level="low",
            auto_redact=True,
        )
    ]
    text = "前言。原告张三提交证据。"

    with patch(
        "legal_redactor.candidate_collector.detect_party_candidates",
        side_effect=[([], []), (local, [])],
    ):
        result = CandidateCollector().collect(
            CandidateCollectionContext(
                text=text,
                use_semantic_rules=False,
                use_china_admin_rules=False,
            )
        )

    party_candidate = next(
        candidate for candidate in result.candidates if candidate.source == "party_section"
    )
    assert party_candidate.text == "张三"
    assert party_candidate.start == text.index("原告")
    assert party_candidate.end == text.index("原告") + len("张三")


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
        CandidateCollectionContext(
            text="兴代公司",
            seed_candidates=[lower, higher],
            llm_primary_discovery=True,
        )
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].source == "linear_bare_org_alias"
    assert result.candidates[0].confidence == 0.91


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


def test_llm_primary_discovery_emits_audit_only_linear_llm_exact_without_rule_candidates() -> None:
    text = "被告否认其与兴代公司系关联公司，兴代公司辩称无关联。"
    analysis = {
        "companies": [{"window": "s1", "name": "兴代公司", "variants": ["兴代公司"]}],
        "persons": [],
        "locations": [],
        "projects": [],
        "reject": ["否认其与兴代公司系关联公司"],
        "calibrate": {},
        "_sentence_windows": [
            {
                "id": "s1",
                "previous": "",
                "target": "被告否认其与兴代公司系关联公司。",
                "next": "",
            }
        ],
    }

    empty_primary = _collect(text, llm_analysis={}, llm_primary_discovery=True)
    assert empty_primary == []

    candidates = _collect(text, llm_analysis=analysis, llm_primary_discovery=True)
    assert candidates
    assert {candidate.source for candidate in candidates} == {"linear_llm_exact"}
    assert {candidate.text for candidate in candidates} == {"兴代公司"}
    assert not any(candidate.source.startswith(("party", "linear_full_org", "linear_bare")) for candidate in candidates)

    mappings = _engine().discover(text, candidates, analysis)
    originals = {mapping.original for mapping in mappings}
    assert "兴代公司" in originals
    assert "否认其与兴代公司系关联公司" not in originals
    assert any(mapping.source.endswith("linear_llm_exact") for mapping in mappings if mapping.original == "兴代公司")


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


def test_discover_rejects_false_org_clause_with_embedded_company() -> None:
    text = "被告否认其与兴代公司系关联公司，兴代公司辩称双方无关联。"
    mappings = _discover(text)
    originals = {mapping.original for mapping in mappings}
    assert "否认其与兴代公司系关联公司" not in originals
    assert "兴代公司" in originals


def test_discover_respects_sample_blacklist_for_rules() -> None:
    text = "办公区完成调整，河北星河建筑工程有限公司签订合同。"
    mappings = _discover(text, sample_blacklist={"办公区"})
    originals = {mapping.original for mapping in mappings}
    assert "办公区" not in originals
    assert "河北星河建筑工程有限公司" in originals


def test_sentence_windows_keep_commas_inside_sentence() -> None:
    from legal_redactor.llm import build_sentence_windows

    windows = build_sentence_windows("原告张三、李四，被告王五。")

    assert len(windows) == 1
    assert windows[0]["target"] == "原告张三、李四，被告王五。"


def test_sentence_windows_keep_one_sentence_per_target() -> None:
    from legal_redactor.llm import build_sentence_windows

    windows = build_sentence_windows("原告张三提交证据。被告李四发表意见！第三人王五未到庭？")

    assert [item["target"] for item in windows] == [
        "原告张三提交证据。",
        "被告李四发表意见！",
        "第三人王五未到庭？",
    ]
    assert windows[1]["previous"] == "原告张三提交证据。"
    assert windows[1]["next"] == "第三人王五未到庭？"


def test_sentence_selection_defaults_to_mode_target_cap() -> None:
    from legal_redactor.llm import (
        _MAX_EFFECT_TARGET_WINDOWS,
        build_sentence_windows,
        select_entity_target_windows,
    )

    text = "".join(f"第{i}句原告张三提交证据。" for i in range(1, 51))
    windows = build_sentence_windows(text)
    selected = select_entity_target_windows(windows)

    assert len(windows) == 50
    assert len(selected) == _MAX_EFFECT_TARGET_WINDOWS == 48
    assert selected[0]["id"] == "s1"
    assert selected[-1]["id"] == "s48"


def test_sentence_selection_respects_explicit_max_windows_override() -> None:
    from legal_redactor.llm import build_sentence_windows, select_entity_target_windows

    text = "".join(f"第{i}句原告张三提交证据。" for i in range(1, 51))
    windows = build_sentence_windows(text)

    selected_all = select_entity_target_windows(windows, max_windows=50)
    selected_ten = select_entity_target_windows(windows, max_windows=10)
    selected_balanced = select_entity_target_windows(windows, mode="balanced")

    assert len(selected_all) == 50
    assert selected_all[0]["id"] == "s1"
    assert selected_all[-1]["id"] == "s50"
    assert len(selected_ten) == 10
    assert len(selected_balanced) == 24


def test_max_effect_large_document_stays_within_six_batches() -> None:
    from legal_redactor.llm import (
        _sentence_extraction_batches,
        build_sentence_windows,
        select_entity_target_windows,
    )

    # Mirrors the live Web failure shape: hundreds of scored sentences must not
    # expand into tens of sequential MLX batches under default max-effect.
    text = "".join(f"第{i}句原告张三提交证据。" for i in range(1, 316))
    windows = build_sentence_windows(text)
    selected = select_entity_target_windows(windows, mode="max-effect")
    batches = _sentence_extraction_batches(selected, mode="max-effect")

    assert len(windows) == 315
    assert len(selected) == 48
    assert len(batches) == 6

def test_extract_sentence_entities_max_effect_dispatches_six_batches() -> None:
    from legal_redactor.config import LLMAPIConfig
    from legal_redactor.llm import LegalEntityAuditor

    auditor = LegalEntityAuditor(LLMAPIConfig(mode="max-effect"))
    text = "".join(f"第{i}句原告张三提交证据。" for i in range(1, 316))
    calls: list[str] = []

    def fake_call(prompt, *, max_tokens):
        calls.append(prompt)
        return {
            "locations": [],
            "companies": [],
            "persons": [],
            "projects": [],
            "reject": [],
            "calibrate": {},
        }

    auditor._call_model_manager = fake_call  # type: ignore[method-assign]

    result = auditor.extract_sentence_entities(text, enable_samples=False)

    assert result["_target_sentence_count"] == 48
    assert result["_batch_count"] == 6
    assert len(calls) == 6



def test_offline_llm_mode_uses_rules() -> None:
    config = PipelineConfig.from_llm_mode("off")

    assert config.enable_llm is False
    assert config.llm.enabled is False

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
                },
                "headers": {"Content-Type": "application/json"},
            },
        ),
    ]



def test_sentence_extraction_partial_batch_failure_keeps_successful_batches() -> None:
    from legal_redactor.config import LLMAPIConfig
    from legal_redactor.llm import LegalEntityAuditor

    auditor = LegalEntityAuditor(LLMAPIConfig(mode="max-effect"))
    text = "".join(f"第{i}句原告张三提交证据。" for i in range(1, 22))
    calls: list[str] = []

    def fake_extract_windows_batch(batch, *, enable_samples, label):
        calls.append(label)
        if label.startswith("batch 2/"):
            return None, [f"{label}: simulated failure"]
        return {
            "locations": [],
            "companies": [],
            "persons": [{"window": batch[0]["id"], "name": "张三"}],
            "projects": [],
            "reject": [],
            "calibrate": {},
        }, []

    auditor._extract_windows_batch = fake_extract_windows_batch  # type: ignore[method-assign]

    result = auditor.extract_sentence_entities(text, enable_samples=False)

    assert "error" not in result
    assert result["_batch_failures"] == ["batch 2/3: simulated failure"]
    assert [item["name"] for item in result["persons"]] == ["张三"]
    assert sorted(calls) == ["batch 1/3", "batch 2/3", "batch 3/3"]


def test_sentence_batch_records_one_failure_after_retry() -> None:
    from legal_redactor.config import LLMAPIConfig
    from legal_redactor.llm import LegalEntityAuditor

    auditor = LegalEntityAuditor(LLMAPIConfig(mode="max-effect"))

    def fail_call(prompt, *, max_tokens):
        raise RuntimeError("bad json")

    auditor._call_model_manager = fail_call  # type: ignore[method-assign]
    payload, failures = auditor._extract_windows_batch(
        [{"id": "s1", "previous": "", "target": "原告张三。", "next": ""}],
        enable_samples=False,
        label="batch 1/1",
    )

    assert payload is None
    assert failures == ["batch 1/1: bad json"]


def test_parse_json_recovers_max_tokens_truncated_payload() -> None:
    from legal_redactor.config import LLMAPIConfig
    from legal_redactor.llm import LegalEntityAuditor

    auditor = LegalEntityAuditor(LLMAPIConfig(mode="max-effect"))
    # Model hit max_tokens mid-string after already emitting complete entities.
    truncated = (
        '{"locations":[{"window":"s1","full":"北京市海淀区"}],'
        '"companies":[{"window":"s2","name":"石家庄裕华精密铸造有限公司"},'
        '{"window":"s3","name":"裕华公'
    )

    payload = auditor._parse_json(truncated)

    assert "error" not in payload
    assert payload["locations"] == [{"window": "s1", "full": "北京市海淀区"}]
    assert payload["companies"][0]["name"] == "石家庄裕华精密铸造有限公司"
    # The trailing clipped entity is discarded; partial legal names must not
    # enter the mapping table as valid entities.
    assert len(payload["companies"]) == 1
    assert payload["persons"] == []
    assert payload["projects"] == []


def test_parse_json_unrecoverable_error_is_shape_only_without_source_text() -> None:
    from legal_redactor.config import LLMAPIConfig
    from legal_redactor.llm import LegalEntityAuditor

    auditor = LegalEntityAuditor(LLMAPIConfig(mode="max-effect"))
    secret = "原告张三诉石家庄裕华精密铸造有限公司一案"

    # Truncated before any complete key/value can be salvaged.
    truncated_payload = auditor._parse_json('{"locations":[{"window":')
    invalid_payload = auditor._parse_json(f"not-json-at-all::{secret}")

    assert truncated_payload["error"] == "JSON decode failed (truncated)"
    assert invalid_payload["error"] == "JSON decode failed (invalid)"
    for payload in (truncated_payload, invalid_payload):
        blob = str(payload)
        assert secret not in blob
        assert "张三" not in blob
        assert "裕华" not in blob
        assert "locations" in payload
        assert payload["locations"] == []


def test_extract_windows_batch_keeps_recoverable_truncated_json() -> None:
    from legal_redactor.config import LLMAPIConfig
    from legal_redactor.llm import LegalEntityAuditor

    auditor = LegalEntityAuditor(LLMAPIConfig(mode="max-effect"))
    calls: list[int] = []

    def fake_call(prompt, *, max_tokens):
        calls.append(max_tokens)
        # Simulate a single max_tokens-truncated completion that repair can salvage.
        return auditor._parse_json(
            '{"locations":[],"companies":[],"persons":[{"window":"s1","name":"张三"}],'
            '"projects":[{"window":"s1","name":"示例项'
        )

    auditor._call_model_manager = fake_call  # type: ignore[method-assign]
    payload, failures = auditor._extract_windows_batch(
        [{"id": "s1", "previous": "", "target": "原告张三参与示例项目。", "next": ""}],
        enable_samples=False,
        label="batch 1/1",
    )

    assert failures == []
    assert payload is not None
    assert payload["persons"] == [{"window": "s1", "name": "张三"}]
    assert payload["projects"] == []
    assert len(calls) == 1


def test_extract_windows_batch_skips_unrecoverable_with_safe_diagnostic() -> None:
    from legal_redactor.config import LLMAPIConfig
    from legal_redactor.llm import LegalEntityAuditor

    auditor = LegalEntityAuditor(LLMAPIConfig(mode="max-effect"))
    secret = "文书原文不得出现在错误信息"
    token_budgets: list[int] = []

    def fake_call(prompt, *, max_tokens):
        token_budgets.append(max_tokens)
        # Unrecoverable truncation: open object/array with no complete value.
        return auditor._parse_json('{"locations":[{"window":')

    auditor._call_model_manager = fake_call  # type: ignore[method-assign]
    payload, failures = auditor._extract_windows_batch(
        [{"id": "s1", "previous": "", "target": secret + "。", "next": ""}],
        enable_samples=False,
        label="batch 2/3",
    )

    assert payload is None
    assert len(failures) == 1
    assert failures[0].startswith("batch 2/3: JSON decode failed (truncated)")
    assert secret not in failures[0]
    assert "不得出现" not in failures[0]
    # Truncation retries raise the token ceiling without expanding concurrency.
    assert len(token_budgets) == 3
    assert token_budgets[0] < token_budgets[-1]


def test_sentence_orchestration_keeps_company_names_from_llm_clause_output() -> None:
    from legal_redactor.llm import orchestrate_sentence_extractions

    sentence = (
        "石家庄裕华精密铸造有限公司（原名称：鹿泉市裕华精密铸造有限公司），"
        "后有简称为：裕华公司。"
    )
    analysis = {
        "locations": [],
        "companies": [
            {
                "window": "s1",
                "name": (
                    "石家庄裕华精密铸造有限公司（原名称：鹿泉市裕华精密铸造有限公司），"
                    "后有简称为：裕华公司"
                ),
            }
        ],
        "persons": [],
        "projects": [],
        "reject": [],
        "calibrate": {},
    }

    result = orchestrate_sentence_extractions(analysis, source_text=sentence)

    variants = set(result["companies"][0]["variants"])
    assert "石家庄裕华精密铸造有限公司" in variants
    assert "鹿泉市裕华精密铸造有限公司" in variants
    assert "裕华公司" in variants

def test_sentence_orchestration_strips_litigation_role_company_prefix() -> None:
    from legal_redactor.llm import orchestrate_sentence_extractions

    result = orchestrate_sentence_extractions(
        {
            "locations": [],
            "companies": [
                {
                    "window": "s1",
                    "name": "被告河北星河建设有限公司",
                    "variants": ["被告河北星河建设有限公司", "星河建设公司"],
                }
            ],
            "persons": [],
            "projects": [],
            "reject": [],
            "calibrate": {},
        }
    )

    assert result["companies"] == [
        {
            "window": "s1",
            "name": "河北星河建设有限公司",
            "variants": ["河北星河建设有限公司", "星河建设公司"],
        }
    ]


def test_sentence_orchestration_drops_action_clause_organization_noise() -> None:
    from legal_redactor.llm import orchestrate_sentence_extractions

    result = orchestrate_sentence_extractions(
        {
            "locations": [],
            "companies": [
                {"window": "s1", "name": "王琳向冯朋嵩发送河北银行", "variants": ["王琳向冯朋嵩发送河北银行"]},
                {"window": "s2", "name": "否认冯朋嵩系兴代公司", "variants": ["否认冯朋嵩系兴代公司"]},
                {"window": "s3", "name": "称冯朋嵩以兴代公司", "variants": ["称冯朋嵩以兴代公司"]},
                {"window": "s4", "name": "云厚公司", "variants": ["云厚公司"]},
            ],
            "persons": [],
            "projects": [],
            "reject": [],
            "calibrate": {},
        }
    )

    company_names = {item["name"] for item in result["companies"]}
    assert "云厚公司" in company_names
    assert "河北银行" in company_names
    assert "兴代公司" in company_names
    assert "王琳向冯朋嵩发送河北银行" not in company_names
    assert "否认冯朋嵩系兴代公司" not in company_names
    assert "称冯朋嵩以兴代公司" not in company_names


def test_sentence_orchestration_drops_generic_project_noise() -> None:
    from legal_redactor.llm import orchestrate_sentence_extractions

    result = orchestrate_sentence_extractions(
        {
            "locations": [],
            "companies": [],
            "persons": [],
            "projects": [
                {"window": "s1", "name": "办公大厅整体装修施工"},
                {"window": "s2", "name": "会议室装修承包合同"},
                {"window": "s3", "name": "二期空调采购清单"},
                {"window": "s4", "name": "合同总款"},
                {"window": "s5", "name": "整体工程"},
                {"window": "s6", "name": "报价单"},
                {"window": "s7", "name": "起航小镇"},
            ],
            "reject": [],
            "calibrate": {},
        }
    )

    assert result["projects"] == [{"window": "s7", "name": "起航小镇"}]


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



def test_offline_person_placeholders_follow_document_order_not_name_length() -> None:
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())

    result = pipeline.redact("原告张三，被告张小明。")

    person_masks = {
        mapping.original: mapping.masked
        for mapping in result.redaction_map.mappings
        if mapping.type == "person"
    }

    assert person_masks["张三"] == "张某甲"
    assert person_masks["张小明"] == "张某乙"
    assert "原告张某甲，被告张某乙。" in result.redacted_text


def test_discover_detects_inline_party_person_lists() -> None:
    text = (
        "原告华北制药股份有限公司诉被告张三、李四，"
        "第三人赵仁川、王利杰、王兴国、张熠焯、崔松豪、余湘北合同纠纷一案。"
    )

    mappings = _discover(text)

    originals = {mapping.original for mapping in mappings}
    assert {"张三", "李四", "赵仁川", "王利杰", "王兴国", "张熠焯", "崔松豪", "余湘北"} <= originals


def test_discover_maps_explicit_bare_company_alias_as_organization() -> None:
    text = "华北制药股份有限公司（以下简称华药）与中技公司签订合同。华药公司提交说明，华药确认事实。"

    mappings = _discover(text)

    by_original = {mapping.original: mapping for mapping in mappings}
    assert by_original["华药"].type == "organization"
    assert by_original["华药"].masked.endswith("公司")
    assert by_original["华药公司"].masked == by_original["华药"].masked


def test_pipeline_review_candidates_are_deduped_by_type_text_and_capped() -> None:
    from unittest.mock import patch

    from legal_redactor.candidate_collector import CandidateCollectionResult

    duplicates_and_overflow = [
        Candidate(
            type="organization",
            text=f"某某科技有限公司{index}",
            start=0,
            end=10,
            source="linear_full_org",
            confidence=0.9,
            risk_level="medium",
            auto_redact=True,
        )
        for index in range(90)
    ]
    # Same (type, text) as the first entry must not create a second review slot.
    duplicates_and_overflow.append(
        Candidate(
            type="organization",
            text="某某科技有限公司0",
            start=20,
            end=30,
            source="linear_full_org",
            confidence=0.95,
            risk_level="medium",
            auto_redact=True,
        )
    )

    def fake_collect(self, context: CandidateCollectionContext) -> CandidateCollectionResult:
        if not context.llm_primary_discovery and not context.llm_analysis:
            return CandidateCollectionResult(candidates=duplicates_and_overflow)
        return CandidateCollectionResult(candidates=[])

    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    with patch.object(CandidateCollector, "collect", fake_collect):
        result = pipeline.redact("任意文本。")

    assert len(result.review_candidates) == 80
    assert len({(candidate.type, candidate.text) for candidate in result.review_candidates}) == 80
    assert result.review_candidates[0].text == "某某科技有限公司0"
    assert result.review_candidates[-1].text == "某某科技有限公司79"
    assert all(candidate_needs_llm_review(candidate) for candidate in result.review_candidates)


def test_pipeline_collects_rule_detectors_once_before_optional_llm_review() -> None:
    from unittest.mock import patch

    import legal_redactor.candidate_collector as collector_module

    with (
        patch.object(
            collector_module,
            "detect_title_candidates",
            wraps=collector_module.detect_title_candidates,
        ) as title_spy,
        patch.object(
            collector_module,
            "detect_china_admin_rule_candidates",
            wraps=collector_module.detect_china_admin_rule_candidates,
        ) as china_admin_spy,
    ):
        result = RedactionPipeline(config=PipelineConfig.offline_without_llm()).redact(
            "原告华北制药股份有限公司提交证据。"
        )

    assert title_spy.call_count == 1
    assert china_admin_spy.call_count == 1
    assert any(mapping.original == "华北制药股份有限公司" for mapping in result.redaction_map.mappings)


def test_fail_closed_sentence_extraction_skips_collector_and_engine() -> None:
    from dataclasses import replace
    from unittest.mock import patch

    config = replace(
        PipelineConfig.balanced_llm(recognition_mode="sentence_windows"),
        enable_hebei_admin_db=False,
        enable_china_admin_db=False,
    )

    with (
        patch(
            "legal_redactor.llm.LegalEntityAuditor.extract_sentence_entities",
            return_value={"error": "simulated extraction failure"},
        ),
        patch.object(
            CandidateCollector,
            "collect",
            side_effect=AssertionError("collector must not run after fail-closed extraction"),
        ),
        patch.object(
            LinearRuleEngine,
            "discover",
            side_effect=AssertionError("engine must not run after fail-closed extraction"),
        ),
    ):
        result = RedactionPipeline(config=config).redact("原告张三，电话13800138000。")

    assert "13800138000" not in result.redacted_text
    assert any(mapping.type == "phone" for mapping in result.redaction_map.mappings)
    assert result.review_candidates == []
    assert result.warnings == [
        "整句 LLM 识别失败，已仅保留固定结构化正则脱敏：simulated extraction failure"
    ]


def test_apply_mappings_does_not_replace_bare_alias_inside_different_company() -> None:
    text = (
        "华北制药股份有限公司（以下简称华药）提交说明。"
        "华药公司认可事实，华药生物公司另行提交材料，华药研发公司另行提交材料，华药继续陈述。"
    )
    mappings = _discover(text)
    by_original = {mapping.original: mapping for mapping in mappings}

    redacted = RedactionPipeline(config=PipelineConfig.offline_without_llm()).apply_mappings(text, mappings)

    assert by_original["华药公司"].masked == by_original["华药"].masked
    assert by_original["华药生物公司"].masked != by_original["华药"].masked
    assert by_original["华药研发公司"].masked != by_original["华药"].masked
    assert "华药公司" not in redacted
    assert "华药生物公司" not in redacted
    assert "华药研发公司" not in redacted
    assert "公司生物公司" not in redacted
    assert "公司研发公司" not in redacted
    assert "华药继续陈述" not in redacted



def test_apply_mappings_skips_bare_alias_inside_unmapped_company_name() -> None:
    from legal_redactor.config import PipelineConfig
    from legal_redactor.pipeline import RedactionPipeline

    text = "华药公司认可事实，华药生物公司另行提交材料，华药继续陈述。"
    mappings = [
        MappingEntry("organization", "华药公司", "甲公司", None, "test", 1.0, True),
        MappingEntry("organization", "华药", "甲公司", None, "test", 1.0, True),
    ]

    redacted = RedactionPipeline(config=PipelineConfig.offline_without_llm()).apply_mappings(text, mappings)

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
