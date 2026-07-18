from __future__ import annotations

import json

import pytest

from legal_redactor.config import LLMAPIConfig, PipelineConfig
from legal_redactor.llm import LegalEntityAuditor
from legal_redactor.model_manager import BONSAI_MODEL_ID


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
    assert config.llm.model == BONSAI_MODEL_ID
    assert config.llm.model_manager_host == "127.0.0.1"
    assert config.llm.model_manager_port == 18080


def test_balanced_config_targets_same_manager_model() -> None:
    config = PipelineConfig.balanced_llm()

    assert config.llm.model == BONSAI_MODEL_ID
    assert config.llm.context_window == 8192


def test_from_llm_mode_accepts_registered_model_choice() -> None:
    assert PipelineConfig.from_llm_mode("max-effect").llm.model == BONSAI_MODEL_ID
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
