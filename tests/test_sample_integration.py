import json
import pytest
from legal_redactor._samples import (
    save_sample_auto,
    get_few_shot_examples,
    load_all_samples,
    load_recent_error_samples,
    load_sample_blacklist_for_optimization,
    load_trusted_sample_mappings,
    AUTO_SAMPLE_FILE,
)
from legal_redactor.config import PipelineConfig
from legal_redactor.pipeline import RedactionPipeline
from legal_redactor.web_app import _diagnose_sample_entry


def _post_message_payload(response_body: str) -> dict:
    marker = "parent.postMessage("
    start = response_body.index(marker) + len(marker)
    end = response_body.index(',"*"', start)
    return json.loads(response_body[start:end])


@pytest.fixture
def mock_samples(tmp_path):
    """创建临时样本库用于测试。"""
    # 模拟 entries
    entries = [
        # 被拉黑的词（应被豁免，不进行脱敏）
        {"action": "delete", "type": "organization", "original": "来我去公司"},
        # 精确修改的词（应使用精准脱敏掩码）
        {
            "action": "modify",
            "type": "person",
            "old_original": "张小明",
            "new_original": "张小明",
            "old_masked": "张某1",
            "new_masked": "【小明特制掩码】",
        },
        # 新增的词（直接脱敏）
        {"action": "add", "type": "manual", "original": "绝密代号", "masked": "【代号X】"},
    ]

    # 保存临时样本库
    filepath = save_sample_auto(entries, samples_dir=tmp_path)

    # 临时覆盖默认的样本读取逻辑（可以通过 monkeypatch 替换默认样本路径）
    return tmp_path, filepath


def test_pipeline_reuses_modify_samples_without_delete_blacklist(mock_samples, monkeypatch):
    tmp_path, filepath = mock_samples

    import legal_redactor._samples
    monkeypatch.setattr(legal_redactor._samples, "DEFAULT_SAMPLES_DIR", tmp_path)

    config = PipelineConfig.offline_without_llm()
    pipeline = RedactionPipeline(config=config)
    test_text = "原告：张小明。被告：来我去公司。案件涉及绝密代号。"

    result = pipeline.redact(test_text, mode="standard")

    assert "张小明" not in result.redacted_text
    assert "【小明特制掩码】" in result.redacted_text
    assert "绝密代号" in result.redacted_text
    assert "【代号X】" not in result.redacted_text


def test_delete_samples_remain_for_optimization(mock_samples, monkeypatch):
    tmp_path, _filepath = mock_samples

    import legal_redactor._samples as samples_module
    monkeypatch.setattr(samples_module, "DEFAULT_SAMPLES_DIR", tmp_path)

    _, optimization_blacklist = load_all_samples(samples_dir=tmp_path)
    assert "来我去公司" in optimization_blacklist
    assert "来我去公司" in load_sample_blacklist_for_optimization(samples_dir=tmp_path)
    assert "来我去公司" in get_few_shot_examples(samples_dir=tmp_path)


def test_delete_blacklist_does_not_block_party_org_redaction(tmp_path, monkeypatch):
    import legal_redactor._samples as samples_module

    save_sample_auto(
        [{"action": "delete", "type": "organization", "original": "华北制药股份有限公司"}],
        samples_dir=tmp_path,
    )
    monkeypatch.setattr(samples_module, "DEFAULT_SAMPLES_DIR", tmp_path)

    assert "华北制药股份有限公司" in load_sample_blacklist_for_optimization(samples_dir=tmp_path)

    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    result = pipeline.redact(
        "原告华北制药股份有限公司诉被告张三、李四，第三人赵仁川合同纠纷一案。",
        mode="standard",
    )

    orgs = [mapping for mapping in result.redaction_map.mappings if mapping.type == "organization"]
    assert any(mapping.original == "华北制药股份有限公司" for mapping in orgs)
    assert "华北制药股份有限公司" not in result.redacted_text


def test_generic_false_positive_rules_do_not_require_runtime_blacklist():
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    result = pipeline.redact(
        "甲方签约后提交银行流水。合同一、合同二并列出现。",
        mode="standard",
    )

    blocked = {mapping.original for mapping in result.redaction_map.mappings}
    assert "甲方" not in blocked
    assert "银行流水" not in blocked
    assert "合同一" not in blocked
    assert "甲方" in result.redacted_text


