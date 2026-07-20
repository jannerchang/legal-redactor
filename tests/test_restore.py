from legal_redactor.models import MappingEntry, RedactionMap
from legal_redactor.restore import preview_restore, restore_text


def _entry(original: str, masked: str, restore_by_default: bool) -> MappingEntry:
    return MappingEntry(
        type="test",
        original=original,
        masked=masked,
        role=None,
        source="test",
        confidence=1.0,
        restore_by_default=restore_by_default,
    )


def test_restore_always_restores_every_mapping_entry() -> None:
    redaction_map = RedactionMap.create(
        mappings=[
            _entry("原姓名", "甲某", True),
            _entry("原编号", "编号甲", False),
        ]
    )

    assert restore_text("甲某，编号甲", redaction_map) == "原姓名，原编号"
    assert restore_text("甲某，编号甲", redaction_map, restore_all=False) == "原姓名，原编号"


def test_restore_preview_never_skips_entries() -> None:
    redaction_map = RedactionMap.create(
        mappings=[_entry("原编号", "编号甲", False)]
    )

    preview = preview_restore("编号甲", redaction_map, restore_all=False)

    assert preview.restored_text == "原编号"
    assert preview.restored_entries == redaction_map.mappings
    assert preview.skipped_entries == []


def test_restore_shared_entity_mask_prefers_canonical_full_name() -> None:
    redaction_map = RedactionMap.create(
        mappings=[
            MappingEntry(
                type="organization",
                original="星河建设有限公司",
                masked="甲公司",
                role=None,
                source="full_document_llm",
                confidence=0.9,
                restore_by_default=True,
                entity_id="org-1",
                restore_original="星河建设有限公司",
            ),
            MappingEntry(
                type="organization",
                original="星河公司",
                masked="甲公司",
                role=None,
                source="full_document_llm",
                confidence=0.9,
                restore_by_default=True,
                entity_id="org-1",
                restore_original="星河建设有限公司",
            ),
        ]
    )

    assert restore_text("被告甲公司提交答辩。", redaction_map) == "被告星河建设有限公司提交答辩。"


def test_restore_legacy_duplicate_mask_keeps_previous_last_entry_behavior() -> None:
    redaction_map = RedactionMap.create(
        mappings=[
            _entry("较长原文", "同一代称", True),
            _entry("短原文", "同一代称", True),
        ]
    )

    assert restore_text("同一代称", redaction_map) == "短原文"
