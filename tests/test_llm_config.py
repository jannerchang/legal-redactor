from __future__ import annotations

import json

import pytest

from legal_redactor.config import LLMAPIConfig, PipelineConfig
from legal_redactor.llm import LegalEntityAuditor
from legal_redactor.model_manager import QWEN_MODEL_ID
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
    assert config.llm.recognition_mode == "full_document"

    assert config.llm.model == QWEN_MODEL_ID
    assert config.llm.model_manager_host == "127.0.0.1"
    assert config.llm.model_manager_port == 18080


def test_balanced_config_targets_same_manager_model() -> None:
    config = PipelineConfig.balanced_llm()

    assert config.llm.model == QWEN_MODEL_ID
    assert config.llm.context_window == 8192
    assert config.llm.full_document_timeout_seconds == 600
    assert config.llm.full_document_max_output_tokens == 1024
    assert config.llm.full_document_retry_count == 1


def test_from_llm_mode_accepts_registered_model_choice() -> None:
    assert PipelineConfig.from_llm_mode("max-effect").llm.model == QWEN_MODEL_ID
    assert PipelineConfig.from_llm_mode("max-effect", model="qwen3.6-27b-fp8").llm.model == "qwen3.6-27b-fp8"
    assert PipelineConfig.from_llm_mode("balanced", model="qwen3.6-27b-fp8").llm.model == "qwen3.6-27b-fp8"

def test_disabled_and_sentence_recognition_modes_are_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be disabled"):
        PipelineConfig.from_llm_mode("off")
    with pytest.raises(ValueError, match="unsupported recognition mode"):
        PipelineConfig.max_effect(recognition_mode="sentence_windows")


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
        LLMAPIConfig(model=QWEN_MODEL_ID, model_manager_host="manager.local", model_manager_port=18080)
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
                "model": QWEN_MODEL_ID,
                "messages": [{"role": "user", "content": "sensitive document prompt"}],
                "stream": False,
                "temperature": 0.0,
                "max_tokens": 321,
                "chat_template_kwargs": {"enable_thinking": False},
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


def test_full_document_calls_use_newline_stop_sequence(monkeypatch) -> None:
    registry = {
        "persons": ["张三"],
        "organizations": [],
        "locations": [],
        "same_entities": [],
    }
    response_body = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(registry, ensure_ascii=False)},
                }
            ]
        },
        ensure_ascii=False,
    )
    _Connection.requests = []
    _Connection.responses = [_Response(200, response_body), _Response(200, response_body)]
    monkeypatch.setattr("legal_redactor.llm.http.client.HTTPConnection", _Connection)
    auditor = LegalEntityAuditor(
        LLMAPIConfig(
            model=QWEN_MODEL_ID,
            recognition_mode="full_document",
            model_manager_host="manager.local",
            model_manager_port=18080,
        )
    )

    result = auditor.extract_full_document_registry("原告张三。")

    assert result.status == "success"
    assert len(_Connection.requests) == 2
    assert all(request["body"]["stop"] == "\n" for request in _Connection.requests)
    assert all(
        request["body"]["chat_template_kwargs"] == {"enable_thinking": False}
        for request in _Connection.requests
    )
    assert all(request["body"]["max_tokens"] == 1024 for request in _Connection.requests)
    assert all(request["timeout"] == 600 for request in _Connection.requests)


def test_full_document_token_limit_accepts_complete_json_before_trailing_runaway(monkeypatch) -> None:
    registry_json = '{"persons":["张三"],"organizations":[],"locations":[],"same_entities":[]}'
    limited_body = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": registry_json + registry_json + '{"persons":["张'},
                }
            ],
            "usage": {"completion_tokens": 1024},
        },
        ensure_ascii=False,
    )
    empty_body = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": '{"persons":[],"organizations":[],"locations":[],"same_entities":[]}'
                    },
                }
            ]
        },
        ensure_ascii=False,
    )
    _Connection.requests = []
    _Connection.responses = [_Response(200, limited_body), _Response(200, empty_body)]
    monkeypatch.setattr("legal_redactor.llm.http.client.HTTPConnection", _Connection)

    result = LegalEntityAuditor(LLMAPIConfig()).extract_full_document_registry("原告张三。")

    assert result.status == "success"
    assert result.metadata.call_count == 2
    assert result.metadata.retry_count == 0
    assert [entity.variants for entity in result.validation.registry.entities] == [("张三",)]
    assert len(_Connection.requests) == 2