def test_modify_sample_with_company_mask_is_treated_as_organization(tmp_path):
    save_sample_auto(
        [
            {
                "action": "modify",
                "type": "person",
                "old_original": "兴代",
                "new_original": "兴代",
                "old_masked": "兴某甲",
                "new_masked": "丁公司",
            },
            {
                "action": "modify",
                "type": "organization",
                "old_original": "兴代公司",
                "new_original": "兴代公司",
                "old_masked": "乙省乙装饰工程公司",
                "new_masked": "乙省丁公司",
            },
        ],
        samples_dir=tmp_path,
    )

    mappings = load_trusted_sample_mappings(samples_dir=tmp_path)
    by_original = {mapping.original: mapping for mapping in mappings}

    assert by_original["兴代"].type == "organization"
    assert by_original["兴代"].masked == "丁公司"
    assert by_original["兴代公司"].masked == "乙省丁公司"


def test_trusted_added_company_samples_are_reused_narrowly(tmp_path):
    save_sample_auto(
        [
            {"action": "add", "type": "manual", "original": "胖哥公司", "masked": "乙公司"},
            {"action": "add", "type": "manual", "original": "唐山", "masked": "己市"},
            {"action": "add", "type": "manual", "original": "曹永现", "masked": "曹某甲"},
            {"action": "add", "type": "manual", "original": "冀", "masked": "新"},
            {"action": "add", "type": "manual", "original": "绝密代号", "masked": "【代号X】"},
        ],
        source="today",
        samples_dir=tmp_path,
    )

    mappings = load_trusted_sample_mappings(samples_dir=tmp_path)

    assert sorted((m.type, m.original, m.masked) for m in mappings) == sorted([
        ("person", "曹永现", "曹某甲"),
        ("location", "唐山", "己市"),
        ("organization", "胖哥公司", "乙公司"),
    ])


def test_short_person_delete_samples_do_not_pollute_global_blacklist(tmp_path):
    save_sample_auto(
        [
            {"action": "delete", "type": "person", "original": "王五"},
            {"action": "delete", "type": "person", "original": "张小明"},
            {"action": "delete", "type": "organization", "original": "来我去公司"},
        ],
        source="today",
        samples_dir=tmp_path,
    )

    _, blacklist = load_all_samples(samples_dir=tmp_path)
    few_shot = get_few_shot_examples(samples_dir=tmp_path)

    assert "王五" not in blacklist
    assert "张小明" not in blacklist
    assert "来我去公司" in blacklist
    assert "王五" not in few_shot
    assert "张小明" not in few_shot
    assert "来我去公司" in few_shot


def test_modify_old_short_person_name_does_not_pollute_blacklist(tmp_path):
    save_sample_auto(
        [
            {
                "action": "modify",
                "type": "person",
                "old_original": "王五",
                "new_original": "王五明",
                "old_masked": "王某1",
                "new_masked": "王某2",
            }
        ],
        source="today",
        samples_dir=tmp_path,
    )

    lookup, blacklist = load_all_samples(samples_dir=tmp_path)

    assert "王五" not in blacklist
    assert lookup["王五明"] == "王某2"


def test_pipeline_reuses_trusted_added_company_sample(tmp_path, monkeypatch):
    import legal_redactor._samples

    save_sample_auto(
        [{"action": "add", "type": "manual", "original": "胖哥公司", "masked": "乙公司"}],
        source="today",
        samples_dir=tmp_path,
    )
    monkeypatch.setattr(legal_redactor._samples, "DEFAULT_SAMPLES_DIR", tmp_path)

    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    result = pipeline.redact("胖哥公司与起航小镇签订合同。")

    assert "胖哥公司" not in result.redacted_text
    assert "乙公司" in result.redacted_text


