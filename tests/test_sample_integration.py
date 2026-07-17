import json

import pytest

from legal_redactor._samples import (
    AUTO_SAMPLE_FILE,
    clear_sample_library,
    get_few_shot_examples,
    load_all_samples,
    load_recent_error_samples,
    load_sample_blacklist_for_optimization,
    load_trusted_sample_mappings,
    save_sample_auto,
)
from legal_redactor.config import LLMAPIConfig, PipelineConfig
from legal_redactor.llm import LegalEntityAuditor
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


def test_pipeline_ignores_sample_library_contents_at_runtime(mock_samples, monkeypatch):
    """Runtime redaction must not reuse sample masks or honor sample deletes."""
    tmp_path, _filepath = mock_samples

    import legal_redactor._samples as samples_module

    monkeypatch.setattr(samples_module, "DEFAULT_SAMPLES_DIR", tmp_path)

    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    result = pipeline.redact("原告：张小明。被告：来我去公司。案件涉及绝密代号。", mode="standard")

    # Sample-only mappings/masks must not be injected into runtime results.
    assert "【小明特制掩码】" not in result.redacted_text
    assert "【代号X】" not in result.redacted_text
    assert all(
        not str(mapping.source or "").startswith("sample_library:")
        for mapping in result.redaction_map.mappings
    )


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


def test_pipeline_redaction_is_independent_of_sample_directory_contents(tmp_path, monkeypatch):
    """Different sample stores must not change runtime redaction outputs."""
    import legal_redactor._samples as samples_module

    empty_dir = tmp_path / "empty"
    populated_dir = tmp_path / "populated"
    empty_dir.mkdir()
    populated_dir.mkdir()
    save_sample_auto(
        [
            {"action": "add", "type": "manual", "original": "胖哥公司", "masked": "乙公司"},
            {"action": "delete", "type": "organization", "original": "河北星河建筑工程有限公司"},
            {"action": "add", "type": "manual", "original": "唐山", "masked": "己市"},
            {
                "action": "modify",
                "type": "organization",
                "old_original": "石家庄裕华精密铸造有限公司",
                "new_original": "石家庄裕华精密铸造有限公司",
                "old_masked": "丙公司",
                "new_masked": "甲公司",
            },
            {
                "action": "add",
                "type": "manual",
                "original": "诺亚人力资源发展集团有限公司",
                "masked": "乙人力资源发展集团有限公司",
            },
        ],
        source="today",
        samples_dir=populated_dir,
    )

    text = (
        "原告胖哥公司与河北星河建筑工程有限公司签订合同。"
        "石家庄裕华精密铸造有限公司位于唐山。"
        "诺亚人力资源发展集团有限公司提交了证据。"
    )
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())

    monkeypatch.setattr(samples_module, "DEFAULT_SAMPLES_DIR", empty_dir)
    empty_result = pipeline.redact(text, mode="standard")
    monkeypatch.setattr(samples_module, "DEFAULT_SAMPLES_DIR", populated_dir)
    populated_result = pipeline.redact(text, mode="standard")

    assert empty_result.redacted_text == populated_result.redacted_text
    assert [m.original for m in empty_result.redaction_map.mappings] == [
        m.original for m in populated_result.redaction_map.mappings
    ]
    assert [m.masked for m in empty_result.redaction_map.mappings] == [
        m.masked for m in populated_result.redaction_map.mappings
    ]
    assert all(
        not str(mapping.source or "").startswith("sample_library:")
        for mapping in populated_result.redaction_map.mappings
    )


def test_llm_prompt_builders_never_inject_sample_few_shot(tmp_path, monkeypatch):
    import legal_redactor._samples as samples_module

    unique_negative = "样例误报词XYZ不应出现在提示词"
    unique_positive = "样例正样本公司UVW"
    save_sample_auto(
        [
            {"action": "delete", "type": "organization", "original": unique_negative},
            {"action": "add", "type": "manual", "original": unique_positive, "masked": "乙公司"},
        ],
        source="today",
        samples_dir=tmp_path,
    )
    monkeypatch.setattr(samples_module, "DEFAULT_SAMPLES_DIR", tmp_path)
    few_shot = get_few_shot_examples(samples_dir=tmp_path)
    assert unique_negative in few_shot
    assert unique_positive in few_shot

    auditor = LegalEntityAuditor(LLMAPIConfig(enabled=False))
    sentence_prompt = auditor._build_sentence_extraction_prompt(
        [{"id": "s1", "previous": "", "target": "原告胖哥公司。", "next": ""}],
        enable_samples=True,
    )
    merged_prompt = auditor._build_merged_prompt(
        "原告胖哥公司。",
        [{"text": "胖哥公司", "type": "organization", "context": "原告胖哥公司。"}],
        enable_samples=True,
    )

    assert unique_negative not in sentence_prompt
    assert unique_positive not in sentence_prompt
    assert unique_negative not in merged_prompt
    assert unique_positive not in merged_prompt


def test_clear_sample_library_removes_entries_and_allows_future_writes(tmp_path):
    save_sample_auto(
        [
            {"action": "delete", "type": "organization", "original": "来我去公司"},
            {"action": "add", "type": "manual", "original": "胖哥公司", "masked": "乙公司"},
        ],
        source="today",
        samples_dir=tmp_path,
    )
    lookup_before, blacklist_before = load_all_samples(samples_dir=tmp_path)
    assert lookup_before or blacklist_before

    result = clear_sample_library(tmp_path)
    assert result["removed_entries"] >= 2
    assert result["removed_files"] >= 1
    assert result["sample_file"] == AUTO_SAMPLE_FILE

    auto_path = tmp_path / AUTO_SAMPLE_FILE
    assert auto_path.exists()
    data = json.loads(auto_path.read_text(encoding="utf-8"))
    assert data["entries"] == []
    assert data["total"] == 0

    lookup_after, blacklist_after = load_all_samples(samples_dir=tmp_path)
    assert lookup_after == {}
    assert blacklist_after == set()

    save_sample_auto(
        [{"action": "add", "type": "manual", "original": "新样本公司", "masked": "丙公司"}],
        source="after-clear",
        samples_dir=tmp_path,
    )
    lookup_rebuilt, _ = load_all_samples(samples_dir=tmp_path)
    assert lookup_rebuilt["新样本公司"] == "丙公司"


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

    # 用户将“李四”的候选边界修正为“李四明”并改写掩码。
    # 样本必须同时记录修改前原文，不能把这条记录误作手动新增。
    form_data = {
        "map_type": ["person", "person", "person", "person"],
        "map_original": ["张三", "李四明", "新增人名", "删除人名"],
        "map_original_before": ["张三", "李四", "", ""],
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

    # 期望只保留 3 条记录：李四 -> 李四明 (modify)、新增人名 (add)、删除人名 (delete)
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
            assert e.get("old_original") == "李四"
            assert e.get("new_original") == "李四明"
            assert e.get("old_masked") == "李某1"
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
    assert {item["original"] for item in summary["lookup_entries"]} == {"李四明", "新增人名"}
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
