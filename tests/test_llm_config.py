from __future__ import annotations

import json

import pytest

from legal_redactor.config import LLMAPIConfig, PipelineConfig
from legal_redactor.llm import LegalEntityAuditor
from legal_redactor.model_manager import BONSAI_MODEL_ID, QWEN_MODEL_ID
from legal_redactor.entity_registry import (
    DoNotMergePair,
    FullDocumentEntityRegistry,
    RegistryEntity,
    RegistryValidationResult,
    UncertainEntity,
    materialize_registry_candidates,
    validate_registry_against_text,
)


class _Response:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body


class _Connection:
    responses: list[_Response] = []
    requests: list[dict] = []

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def request(self, method: str, path: str, body: bytes, headers: dict[str, str]) -> None:
        self.requests.append(
            {
                "host": self.host,
                "port": self.port,
                "timeout": self.timeout,
                "method": method,
                "path": path,
                "body": json.loads(body),
                "headers": headers,
            }
        )

    def getresponse(self) -> _Response:
        return self.responses.pop(0)

    def close(self) -> None:
        return None


def test_max_effect_config_targets_manager_logical_model() -> None:
    config = PipelineConfig.max_effect()

    assert config.profile == "standard"
    assert config.semantic_llm_first
    assert config.llm.model == QWEN_MODEL_ID
    assert config.llm.model_manager_host == "127.0.0.1"
    assert config.llm.model_manager_port == 18080


def test_balanced_config_targets_same_manager_model() -> None:
    config = PipelineConfig.balanced_llm()

    assert config.llm.model == QWEN_MODEL_ID
    assert config.llm.context_window == 8192
    assert config.llm.full_document_timeout_seconds == 600


def test_from_llm_mode_accepts_registered_model_choice() -> None:
    assert PipelineConfig.from_llm_mode("max-effect").llm.model == QWEN_MODEL_ID
    assert PipelineConfig.from_llm_mode("max-effect", model="qwen3.5-9b").llm.model == "qwen3.5-9b"
    assert PipelineConfig.from_llm_mode("balanced", model="qwen3.5-9b").llm.model == "qwen3.5-9b"


def test_auditor_sends_openai_manager_request_and_parses_choice(monkeypatch) -> None:
    _Connection.requests = []
    _Connection.responses = [
        _Response(
            200,
            '{"choices":[{"message":{"content":"{\\"locations\\":[],\\"companies\\":[],\\"persons\\":[],\\"projects\\":[],\\"reject\\":[],\\"calibrate\\":{}}"}}]}',
        )
    ]
    monkeypatch.setattr("legal_redactor.llm.http.client.HTTPConnection", _Connection)
    auditor = LegalEntityAuditor(
        LLMAPIConfig(model=BONSAI_MODEL_ID, model_manager_host="manager.local", model_manager_port=18080)
    )

    result = auditor._call_model_manager("sensitive document prompt", max_tokens=321)

    assert result["locations"] == []
    assert result["companies"] == []
    assert result["persons"] == []
    assert result["projects"] == []
    assert result["reject"] == []
    assert result["calibrate"] == {}
    assert _Connection.requests == [
        {
            "host": "manager.local",
            "port": 18080,
            "timeout": 120,
            "method": "POST",
            "path": "/v1/chat/completions",
            "body": {
                "model": BONSAI_MODEL_ID,
                "messages": [{"role": "user", "content": "sensitive document prompt"}],
                "stream": False,
                "temperature": 0.0,
                "max_tokens": 321,
            },
            "headers": {"Content-Type": "application/json"},
        }
    ]


@pytest.mark.parametrize(
    "response",
    [
        _Response(503, '{"error":{"code":"model_unavailable"}}'),
        _Response(200, "not-json"),
        _Response(200, '{"choices":[]}'),
    ],
)
def test_auditor_manager_errors_do_not_echo_prompt(monkeypatch, response) -> None:
    _Connection.requests = []
    _Connection.responses = [response]
    monkeypatch.setattr("legal_redactor.llm.http.client.HTTPConnection", _Connection)
    auditor = LegalEntityAuditor(LLMAPIConfig())
    prompt = "张三的私密文书内容"

    with pytest.raises(RuntimeError) as raised:
        auditor._call_model_manager(prompt)

    assert prompt not in str(raised.value)


def test_full_document_call_uses_newline_stop_sequence(monkeypatch) -> None:
    registry = {
        "persons": ["张三"],
        "organizations": [],
        "locations": [],
        "same_entities": [],
    }
    response_body = json.dumps(
        {"choices": [{"message": {"content": json.dumps(registry, ensure_ascii=False)}}]},
        ensure_ascii=False,
    )
    _Connection.requests = []
    _Connection.responses = [_Response(200, response_body), _Response(200, response_body)]
    monkeypatch.setattr("legal_redactor.llm.http.client.HTTPConnection", _Connection)
    auditor = LegalEntityAuditor(
        LLMAPIConfig(
            model=BONSAI_MODEL_ID,
            recognition_mode="full_document",
            model_manager_host="manager.local",
            model_manager_port=18080,
        )
    )

    result = auditor.extract_full_document_registry("原告张三。")

    assert result.status == "success"
    assert len(_Connection.requests) == 2
    assert all(request["body"]["stop"] == "\n" for request in _Connection.requests)