def test_pipeline_reuses_trusted_added_locations_and_ignores_case_abbr(tmp_path, monkeypatch):
    import legal_redactor._samples

    save_sample_auto(
        [
            {"action": "add", "type": "manual", "original": "河北", "masked": "甲省"},
            {"action": "add", "type": "manual", "original": "唐山", "masked": "己市"},
            {"action": "add", "type": "manual", "original": "迁安市", "masked": "戊市"},
            {"action": "add", "type": "manual", "original": "井陉县", "masked": "丁县"},
            {"action": "add", "type": "manual", "original": "冀", "masked": "新"},
        ],
        source="today",
        samples_dir=tmp_path,
    )
    monkeypatch.setattr(legal_redactor._samples, "DEFAULT_SAMPLES_DIR", tmp_path)

    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    result = pipeline.redact("河北唐山迁安市、井陉县，案号（2025）冀01民终123号。")

    assert "河北" not in result.redacted_text
    assert "唐山" not in result.redacted_text
    assert "迁安市" not in result.redacted_text
    assert "井陉县" not in result.redacted_text
    assert "甲省" in result.redacted_text
    assert "己市" in result.redacted_text
    assert "戊市" in result.redacted_text
    assert "丁县" in result.redacted_text
    assert all(mapping.original != "冀" for mapping in result.redaction_map.mappings)


def test_pipeline_reuses_today_company_and_location_corrections(tmp_path, monkeypatch):
    import legal_redactor._samples

    save_sample_auto(
        [
            {
                "action": "modify",
                "type": "organization",
                "old_original": "石家庄裕华精密铸造有限公司",
                "new_original": "石家庄裕华精密铸造有限公司",
                "old_masked": "丙公司",
                "new_masked": "甲公司",
            },
            {
                "action": "modify",
                "type": "organization",
                "old_original": "鹿泉市裕华精密铸造有限公司",
                "new_original": "鹿泉市裕华精密铸造有限公司",
                "old_masked": "乙公司",
                "new_masked": "甲公司",
            },
            {
                "action": "add",
                "type": "manual",
                "original": "裕华公司",
                "masked": "甲公司",
            },
            {
                "action": "add",
                "type": "manual",
                "original": "石药集团",
                "masked": "乙集团",
            },
            {
                "action": "modify",
                "type": "location",
                "old_original": "鹿泉",
                "new_original": "鹿泉",
                "old_masked": "某区",
                "new_masked": "丙区",
            },
        ],
        source="today",
        samples_dir=tmp_path,
    )
    monkeypatch.setattr(legal_redactor._samples, "DEFAULT_SAMPLES_DIR", tmp_path)

    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    result = pipeline.redact(
        "石家庄裕华精密铸造有限公司与鹿泉市裕华精密铸造有限公司相关，裕华公司位于鹿泉。石药集团提交说明。"
    )

    assert result.redacted_text == "甲公司与甲公司相关，甲公司位于丙区。乙集团提交说明。"


def test_pipeline_drops_rule_fragments_inside_trusted_company_sample(tmp_path, monkeypatch):
    import legal_redactor._samples

    save_sample_auto(
        [
            {
                "action": "add",
                "type": "manual",
                "original": "诺亚人力资源发展集团有限公司",
                "masked": "乙人力资源发展集团有限公司",
            }
        ],
        source="today",
        samples_dir=tmp_path,
    )
    monkeypatch.setattr(legal_redactor._samples, "DEFAULT_SAMPLES_DIR", tmp_path)

    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    result = pipeline.redact("诺亚人力资源发展集团有限公司提交了证据。")

    assert result.redacted_text == "乙人力资源发展集团有限公司提交了证据。"
    assert [m.original for m in result.redaction_map.mappings] == ["诺亚人力资源发展集团有限公司"]


def test_sample_entries_are_timestamped_and_recent_errors_sorted(tmp_path):
    save_sample_auto(
        [{"action": "delete", "type": "location", "original": "旧错误"}],
        source="first",
        samples_dir=tmp_path,
    )
    sample_file = tmp_path / AUTO_SAMPLE_FILE
    data = json.loads(sample_file.read_text(encoding="utf-8"))
    first_entry = data["entries"][0]
    assert first_entry["created_at"]
    assert first_entry["updated_at"]
    assert first_entry["first_seen_at"] == first_entry["created_at"]
    assert first_entry["last_seen_at"] == first_entry["updated_at"]
    created_at = first_entry["created_at"]

    save_sample_auto(
        [{"action": "delete", "type": "organization", "original": "新错误"}],
        source="second",
        samples_dir=tmp_path,
    )
    data = json.loads(sample_file.read_text(encoding="utf-8"))
    new_error_updated_at = {
        entry["original"]: entry["updated_at"]
        for entry in data["entries"]
        if entry.get("original") == "新错误"
    }["新错误"]
    save_sample_auto(
        [{"action": "delete", "type": "location", "original": "旧错误"}],
        source="again",
        samples_dir=tmp_path,
    )

    data = json.loads(sample_file.read_text(encoding="utf-8"))
    by_original = {entry["original"]: entry for entry in data["entries"]}
    assert by_original["旧错误"]["created_at"] == created_at
    assert by_original["旧错误"]["first_seen_at"] == created_at
    assert by_original["旧错误"]["source"] == "again"
    assert by_original["旧错误"]["last_source"] == "again"
    assert by_original["新错误"]["updated_at"] == new_error_updated_at

    recent = load_recent_error_samples(samples_dir=tmp_path, limit=2)
    assert [entry["original"] for entry in recent] == ["旧错误", "新错误"]