def test_full_document_token_limit_retries_once_with_repair_prompt(monkeypatch) -> None:
    registry = {
        "persons": ["张三"],
        "organizations": [],
        "locations": [],
        "same_entities": [],
    }
    limited_body = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": '{"persons":["张三"'},
                }
            ],
            "usage": {"completion_tokens": 1024},
        },
        ensure_ascii=False,
    )
    repaired_body = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(registry, ensure_ascii=False)},
                }
            ],
            "usage": {"completion_tokens": 40},
        },
        ensure_ascii=False,
    )
    empty_body = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": '{"persons":[],"organizations":[],"locations":[],"same_entities":[]}'
                    },
                }
            ],
            "usage": {"completion_tokens": 20},
        },
        ensure_ascii=False,
    )
    _Connection.requests = []
    _Connection.responses = [
        _Response(200, limited_body),
        _Response(200, repaired_body),
        _Response(200, empty_body),
    ]
    monkeypatch.setattr("legal_redactor.llm.http.client.HTTPConnection", _Connection)

    result = LegalEntityAuditor(LLMAPIConfig()).extract_full_document_registry("原告张三。")

    assert result.status == "success"
    assert result.reason is None
    assert result.metadata.call_count == 3
    assert result.metadata.retry_count == 1
    assert len(_Connection.requests) == 3
    assert "上一轮输出不是合法的案件级实体 JSON" in _Connection.requests[1]["body"]["messages"][0]["content"]


def test_full_document_repeated_token_limit_fails_closed(monkeypatch) -> None:
    response_body = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": '{"persons":["张三"'},
                }
            ],
            "usage": {"completion_tokens": 1024},
        },
        ensure_ascii=False,
    )
    _Connection.requests = []
    _Connection.responses = [_Response(200, response_body), _Response(200, response_body)]
    monkeypatch.setattr("legal_redactor.llm.http.client.HTTPConnection", _Connection)

    result = LegalEntityAuditor(LLMAPIConfig()).extract_full_document_registry("原告张三。")

    assert result.status == "fallback"
    assert result.reason == "output_token_limit"
    assert result.metadata.finish_reason == "length"
    assert result.metadata.call_count == 2
    assert result.metadata.retry_count == 1
    assert len(_Connection.requests) == 2


def test_full_document_supplement_failure_preserves_primary_registry(monkeypatch) -> None:
    primary_registry = {
        "persons": ["张三"],
        "organizations": [],
        "locations": [],
        "same_entities": [],
    }
    primary_body = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(primary_registry, ensure_ascii=False)},
                }
            ]
        },
        ensure_ascii=False,
    )
    supplement_body = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": '{"persons":["李四"'},
                }
            ],
            "usage": {"completion_tokens": 1024},
        },
        ensure_ascii=False,
    )
    _Connection.requests = []
    _Connection.responses = [
        _Response(200, primary_body),
        _Response(200, supplement_body),
        _Response(200, supplement_body),
    ]
    monkeypatch.setattr("legal_redactor.llm.http.client.HTTPConnection", _Connection)

    result = LegalEntityAuditor(LLMAPIConfig()).extract_full_document_registry("原告张三，被告李四。")

    assert result.status == "success"
    assert result.reason == "supplement_output_token_limit"
    assert [entity.variants for entity in result.validation.registry.entities] == [("张三",)]
    assert result.metadata.call_count == 3
    assert result.metadata.retry_count == 1
    assert len(_Connection.requests) == 3
    assert "上一轮补漏输出不是合法 JSON" in _Connection.requests[2]["body"]["messages"][0]["content"]


def test_full_document_supplement_invalid_entities_gets_one_repair_attempt(monkeypatch) -> None:
    primary_registry = {
        "persons": ["张三"],
        "organizations": [],
        "locations": [],
        "same_entities": [],
    }
    repaired_supplement = {
        "persons": ["李四"],
        "organizations": [],
        "locations": [],
        "same_entities": [],
    }

    def completion(content: object) -> _Response:
        response_body = json.dumps(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": content
                            if isinstance(content, str)
                            else json.dumps(content, ensure_ascii=False)
                        },
                    }
                ]
            },
            ensure_ascii=False,
        )
        return _Response(200, response_body)

    _Connection.requests = []
    _Connection.responses = [
        completion(primary_registry),
        completion('{"persons":["李四"],"organizations":[],"locations":[],"same_entities":{}}'),
        completion(repaired_supplement),
    ]
    monkeypatch.setattr("legal_redactor.llm.http.client.HTTPConnection", _Connection)

    result = LegalEntityAuditor(LLMAPIConfig()).extract_full_document_registry("原告张三，被告李四。")

    assert result.status == "success"
    assert [entity.variants for entity in result.validation.registry.entities] == [("张三",), ("李四",)]


    assert result.metadata.call_count == 3
    assert result.metadata.retry_count == 1
    assert len(_Connection.requests) == 3
    repair_prompt = _Connection.requests[2]["body"]["messages"][0]["content"]
    assert "上一轮补漏输出不是合法 JSON" in repair_prompt


