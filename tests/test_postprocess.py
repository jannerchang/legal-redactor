"""Unit tests for the postprocess mapping pipeline.

These exercise the public apply_postprocess entry and its PostprocessConfig
flags, pinning the fixed step order and the path-specific toggles
(include_fragments / include_alias_merge / protected_texts) that pipeline
previously inlined as different call sequences.
"""

from legal_redactor.models import MappingEntry
from legal_redactor.postprocess import (
    PostprocessConfig,
    _filter_fragments_inside_longer_entities,
    _filter_locations_inside_organizations,
    _filter_mappings_inside_trusted_samples,
    _filter_noise_entity_mappings,
    _filter_org_alias_prefixed_locations,
    _merge_organization_alias_mappings,
    apply_postprocess,
)


def _mappings() -> list[MappingEntry]:
    return [
        MappingEntry(type="organization", original="深圳市声旺公司", masked="甲公司", role=None, source="sample_library:lib", confidence=1.0, restore_by_default=True),
        MappingEntry(type="location", original="深圳市", masked="甲市", role=None, source="linear_rule", confidence=0.9, restore_by_default=True),
        MappingEntry(type="organization", original="合同一", masked="乙合同", role=None, source="linear_llm_exact", confidence=1.0, restore_by_default=True),
        MappingEntry(type="person", original="声旺", masked="丙", role=None, source="linear_rule", confidence=0.8, restore_by_default=True),
    ]


def _manual_chain(text, mappings, cfg):
    m = _filter_mappings_inside_trusted_samples(text, mappings)
    m = _filter_locations_inside_organizations(text, m, cfg.protected_texts)
    m = _filter_org_alias_prefixed_locations(m)
    if cfg.include_fragments:
        m = _filter_fragments_inside_longer_entities(text, m)
    m = _filter_noise_entity_mappings(m)
    if cfg.include_alias_merge:
        m = _merge_organization_alias_mappings(m)
    return m


def test_apply_postprocess_matches_manual_chain_for_each_path_config():
    text = "深圳市声旺公司位于深圳市，合同一为证。"
    protected = {"深圳市声旺"}
    configs = [
        PostprocessConfig(include_fragments=True, include_alias_merge=False, protected_texts=protected),
        PostprocessConfig(include_fragments=False, include_alias_merge=False, protected_texts=protected),
        PostprocessConfig(include_fragments=True, include_alias_merge=True, protected_texts=None),
    ]
    for cfg in configs:
        assert apply_postprocess(text, _mappings(), cfg) == _manual_chain(text, _mappings(), cfg)


def test_apply_postprocess_empty_mappings_is_identity():
    text = "任意文本"
    for cfg in [
        PostprocessConfig(),
        PostprocessConfig(include_fragments=True, include_alias_merge=True),
    ]:
        assert apply_postprocess(text, [], cfg) == []


def test_postprocess_does_not_merge_registry_entities_marked_do_not_merge():
    text = "星河建设有限公司与星河科技有限公司并非同一主体。"
    mappings = [
        MappingEntry(
            type="organization",
            original="星河建设有限公司",
            masked="甲公司",
            role=None,
            source="linear:full_document_llm",
            confidence=0.9,
            restore_by_default=True,
            entity_id="org-1",
            do_not_merge=("org-2",),
        ),
        MappingEntry(
            type="organization",
            original="星河科技有限公司",
            masked="乙公司",
            role=None,
            source="linear:full_document_llm",
            confidence=0.9,
            restore_by_default=True,
            entity_id="org-2",
            do_not_merge=("org-1",),
        ),
    ]

    processed = apply_postprocess(
        text,
        mappings,
        PostprocessConfig(include_alias_merge=True),
    )

    assert [mapping.masked for mapping in processed] == ["甲公司", "乙公司"]