def test_full_document_transport_failure_preserves_http_reason_and_logs(caplog) -> None:
    _Connection.requests = []
    _Connection.responses = [_Response(503, '{"error":{"code":"model_unavailable"}}')]
    auditor = LegalEntityAuditor(
        LLMAPIConfig(
            model=BONSAI_MODEL_ID,
            recognition_mode="full_document",
            model_manager_host="manager.local",
            model_manager_port=18080,
        )
    )

    with pytest.MonkeyPatch.context() as monkeypatch, caplog.at_level("INFO", logger="legal_redactor"):
        monkeypatch.setattr("legal_redactor.llm.http.client.HTTPConnection", _Connection)
        result = auditor.extract_full_document_registry("原告张三。")

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert result.status == "fallback"
    assert result.reason == "http_503"
    assert result.metadata.http_status == 503
    assert result.metadata.call_count == 1
    assert "全文 LLM 开始" in messages
    assert "原因=http_503" in messages
    assert "HTTP=503" in messages


def test_full_document_success_logs_stage_progress(caplog) -> None:
    registry = {
        "persons": ["张三"],
        "organizations": [],
        "locations": [],
        "same_entities": [],
    }
    response_body = json.dumps(
        {
            "choices": [{"message": {"content": json.dumps(registry, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
        },
        ensure_ascii=False,
    )
    _Connection.requests = []
    _Connection.responses = [_Response(200, response_body), _Response(200, response_body)]
    auditor = LegalEntityAuditor(
        LLMAPIConfig(
            model=BONSAI_MODEL_ID,
            recognition_mode="full_document",
            model_manager_host="manager.local",
            model_manager_port=18080,
        )
    )

    with pytest.MonkeyPatch.context() as monkeypatch, caplog.at_level("INFO", logger="legal_redactor"):
        monkeypatch.setattr("legal_redactor.llm.http.client.HTTPConnection", _Connection)
        result = auditor.extract_full_document_registry("原告张三。")

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert result.status == "success"
    assert result.metadata.call_count == 2
    assert result.metadata.completion_token_count == 80
    assert "全文 LLM 调用 1/2：阶段=初次登记" in messages
    assert "全文 LLM 调用 1/2：阶段=二次补漏" in messages
    assert "全文 LLM 完成：实体=1" in messages


def test_full_document_prompt_requires_minimal_identity_groups() -> None:
    auditor = LegalEntityAuditor(LLMAPIConfig(recognition_mode="full_document"))
    prompt = auditor._build_full_document_registry_prompt("星河建设有限公司又称星河公司。")

    assert "只输出一行紧凑 JSON" in prompt
    assert "persons、organizations、locations 只列去重后的原文名称字符串" in prompt
    assert "same_entities 只列全文明确属于同一主体的两个名称" in prompt
    assert '"persons":["张三","李四"]' in prompt
    assert "无法确认就不列" in prompt
    assert "不要证据、entity_id、type、confidence、解释、Markdown、脱敏稿、换行或其他字段" in prompt
    assert "输出最后一个 } 后立即停止" in prompt
    assert '"same_entities":[["星河建设有限公司","星河公司"]]' in prompt


def test_full_document_supplement_prompt_excludes_known_names_and_keeps_full_text() -> None:
    from legal_redactor.entity_registry import FullDocumentEntityRegistry, RegistryEntity, RegistryValidationResult

    auditor = LegalEntityAuditor(LLMAPIConfig(recognition_mode="full_document"))
    primary = RegistryValidationResult(
        registry=FullDocumentEntityRegistry(
            entities=(RegistryEntity("person-1", "person", "张三", ("张三",)),)
        )
    )

    prompt = auditor._build_full_document_supplement_prompt("张三与遗漏的李四。", primary)

    assert "二次" not in prompt
    assert "补漏器" in prompt
    assert '"persons":["张三"]' in prompt
    assert "张三与遗漏的李四。" in prompt
    assert "没有遗漏就输出四个空数组" in prompt


def test_truncated_registry_repair_only_closes_existing_json_structure() -> None:
    truncated = '{"persons":["张三"],"organizations":["星河建设有限公司"],"locations":[],"same_entities":['

    repaired = LegalEntityAuditor._repair_full_document_registry_payload(truncated)

    assert repaired == '{"persons":["张三"],"organizations":["星河建设有限公司"],"locations":[]}'
    assert json.loads(repaired) == {
        "persons": ["张三"],
        "organizations": ["星河建设有限公司"],
        "locations": [],
    }
    assert "same_entities" not in repaired


def test_registry_repair_does_not_rewrite_complete_or_non_json_output() -> None:
    complete = '{"persons":[],"organizations":[],"locations":[],"same_entities":[]}'

    assert LegalEntityAuditor._repair_full_document_registry_payload(complete) is None
    assert LegalEntityAuditor._repair_full_document_registry_payload("模型解释文本") is None


def test_registry_parser_builds_identity_groups_and_bounds_names() -> None:
    from legal_redactor.entity_registry import parse_full_document_registry
    result = parse_full_document_registry(
        {
            "persons": ["张三"],
            "organizations": ["甲公司", *[f"甲公司别名{i}" for i in range(20)]],
            "locations": ["北京市"],
            "same_entities": [["甲公司", f"甲公司别名{i}"] for i in range(20)],
        }
    )

    assert result.valid
    person, organization, location = result.registry.entities
    assert person.entity_id == "person-1"
    assert person.variants == ("张三",)
    assert organization.entity_id == "org-1"
    assert organization.primary_text == "甲公司别名10"
    assert organization.variants == tuple(["甲公司", *[f"甲公司别名{i}" for i in range(15)]])
    assert location.entity_id == "location-1"
    assert location.variants == ("北京市",)


def test_registry_parser_keeps_first_type_for_duplicate_model_name() -> None:
    from legal_redactor.entity_registry import parse_full_document_registry

    result = parse_full_document_registry(
        {
            "persons": [],
            "organizations": ["河南省高级人民法院"],
            "locations": ["河南省高级人民法院", "河南省"],
            "same_entities": [],
        }
    )

    assert result.valid
    assert [(entity.entity_type, entity.variants) for entity in result.registry.entities] == [
        ("organization", ("河南省高级人民法院",)),
        ("location", ("河南省",)),
    ]


def test_registry_parser_rejects_nonminimal_top_level_fields() -> None:
    from legal_redactor.entity_registry import parse_full_document_registry

    result = parse_full_document_registry(
        {
            "persons": ["张三"],
            "organizations": [],
            "locations": [],
            "same_entities": [],
            "evidence": ["原告张三"],
        }
    )

    assert not result.valid
    assert result.error == "invalid_entities"


def test_registry_validation_requires_exact_source_text_and_materializes_local_spans() -> None:
    text = "原告张三起诉星河建设有限公司，星河公司答辩。"
    validation = validate_registry_against_text(
        text,
        RegistryValidationResult(
            registry=FullDocumentEntityRegistry(
                entities=(
                    RegistryEntity("person-1", "person", "张三", ("张三", "张某")),
                    RegistryEntity(
                        "org-1",
                        "organization",
                        "星河建设有限公司",
                        ("星河建设有限公司", "星河公司", "不存在公司"),
                    ),
                )
            )
        ),
    )

    assert validation.dropped_variant_count == 2
    materialization = materialize_registry_candidates(text, validation)
    assert [
        (candidate.text, candidate.start, candidate.end)
        for candidate in materialization.candidates
    ] == [
        ("张三", text.index("张三"), text.index("张三") + len("张三")),
        (
            "星河建设有限公司",
            text.index("星河建设有限公司"),
            text.index("星河建设有限公司") + len("星河建设有限公司"),
        ),
        ("星河公司", text.index("星河公司"), text.index("星河公司") + len("星河公司")),
    ]


def test_registry_conflicts_and_uncertain_entities_never_auto_redact() -> None:
    text = "张三提交材料。"
    validation = validate_registry_against_text(
        text,
        RegistryValidationResult(
            registry=FullDocumentEntityRegistry(
                entities=(
                    RegistryEntity("person-1", "person", "张三", ("张三",)),
                    RegistryEntity("person-2", "person", "张三", ("张三",)),
                ),
                uncertain=(UncertainEntity("张三", "person", ("person-1", "person-2")),),
            )
        ),
    )

    materialization = materialize_registry_candidates(text, validation)

    assert validation.conflicts
    assert materialization.candidates == ()
    assert materialization.review_candidates
    assert all(not candidate.auto_redact for candidate in materialization.review_candidates)


def test_registry_do_not_merge_constraint_reaches_materialized_candidates() -> None:
    text = "星河建设有限公司与星河科技有限公司并非同一主体。"
    validation = validate_registry_against_text(
        text,
        RegistryValidationResult(
            registry=FullDocumentEntityRegistry(
                entities=(
                    RegistryEntity("org-1", "organization", "星河建设有限公司", ("星河建设有限公司",)),
                    RegistryEntity("org-2", "organization", "星河科技有限公司", ("星河科技有限公司",)),
                ),
                do_not_merge=(DoNotMergePair("org-1", "org-2"),),
            )
        ),
    )

    materialization = materialize_registry_candidates(text, validation)
    blocked_by_id = {
        candidate.metadata["registry_entity_id"]: candidate.metadata["registry_do_not_merge"]
        for candidate in materialization.candidates
    }

    assert blocked_by_id == {"org-1": ["org-2"], "org-2": ["org-1"]}
