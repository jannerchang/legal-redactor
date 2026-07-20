"""测试数据模型序列化/反序列化。"""


from legal_redactor.models import MappingEntry, RedactionMap, Candidate, Leak


def test_mapping_entry_roundtrip():
    entry = MappingEntry(
        type="person",
        original="张三",
        masked="自然人甲",
        role="原告",
        source="party_section",
        confidence=0.95,
        restore_by_default=True,
        reason="人工确认是原告姓名",
        entity_id="person-1",
        do_not_merge=("person-2",),
        restore_original="张三",
    )
    d = entry.to_dict()
    restored = MappingEntry.from_dict(d)
    assert restored.type == "person"
    assert restored.original == "张三"
    assert restored.masked == "自然人甲"
    assert restored.confidence == 0.95
    assert restored.reason == "人工确认是原告姓名"
    assert restored.entity_id == "person-1"
    assert restored.do_not_merge == ("person-2",)
    assert restored.restore_original == "张三"


def test_redaction_map_roundtrip():
    rm = RedactionMap.create(
        mappings=[
            MappingEntry(
                type="person",
                original="张三",
                masked="自然人甲",
                role="原告",
                source="party_section",
                confidence=1.0,
                restore_by_default=True,
            ),
        ],
        mode="normal",
        source_file="test.txt",
    )
    d = rm.to_dict()
    restored = RedactionMap.from_dict(d)
    assert restored.version == "1.0"
    assert restored.mode == "normal"
    assert restored.source_file == "test.txt"
    assert len(restored.mappings) == 1
    assert restored.mappings[0].original == "张三"


def test_mapping_entry_from_legacy_dict_without_reason():
    restored = MappingEntry.from_dict(
        {
            "type": "person",
            "original": "张三",
            "masked": "自然人甲",
            "role": None,
            "source": "legacy",
            "confidence": 1.0,
            "restore_by_default": True,
        }
    )
    assert restored.reason is None
    assert restored.entity_id is None
    assert restored.do_not_merge == ()
    assert restored.restore_original is None


def test_redaction_map_sorts_mappings_by_entity_group():
    rm = RedactionMap.create(
        mappings=[
            MappingEntry(
                type="person",
                original="张三",
                masked="张某甲",
                role=None,
                source="test",
                confidence=1.0,
                restore_by_default=True,
            ),
            MappingEntry(
                type="location",
                original="河北省",
                masked="甲省",
                role=None,
                source="test",
                confidence=1.0,
                restore_by_default=True,
            ),
            MappingEntry(
                type="organization",
                original="河北豪木山建筑工程有限公司",
                masked="甲公司",
                role=None,
                source="test",
                confidence=1.0,
                restore_by_default=True,
            ),
            MappingEntry(
                type="phone",
                original="13800000000",
                masked="***",
                role=None,
                source="test",
                confidence=1.0,
                restore_by_default=False,
            ),
        ]
    )

    assert [entry.type for entry in rm.mappings] == [
        "organization",
        "location",
        "person",
        "phone",
    ]


def test_redaction_map_sorts_same_type_by_original_length():
    rm = RedactionMap.create(
        mappings=[
            MappingEntry(
                type="organization",
                original="拓欧公司",
                masked="丁省丁公司",
                role=None,
                source="test",
                confidence=1.0,
                restore_by_default=True,
            ),
            MappingEntry(
                type="organization",
                original="安徽拓欧建设集团有限公司",
                masked="丁省丁公司",
                role=None,
                source="test",
                confidence=1.0,
                restore_by_default=True,
            ),
            MappingEntry(
                type="organization",
                original="大唐公司",
                masked="丙新能源公司",
                role=None,
                source="test",
                confidence=1.0,
                restore_by_default=True,
            ),
            MappingEntry(
                type="organization",
                original="大唐来安新能源有限公司",
                masked="丙新能源公司",
                role=None,
                source="test",
                confidence=1.0,
                restore_by_default=True,
            ),
        ]
    )

    assert [entry.original for entry in rm.mappings] == [
        "安徽拓欧建设集团有限公司",
        "大唐来安新能源有限公司",
        "大唐公司",
        "拓欧公司",
    ]


def test_candidate_to_dict():
    c = Candidate(
        type="id_number",
        text="330106198501012345",
        start=0,
        end=18,
        source="regex",
        confidence=1.0,
        risk_level="high",
        auto_redact=True,
    )
    d = c.to_dict()
    assert d["type"] == "id_number"
    assert d["text"] == "330106198501012345"
    assert d["confidence"] == 1.0


def test_leak_to_dict():
    leak = Leak(
        type="phone",
        text="13800000000",
        start=100,
        end=111,
        source="regex",
        risk_level="high",
    )
    d = leak.to_dict()
    assert d["type"] == "phone"
    assert d["text"] == "13800000000"