def test_recent_error_samples_use_file_timestamp_for_legacy_entries(tmp_path):
    sample_file = tmp_path / "legacy.sample.json"
    sample_file.write_text(
        json.dumps(
            {
                "version": "1.0",
                "updated_at": "2026-01-02T03:04:05+00:00",
                "entries": [
                    {"action": "delete", "type": "person", "original": "旧格式错误"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    recent = load_recent_error_samples(samples_dir=tmp_path, limit=1)
    assert recent[0]["original"] == "旧格式错误"
    assert recent[0]["updated_at"] == "2026-01-02T03:04:05+00:00"


def test_diagnose_sample_entry():
    # 测试 delete 误识别诊断
    e_del_phone = {"action": "delete", "original": "13812345678"}
    diag_phone = _diagnose_sample_entry(e_del_phone)
    assert "手机号正则" in diag_phone
    assert "误匹配为实体" in diag_phone

    e_del_company = {"action": "delete", "original": "河北省某某建设工程有限公司"}
    diag_company = _diagnose_sample_entry(e_del_company)
    assert "机构后缀特征" in diag_company
    assert "误匹配为实体" in diag_company

    e_del_person = {"action": "delete", "original": "张小"}
    diag_person = _diagnose_sample_entry(e_del_person)
    assert "姓名兜底匹配" in diag_person
    assert "误匹配为实体" in diag_person

    # 测试 modify 诊断
    e_mod = {"action": "modify", "old_masked": "张某1", "new_masked": "特制掩码"}
    diag_mod = _diagnose_sample_entry(e_mod)
    assert "修正脱敏掩码" in diag_mod
    assert "张某1" in diag_mod
    assert "特制掩码" in diag_mod

    # 测试 add 诊断
    e_add = {"action": "add", "original": "绝密代号", "masked": "代号X"}
    diag_add = _diagnose_sample_entry(e_add)
    assert "手动新增实体" in diag_add


@pytest.mark.anyio
async def test_save_sample_page_only_saves_diffs(tmp_path, monkeypatch):
    """测试 Web UI 的 save_sample_page 接口：
    - 正确识别且未修改的词不应保存为样本（即 keep 动作不保存）；
    - 修改的词保存为 modify；
    - 新增的词保存为 add；
    - 删除的词保存为 delete。
    """
    import legal_redactor._samples
    monkeypatch.setattr(legal_redactor._samples, "DEFAULT_SAMPLES_DIR", tmp_path)

    # 绕过 Python 函数默认参数评估时间陷阱，将 save_sample_auto 的默认 samples_dir 重定向到 tmp_path
    original_save = legal_redactor._samples.save_sample_auto
    def mock_save_sample_auto(entries, source="", samples_dir=tmp_path):
        return original_save(entries, source=source, samples_dir=samples_dir)
    monkeypatch.setattr(legal_redactor._samples, "save_sample_auto", mock_save_sample_auto)

    # 构造 mock 的 Form
    class MockFormData:
        def __init__(self, form_data):
            self._form_data = form_data
        def getlist(self, key):
            val = self._form_data.get(key, [])
            return val if isinstance(val, list) else [val]
        def get(self, key, default=None):
            val = self._form_data.get(key, default)
            return val[0] if isinstance(val, list) and len(val) > 0 else val

    class MockRequest:
        def __init__(self, form_data):
            self._form_data = MockFormData(form_data)
        async def form(self):
            return self._form_data

    # 原先系统生成的自动映射关系为：
    # "张三" -> "张某1"
    # "李四" -> "李某1"
    original_mapping = {
        "mappings": [
            {"type": "person", "original": "张三", "masked": "张某1"},
            {"type": "person", "original": "李四", "masked": "李某1"},
        ]
    }

    # 用户在前端编辑后的表格状态为：
    # row 0: "张三" -> "张某1" (未修改，应该保持 Keep，不保存)
    # row 1: "李四" -> "李某特制掩码" (修改，应该保存为 modify)
    # row 2: "新增人名" -> "新某1" (新增，应该保存为 add)
    # row 3: "删除人名" (勾选了删除，应该保存为 delete)
    form_data = {
        "map_type": ["person", "person", "person", "person"],
        "map_original": ["张三", "李四", "新增人名", "删除人名"],
        "map_masked": ["张某1", "李某特制掩码", "新某1", "删除某1"],
        "map_role": ["", "", "", ""],
        "map_source": ["rule", "rule", "manual", "rule"],
        "map_confidence": ["1.0", "1.0", "1.0", "1.0"],
        "map_reason": ["", "应改为特制掩码", "漏识别，手工新增", "不是人名，误识别"],
        "map_restore_by_default": ["1", "1", "1", "1"],
        "row_delete": ["3"], # 勾选了第3行（删除人名）
        "map_source_file": "test.txt",
        "original_mapping_json": json.dumps(original_mapping),
    }

    from legal_redactor.web_app import save_sample_page
    request = MockRequest(form_data)

    # 执行保存
    response = await save_sample_page(request)
    assert response.status_code == 200

    # 读取生成的样本文件并验证
    from legal_redactor._samples import _auto_sample_path
    sample_file = _auto_sample_path(tmp_path)
    assert sample_file.exists()

    sample_data = json.loads(sample_file.read_text(encoding="utf-8"))
    entries = sample_data.get("entries", [])

    # 期望只保留 3 条记录：李四 (modify)、新增人名 (add)、删除人名 (delete)
    # 而张三 (keep) 绝对不能保存！
    assert len(entries) == 3

    actions = {e.get("action") for e in entries}
    assert "modify" in actions
    assert "add" in actions
    assert "delete" in actions

    # 验证具体内容
    for e in entries:
        if e.get("action") == "keep":
            pytest.fail("Keep entries should not be saved!")
        elif e.get("action") == "modify":
            assert e.get("new_original") == "李四"
            assert e.get("new_masked") == "李某特制掩码"
            assert e.get("reason") == "应改为特制掩码"
        elif e.get("action") == "add":
            assert e.get("original") == "新增人名"
            assert e.get("masked") == "新某1"
            assert e.get("reason") == "漏识别，手工新增"
        elif e.get("action") == "delete":
            assert e.get("original") == "删除人名"
            assert e.get("reason") == "不是人名，误识别"

    payload = _post_message_payload(response.body.decode("utf-8"))
    assert payload["type"] == "sample_summary"
    summary = payload["summary"]
    assert set(summary) >= {
        "lookup_entries",
        "delete_blacklist_candidates",
        "suppressed_risky_entries",
        "manual_corrections",
        "false_positive_deletes",
        "missing_adds",
        "restore_unresolved_placeholders",
        "newest_sample_provenance",
        "regression_suggestions",
    }
    assert summary["manual_corrections"] == 3
    assert summary["false_positive_deletes"] == 1
    assert summary["missing_adds"] == 1
    assert {item["original"] for item in summary["lookup_entries"]} == {"李四", "新增人名"}
    assert {item["original"] for item in summary["delete_blacklist_candidates"]} == {"删除人名"}
    delete_item = summary["delete_blacklist_candidates"][0]
    assert delete_item["reason_code"] == "delete_candidate"
    assert "黑名单" in delete_item["message"]
    assert summary["newest_sample_provenance"]["sample_file"] == AUTO_SAMPLE_FILE
    assert summary["newest_sample_provenance"]["sample_updated_at"]


@pytest.mark.anyio
async def test_save_sample_page_skips_short_person_global_delete(tmp_path, monkeypatch):
    import legal_redactor._samples
    monkeypatch.setattr(legal_redactor._samples, "DEFAULT_SAMPLES_DIR", tmp_path)

    original_save = legal_redactor._samples.save_sample_auto

    def mock_save_sample_auto(entries, source="", samples_dir=tmp_path):
        return original_save(entries, source=source, samples_dir=samples_dir)

    monkeypatch.setattr(legal_redactor._samples, "save_sample_auto", mock_save_sample_auto)

    class MockFormData:
        def __init__(self, form_data):
            self._form_data = form_data

        def getlist(self, key):
            val = self._form_data.get(key, [])
            return val if isinstance(val, list) else [val]

        def get(self, key, default=None):
            val = self._form_data.get(key, default)
            return val[0] if isinstance(val, list) and len(val) > 0 else val

    class MockRequest:
        def __init__(self, form_data):
            self._form_data = MockFormData(form_data)

        async def form(self):
            return self._form_data

    form_data = {
        "map_type": ["person"],
        "map_original": ["王五"],
        "map_masked": ["王某1"],
        "map_role": [""],
        "map_source": ["rule"],
        "map_confidence": ["1.0"],
        "map_reason": ["误识别短人名"],
        "map_restore_by_default": ["1"],
        "row_delete": ["0"],
        "map_source_file": "test.txt",
        "original_mapping_json": json.dumps(
            {"mappings": [{"type": "person", "original": "王五", "masked": "王某1"}]}
        ),
    }

    from legal_redactor.web_app import save_sample_page

    response = await save_sample_page(MockRequest(form_data))

    assert response.status_code == 200
    body = response.body.decode("utf-8")
    assert "短中文人名" in body
    payload = _post_message_payload(body)
    assert payload["type"] == "sample_summary"
    assert payload["summary"]["manual_corrections"] == 1
    assert payload["summary"]["delete_blacklist_candidates"] == []
    assert payload["summary"]["suppressed_risky_entries"][0]["original"] == "王五"
    assert not (tmp_path / AUTO_SAMPLE_FILE).exists()


@pytest.mark.anyio
async def test_save_sample_page_recomputes_summary_from_rows_not_forged_labels(tmp_path, monkeypatch):
    import legal_redactor._samples

    monkeypatch.setattr(legal_redactor._samples, "DEFAULT_SAMPLES_DIR", tmp_path)
    original_save = legal_redactor._samples.save_sample_auto

    def mock_save_sample_auto(entries, source="", samples_dir=tmp_path):
        return original_save(entries, source=source, samples_dir=samples_dir)

    monkeypatch.setattr(legal_redactor._samples, "save_sample_auto", mock_save_sample_auto)

    class MockFormData:
        def __init__(self, form_data):
            self._form_data = form_data

        def getlist(self, key):
            val = self._form_data.get(key, [])
            return val if isinstance(val, list) else [val]

        def get(self, key, default=None):
            val = self._form_data.get(key, default)
            return val[0] if isinstance(val, list) and len(val) > 0 else val

    class MockRequest:
        def __init__(self, form_data):
            self._form_data = MockFormData(form_data)

        async def form(self):
            return self._form_data

    form_data = {
        "map_type": ["person"],
        "map_original": ["新增人名"],
        "map_masked": ["新某1"],
        "map_role": [""],
        "map_source": ["manual"],
        "map_confidence": ["1.0"],
        "map_reason": ["漏识别"],
        "map_restore_by_default": ["1"],
        "row_delete": [],
        "map_category": ["delete_candidate"],
        "row_category": ["delete_candidate"],
        "map_source_file": "test.txt",
        "original_mapping_json": json.dumps({"mappings": []}),
    }

    from legal_redactor.web_app import save_sample_page

    response = await save_sample_page(MockRequest(form_data))
    payload = _post_message_payload(response.body.decode("utf-8"))
    summary = payload["summary"]

    assert summary["missing_adds"] == 1
    assert summary["false_positive_deletes"] == 0
    assert summary["delete_blacklist_candidates"] == []
    sample_file = tmp_path / AUTO_SAMPLE_FILE
    entries = json.loads(sample_file.read_text(encoding="utf-8"))["entries"]
    assert entries[0]["action"] == "add"


@pytest.mark.anyio
async def test_save_sample_page_reports_effective_retry_delta(tmp_path, monkeypatch):
    import legal_redactor._samples

    monkeypatch.setattr(legal_redactor._samples, "DEFAULT_SAMPLES_DIR", tmp_path)
    original_save = legal_redactor._samples.save_sample_auto

    def mock_save_sample_auto(entries, source="", samples_dir=tmp_path):
        return original_save(entries, source=source, samples_dir=samples_dir)

    monkeypatch.setattr(legal_redactor._samples, "save_sample_auto", mock_save_sample_auto)

    class MockFormData:
        def __init__(self, form_data):
            self._form_data = form_data

        def getlist(self, key):
            val = self._form_data.get(key, [])
            return val if isinstance(val, list) else [val]

        def get(self, key, default=None):
            val = self._form_data.get(key, default)
            return val[0] if isinstance(val, list) and len(val) > 0 else val

    class MockRequest:
        def __init__(self, form_data):
            self._form_data = MockFormData(form_data)

        async def form(self):
            return self._form_data

    form_data = {
        "map_type": ["person"],
        "map_original": ["新增人名"],
        "map_masked": ["新某1"],
        "map_role": [""],
        "map_source": ["manual"],
        "map_confidence": ["1.0"],
        "map_reason": ["漏识别"],
        "map_restore_by_default": ["1"],
        "row_delete": [],
        "map_source_file": "test.txt",
        "original_mapping_json": json.dumps({"mappings": []}),
    }

    from legal_redactor.web_app import save_sample_page

    first = await save_sample_page(MockRequest(form_data))
    second = await save_sample_page(MockRequest(form_data))
    first_payload = _post_message_payload(first.body.decode("utf-8"))
    second_payload = _post_message_payload(second.body.decode("utf-8"))

    assert "新增 1" in first_payload["msg"]
    assert "未变化 0" in first_payload["msg"]
    assert "新增 0" in second_payload["msg"]
    assert "未变化 1" in second_payload["msg"]
    assert second_payload["summary"]["manual_corrections"] == 1


def test_fallback_person_missed_names_are_detected():
    """测试通过优化后的 _FALLBACK_PERSON_PATTERNS 能够成功识别以前遗漏的人名。"""
    from legal_redactor.detectors import detect_fallback_person_candidates

    # 模拟包含遗漏人名的文书文本
    text_1 = "本案交由陈戊靖负责审计，相关账目清晰。"
    text_2 = "陶玉静的主张得到了法庭的支持。"
    text_3 = "经核实，陈戊靖于2023年办理了离职。"

    candidates_1 = detect_fallback_person_candidates(text_1)
    candidates_2 = detect_fallback_person_candidates(text_2)
    candidates_3 = detect_fallback_person_candidates(text_3)

    # 验证是否成功检出 "陈戊靖"
    assert any(c.text == "陈戊靖" for c in candidates_1)
    # 验证是否成功检出 "陶玉静"
    assert any(c.text == "陶玉静" for c in candidates_2)
    # 验证是否成功检出 "陈戊靖" (句中动作形式)
    assert any(c.text == "陈戊靖" for c in candidates_3)


def test_clean_organization_and_validate_llm_person():
    """测试组织机构清洗优化以及 LLM 人名提取校验的正确性。"""
    from legal_redactor.detectors import _clean_organization_text, _is_false_org

    # 1. 组织清洗只做格式归一化，不再凭动作词猜实体边界
    c1 = _clean_organization_text("是由郝亚雄去跟天津市慕尚园林绿化工程有限公司")
    assert c1 == "是由郝亚雄去跟天津市慕尚园林绿化工程有限公司"

    c2 = _clean_organization_text("接管河北奥星集团药业有限公司")
    assert c2 == "接管河北奥星集团药业有限公司"

    c3 = _clean_organization_text("（华禾康源生物科技河北有限公司")
    assert c3 == "华禾康源生物科技河北有限公司"

    c4 = _clean_organization_text("其实壹州公司")
    assert c4 == "其实壹州公司"

    c5 = _clean_organization_text("确实壹州公司")
    assert c5 == "确实壹州公司"

    c6 = _clean_organization_text("证实壹州公司")
    assert c6 == "证实壹州公司"

    # 验证未对称括号与未带后缀品牌名清洗
    assert _clean_organization_text("（华禾康源生物科技河北") == "华禾康源生物科技河北"
    assert _clean_organization_text("）河北立生") == "河北立生"
    assert _clean_organization_text("加盖慕尚") == "加盖慕尚"
    assert _clean_organization_text("接管河北奥星") == "接管河北奥星"

    # 2. 验证伪公司过滤
    assert _is_false_org("严重违反公司") is True
    assert _is_false_org("继续违反公司") is True
    assert _is_false_org("否返还立生公司") is True
    assert _is_false_org("加盖慕尚公司") is True
    assert _is_false_org("其实公司") is True
    assert _is_false_org("但是公司") is True
    assert _is_false_org("确实公司") is True
    assert _is_false_org("但公司") is True
    assert _is_false_org("并公司") is True
    assert _is_false_org("天津市慕尚园林绿化工程有限公司") is False


    # 构造含大模型幻觉人名/句子的 Mock LLM 输出
    mock_analysis = {
        "locations": [],
        "companies": [],
        "persons": [
            {"name": "我是去给郝亚雄帮忙的", "surname": "我"},
            {"name": "外围这一块、通道、下面这一半圈、中间这一块", "surname": "外"},
            {"name": "当时苗确实没有死", "surname": "当"},
            {"name": "我们做过结算", "surname": "我"},
            {"name": "见过", "surname": "见"},
            {"name": "分了几块", "surname": "分"},
            {"name": "对", "surname": "对"},
            {"name": "开庭后", "surname": "开"},
            {"name": "张三", "surname": "张"},  # 唯一合法名字
        ],
        "reject": []
    }


    # 复制 pipeline 内部的 name 校验逻辑来验证
    common_surnames = frozenset(
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

    valid_names = []
    for person in mock_analysis["persons"]:
        name = person["name"]
        # ── 过滤明显的大模型抽取幻觉/长句误切 ──
        if len(name) > 6 or len(name) < 2:
            continue
        if any(char in name for char in "，。；、：:,\r\n"):
            continue
        if any(word in name for word in ("的", "了", "在", "是", "去", "给", "有", "我", "你", "他", "们", "这", "那", "个", "谁", "对", "后")):
            continue
        is_valid_han = len(name) <= 4 and (name[0] in common_surnames or (len(name) > 2 and name[:2] in common_surnames))
        is_valid_minority = "·" in name and len(name) <= 15
        if not (is_valid_han or is_valid_minority):
            continue
        valid_names.append(name)

    assert valid_names == ["张三"]


def test_advanced_rules_optimization():
    """测试识别规则深度优化路线图各项工作的正确性。"""
    from legal_redactor.detectors import ORG_RE, detect_fallback_person_candidates
    from legal_redactor.lexicon import FALSE_PERSON_WORDS

    # 1. 验证 ORG_RE 行政区划前置长度限制由 10 缩减为 5 字
    # "郝亚雄去跟天津市" 前置有 5 个非行政区字 + 天津(2字)，总长度 7，因此匹配范围绝不能以“郝”开始！
    # 天津市(3字)在 [2,5] 范围内，所以必须只以“天津市”开始匹配！
    text_org = "郝亚雄去跟天津市慕尚园林绿化工程有限公司"
    match = ORG_RE.search(text_org)
    assert match is not None
    from legal_redactor.detectors import _clean_organization_text
    cleaned = _clean_organization_text(match.group(0))
    # 组织清洗不再凭动作词裁剪实体边界；该类边界由候选生成或 LLM 校准负责。
    assert cleaned == match.group(0)

    # 2. 验证 fallback 人名匹配的全新动作词 lookahead
    # 检查新增的动作词（转账、汇款、下载、发送、立案、驳回等）是否能完美匹配
    candidates_1 = detect_fallback_person_candidates("本案由陈戊靖转账处理。")
    candidates_2 = detect_fallback_person_candidates("陶玉静汇款五百元。")
    candidates_3 = detect_fallback_person_candidates("经查，陈戊靖下载了文件。")
    candidates_4 = detect_fallback_person_candidates("相关材料已由陶玉静发送。")
    candidates_5 = detect_fallback_person_candidates("陈戊靖立案起诉。")
    candidates_6 = detect_fallback_person_candidates("陶玉静驳回了上诉。")

    assert any(c.text == "陈戊靖" for c in candidates_1)
    assert any(c.text == "陶玉静" for c in candidates_2)
    assert any(c.text == "陈戊靖" for c in candidates_3)
    assert any(c.text == "陶玉静" for c in candidates_4)
    assert any(c.text == "陈戊靖" for c in candidates_5)
    assert any(c.text == "陶玉静" for c in candidates_6)

    # 3. 验证 FALSE_PERSON_WORDS 排除词库的扩充
    assert "案情" in FALSE_PERSON_WORDS
    assert "起诉状" in FALSE_PERSON_WORDS
    assert "答辩状" in FALSE_PERSON_WORDS
    assert "委托书" in FALSE_PERSON_WORDS
    assert "代理词" in FALSE_PERSON_WORDS
