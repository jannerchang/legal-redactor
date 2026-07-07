"""Tests for the detector registry: adapter transparency and discover_all.

These pin that each adapter forwards to its underlying detect_* function
unchanged, so the registry is a safe extension point. The registry is not
yet wired into LinearRuleEngine.collect_candidates (see detector_registry
module docstring); these tests cover the adapter layer in isolation.
"""

from legal_redactor.china_admin_rules import detect_china_admin_rule_candidates
from legal_redactor.detector_registry import (
    DetectorRegistry,
    FunctionDetector,
    PartyLineDetector,
    build_default_registry,
)
from legal_redactor.detectors import (
    detect_fallback_person_candidates,
    detect_inline_party_person_list_candidates,
    detect_party_candidates,
    detect_title_candidates,
)

SAMPLE = "原告张三，被告李四。北京市朝阳区某工程施工。合同一约定由甲科技有限公司承建。"


def test_function_adapter_is_transparent():
    pairs = [
        FunctionDetector("title", detect_title_candidates),
        FunctionDetector("inline_party_person_list", detect_inline_party_person_list_candidates),
        FunctionDetector("fallback_person", detect_fallback_person_candidates),
        FunctionDetector("china_admin_rule", detect_china_admin_rule_candidates),
    ]
    for detector in pairs:
        assert detector.discover(SAMPLE) == detector.discover_fn(SAMPLE)


def test_party_adapter_drops_party_lines_and_keeps_candidates():
    detector = PartyLineDetector("party", detect_party_candidates)
    candidates, party_lines = detect_party_candidates(SAMPLE)
    assert detector.discover(SAMPLE) == candidates
    # the adapter must not surface the party_lines tuple element
    assert all(not isinstance(c, list) for c in detector.discover(SAMPLE))


def test_build_default_registry_orders_adapters():
    registry = build_default_registry()
    assert [d.name for d in registry.detectors] == [
        "title",
        "inline_party_person_list",
        "fallback_person",
        "china_admin_rule",
        "party",
    ]


def test_discover_all_concatenates_in_registration_order():
    registry = build_default_registry()
    expected = (
        detect_title_candidates(SAMPLE)
        + detect_inline_party_person_list_candidates(SAMPLE)
        + detect_fallback_person_candidates(SAMPLE)
        + detect_china_admin_rule_candidates(SAMPLE)
        + detect_party_candidates(SAMPLE)[0]
    )
    assert registry.discover_all(SAMPLE) == expected


def test_empty_registry_discovers_nothing():
    assert DetectorRegistry().discover_all(SAMPLE) == []