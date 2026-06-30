from __future__ import annotations

from dataclasses import dataclass

from legal_redactor.counters import TypeCounters
from legal_redactor.candidate_resolution import resolve_candidate_overlaps
from legal_redactor.linear_engine import LinearRuleEngine
from legal_redactor.org_masking import (
    derived_organization_alias_cores,
    explicit_organization_aliases,
    has_explicit_bare_brand_alias,
)
from legal_redactor.location_utils import get_location_core, location_suffix, strip_leading_locations
from legal_redactor.models import Candidate


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
    assert "河北" in originals


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


def test_append_exact_candidate_skips_ambiguous_global_find_when_window_misses() -> None:
    text = "甲公司提交说明。乙公司到庭。"
    candidates: list[Candidate] = []
    LinearRuleEngine._append_exact_candidate(
        candidates,
        text,
        "乙公司",
        "organization",
        {"window": "s2"},
        {
            "s2": {"start": 0, "end": 6},
        },
    )
    assert candidates == []


def test_append_exact_candidate_uses_single_occurrence_fallback_when_window_misses() -> None:
    text = "原告江苏路达电力工程有限公司，后更名为淮安载道电力工程有限公司。张三住河北省石家庄市长安区。"
    candidates: list[Candidate] = []
    LinearRuleEngine._append_exact_candidate(
        candidates,
        text,
        "张三",
        "person",
        {"window": "s1"},
        {"s1": {"start": 0, "end": 32}},
    )
    assert len(candidates) == 1
    assert candidates[0].text == "张三"
    assert candidates[0].start == text.index("张三")


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


def test_discover_respects_sample_blacklist_for_rules() -> None:
    engine = _engine(sample_blacklist={"办公区"})
    text = "办公区完成调整，河北星河建筑工程有限公司签订合同。"
    mappings = engine.discover(text)
    originals = {mapping.original for mapping in mappings}
    assert "办公区" not in originals
    assert "河北星河建筑工程有限公司" in originals