def test_full_document_transport_failure_preserves_http_reason_and_logs(caplog) -> None:
    _Connection.requests = []
    _Connection.responses = [_Response(503, '{"error":{"code":"model_unavailable"}}')]
    auditor = LegalEntityAuditor(
        LLMAPIConfig(
            model=QWEN_MODEL_ID,
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
            model=QWEN_MODEL_ID,
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
    assert result.metadata.finish_reason is None
    assert "全文 LLM 调用 1/2：阶段=初次登记" in messages
    assert "全文 LLM 调用 1/2：阶段=二次补漏" in messages
    assert "全文 LLM 完成：实体=1" in messages


def test_full_document_prompt_requires_minimal_identity_groups() -> None:
    auditor = LegalEntityAuditor(LLMAPIConfig(recognition_mode="full_document"))
    prompt = auditor._build_full_document_registry_prompt("星河建设有限公司又称星河公司。")

    assert "只输出一行紧凑 JSON" in prompt
    assert "persons、organizations、locations 只列去重后的原文名称字符串" in prompt
    assert "same_entities 只列原文用又名、曾用名、简称、以下简称或同一人明确确认" in prompt
    assert "张三与李四这类不同完整人名禁止合并" in prompt
    assert '"persons":["张三","李四"]' in prompt
    assert "无法确认就不列" in prompt
    assert "same_entities 两项文字必须不同，禁止名称与自身配对" in prompt
    assert "地点必须登记原文出现的省级、地级市和市辖区名称" in prompt
    assert "禁止登记县、旗、乡镇、街道、村、社区" in prompt
    assert "全文出现的所有有专名的具体法律主体或经营主体，不限于当事人" in prompt
    assert "逐段清点公司、集团、银行、分支行、律所、医院、学校、经营部、安装部、安装队、经销处" in prompt
    assert "非当事人、代发工资主体、供应商、承包商、付款主体" in prompt
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
    assert '{"persons":[],"organizations":[],"locations":[],"same_entities":[]}' in prompt
    assert "每个字段只允许出现一次" in prompt

    assert "禁止名称与自身配对" in prompt
    assert "地点必须登记原文出现的省级、地级市和以‘区’结尾的市辖区名称" in prompt
    assert "不限于当事人" in prompt
    assert "先逐段复核第一轮清单" in prompt
    assert "经营部、安装部、安装队、经销处" in prompt
    assert "代发工资主体、供应商、承包商、付款主体" in prompt

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


def test_registry_parser_drops_malformed_same_entity_pairs_without_dropping_entities() -> None:
    from legal_redactor.entity_registry import parse_full_document_registry

    result = parse_full_document_registry(
        {
            "persons": ["张三"],
            "organizations": ["星河建设有限公司", "星河公司"],
            "locations": [],
            "same_entities": [
                ["星河建设有限公司", "星河公司"],
                ["张三"],
                {"left": "张三", "right": "李四"},
                ["张三", 1],
            ],
        }
    )

    assert result.valid
    assert [(entity.entity_type, entity.variants) for entity in result.registry.entities] == [
        ("person", ("张三",)),
        ("organization", ("星河建设有限公司", "星河公司")),
    ]


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


def test_registry_parser_ignores_nonminimal_top_level_fields() -> None:
    from legal_redactor.entity_registry import parse_full_document_registry

    result = parse_full_document_registry(
        {
            "persons": ["张三"],
            "organizations": [],
            "locations": [],
            "same_entities": [],
            "evidence": ["原告张三"],
            "explanation": "模型附加说明",
        }
    )

    assert result.valid
    assert [(entity.entity_type, entity.variants) for entity in result.registry.entities] == [
        ("person", ("张三",))
    ]


def test_registry_parser_defaults_omitted_empty_minimal_fields() -> None:
    from legal_redactor.entity_registry import parse_full_document_registry

    result = parse_full_document_registry(
        {
            "persons": ["张三"],
            "organizations": [],
        }
    )

    assert result.valid
    assert [(entity.entity_type, entity.variants) for entity in result.registry.entities] == [
        ("person", ("张三",))
    ]


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

def test_registry_materialization_filters_sample_derived_false_entities() -> None:
    text = "目标松地。107。土地差价款。民间借贷案件。地产公司。裕华区法院。阆中法院。劳动仲裁委。"
    entities = (
        RegistryEntity("person-1", "person", "目标松地", ("目标松地",)),
        *(RegistryEntity(f"org-{index}", "organization", value, (value,)) for index, value in enumerate(
            ("107", "土地差价款", "民间借贷案件", "地产公司", "裕华区法院", "阆中法院", "劳动仲裁委"),
            1,
        )),
    )
    validation = validate_registry_against_text(
        text,
        RegistryValidationResult(registry=FullDocumentEntityRegistry(entities=entities)),
    )

    assert materialize_registry_candidates(text, validation).candidates == ()


def test_registry_materialization_keeps_named_factory_and_valid_person() -> None:
    text = "平山县永鸿金属制品厂负责人杨利进到庭。"
    validation = validate_registry_against_text(
        text,
        RegistryValidationResult(
            registry=FullDocumentEntityRegistry(
                entities=(
                    RegistryEntity(
                        "org-1",
                        "organization",
                        "平山县永鸿金属制品厂",
                        ("平山县永鸿金属制品厂",),
                    ),
                    RegistryEntity("person-1", "person", "杨利进", ("杨利进",)),
                )
            )
        ),
    )

    assert [candidate.text for candidate in materialize_registry_candidates(text, validation).candidates] == [
        "平山县永鸿金属制品厂",
        "杨利进",
    ]

def test_registry_materialization_keeps_named_business_outlet_suffixes() -> None:
    text = (
        "高新区泽行机械设备安装队、藁城区尚远机械设备安装部、"
        "长安启明机械设备经营部和泽新经销处分别发放工资。"
    )
    values = (
        "高新区泽行机械设备安装队",
        "藁城区尚远机械设备安装部",
        "长安启明机械设备经营部",
        "泽新经销处",
    )
    validation = validate_registry_against_text(
        text,
        RegistryValidationResult(
            registry=FullDocumentEntityRegistry(
                entities=tuple(
                    RegistryEntity(f"org-{index}", "organization", value, (value,))
                    for index, value in enumerate(values, 1)
                )
            )
        ),
    )

    assert [
        candidate.text for candidate in materialize_registry_candidates(text, validation).candidates
    ] == list(values)


def test_named_business_outlet_mappings_survive_postprocess() -> None:
    from legal_redactor.models import MappingEntry
    from legal_redactor.postprocess import PostprocessConfig, apply_postprocess

    values = (
        "高新区泽行机械设备安装队",
        "藁城区尚远机械设备安装部",
        "长安启明机械设备经营部",
        "泽新经销处",
    )
    mappings = [
        MappingEntry(
            type="organization",
            original=value,
            masked=f"{index}机构",
            role=None,
            source="linear:full_document_llm",
            confidence=0.9,
            restore_by_default=True,
        )
        for index, value in enumerate(values, 1)
    ]

    assert apply_postprocess("、".join(values), mappings, PostprocessConfig()) == mappings



def test_named_factory_survives_mapping_postprocess() -> None:
    from legal_redactor.models import MappingEntry
    from legal_redactor.postprocess import PostprocessConfig, apply_postprocess

    mapping = MappingEntry(
        type="organization",
        original="平山县永鸿金属制品厂",
        masked="甲厂",
        role=None,
        source="linear:full_document_llm",
        confidence=0.9,
        restore_by_default=True,
    )

    assert apply_postprocess(
        "平山县永鸿金属制品厂",
        [mapping],
        PostprocessConfig(),
    ) == [mapping]


def test_registry_validation_preserves_explicit_person_aliases() -> None:
    from legal_redactor.entity_registry import parse_full_document_registry

    text = "原告张三（曾用名李四）提起诉讼。"
    parsed = parse_full_document_registry(
        {
            "persons": ["张三", "李四"],
            "organizations": [],
            "locations": [],
            "same_entities": [["张三", "李四"]],
        }
    )

    validation = validate_registry_against_text(text, parsed)

    assert [(entity.entity_id, entity.variants) for entity in validation.registry.entities] == [
        ("person-1", ("张三", "李四"))
    ]
    assert validation.registry.do_not_merge == ()


def test_registry_validation_splits_unverified_person_identity_claim() -> None:
    from legal_redactor.entity_registry import parse_full_document_registry

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

    assert [(entity.entity_id, entity.variants) for entity in validation.registry.entities] == [
        ("person-1", ("张三",)),
        ("person-2", ("李四",)),
    ]
    assert tuple(pair.normalized() for pair in validation.registry.do_not_merge) == (
        ("person-1", "person-2"),
    )
    assert "registry_person_identity_splits:1" in validation.warnings



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
