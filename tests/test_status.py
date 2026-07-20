from __future__ import annotations

import json
import socket

from legal_redactor.local_config import diagnose_json_config, load_json_config
from legal_redactor.status import (
    StatusItem,
    build_status_payload,
    probe_case_root,
    probe_model_manager,
    probe_recognition_mode,
)


def test_status_item_shape_and_secret_filtering() -> None:
    item = StatusItem(
        "office_api",
        "Office API",
        "ready",
        "ok",
        "none",
        {"api_token": "super-secret", "api_token_present": True},
    ).to_dict()

    assert set(item) == {"id", "label", "state", "message", "action", "details"}
    assert item["state"] == "ready"
    assert item["details"]["api_token_present"] is True
    assert "super-secret" not in json.dumps(item, ensure_ascii=False)


def test_status_details_recursively_scrub_paths_and_secret_values() -> None:
    item = StatusItem(
        "llm_api",
        "LLM API",
        "ready",
        "ok",
        "none",
        {
            "model_ids": [
                "remote-model",
                "/Users/example/private-model",
                "C:\\Users\\private-user\\private-model\\model.bin",
                "https://example.com/docs/path",
                "合同编号 A\\B-001",
                {"path": "/Volumes/cases/model.bin", "note": "Bearer secret-token-value"},
            ],
            "nested": {"config_path": "/Users/example/config/api.local.json"},
            "message": "案件库目录存在且可写。",
        },
    ).to_dict()

    text = json.dumps(item, ensure_ascii=False)
    model_ids = item["details"]["model_ids"]
    assert "remote-model" in model_ids
    assert "https://example.com/docs/path" in model_ids
    assert "合同编号 A\\B-001" in model_ids
    assert item["details"]["message"] == "案件库目录存在且可写。"
    assert "/Users/" not in text
    assert "/Volumes/" not in text
    assert "secret-token-value" not in text
    assert "private-user" not in text
    assert "private-model" not in text
    assert "model.bin" not in text
    assert "api.local.json" not in text
    assert "configured" in text


def test_json_config_diagnostics_preserve_safe_default(tmp_path, monkeypatch) -> None:
    missing = diagnose_json_config("LEGAL_REDACTOR_API_CONFIG", "api.local.json", environ={}, config_dir=tmp_path)
    assert missing.state == "missing"
    assert missing.value == {}

    invalid_path = tmp_path / "bad.json"
    invalid_path.write_text("{bad", encoding="utf-8")
    invalid = diagnose_json_config("LEGAL_REDACTOR_API_CONFIG", "api.local.json", environ={"LEGAL_REDACTOR_API_CONFIG": str(invalid_path)})
    assert invalid.state == "invalid_json"

    list_path = tmp_path / "list.json"
    list_path.write_text("[]", encoding="utf-8")
    non_object = diagnose_json_config("LEGAL_REDACTOR_API_CONFIG", "api.local.json", environ={"LEGAL_REDACTOR_API_CONFIG": str(list_path)})
    assert non_object.state == "non_object"

    ready_path = tmp_path / "ready.json"
    ready_path.write_text(json.dumps({"api_token": "secret"}), encoding="utf-8")
    ready = diagnose_json_config("LEGAL_REDACTOR_API_CONFIG", "api.local.json", environ={"LEGAL_REDACTOR_API_CONFIG": str(ready_path)})
    assert ready.state == "ready"
    assert ready.value == {"api_token": "secret"}

    monkeypatch.setenv("LEGAL_REDACTOR_API_CONFIG", str(invalid_path))
    assert load_json_config("LEGAL_REDACTOR_API_CONFIG", "api.local.json") == {}


def test_model_manager_probe_checks_health_and_logical_registry(monkeypatch) -> None:
    responses = iter(
        [
            (200, json.dumps({"status": "ok", "active_model": None, "worker_state": "stopped"})),
            (200, json.dumps({"data": [{"id": "bonsai-27b"}, {"id": "qwen3.5-9b"}]})),
        ]
    )
    monkeypatch.setattr("legal_redactor.status._http_get", lambda *args: next(responses))

    item = probe_model_manager(
        environ={"LEGAL_REDACTOR_MODEL_MANAGER_HOST": "manager.example.test", "LEGAL_REDACTOR_MODEL_MANAGER_PORT": "8123"},
        timeout=0.01,
    )

    assert item.state == "ready"
    assert item.details == {
        "host": "manager.example.test",
        "port": 8123,
        "worker_state": "stopped",
        "model_ids": ["bonsai-27b", "qwen3.5-9b"],
    }



def test_model_manager_probe_reports_worker_error_as_unavailable(monkeypatch) -> None:
    responses = iter(
        [
            (200, json.dumps({"status": "error", "active_model": None, "worker_state": "error"})),
        ]
    )
    monkeypatch.setattr("legal_redactor.status._http_get", lambda *args: next(responses))

    item = probe_model_manager(environ={}, timeout=0.01)

    assert item.state == "error"
    assert item.details["worker_state"] == "error"
    assert item.details["reason"] == "worker_error"
    assert probe_recognition_mode(item).state == "degraded"
def test_model_manager_probe_classifies_invalid_and_unavailable_responses(monkeypatch) -> None:
    assert probe_model_manager(environ={"LEGAL_REDACTOR_MODEL_MANAGER_PORT": "bad"}).state == "error"
    assert probe_model_manager(environ={"LEGAL_REDACTOR_SKIP_MLX": "1", "LEGAL_REDACTOR_MODEL_MANAGER_PORT": "bad"}).state == "skipped"

    monkeypatch.setattr("legal_redactor.status._http_get", lambda *args: (503, "{}"))
    assert "HTTP 503" in probe_model_manager(environ={}, timeout=0.01).message

    monkeypatch.setattr("legal_redactor.status._http_get", lambda *args: (200, "not-json"))
    assert "有效 JSON" in probe_model_manager(environ={}, timeout=0.01).message

    responses = iter([(200, json.dumps({"status": "ok"})), (200, "[]")])
    monkeypatch.setattr("legal_redactor.status._http_get", lambda *args: next(responses))
    assert "模型列表格式" in probe_model_manager(environ={}, timeout=0.01).message

    responses = iter([(200, json.dumps({"status": "ok"})), (200, json.dumps({"data": []}))])
    monkeypatch.setattr("legal_redactor.status._http_get", lambda *args: next(responses))
    assert "没有可用模型" in probe_model_manager(environ={}, timeout=0.01).message

    def raise_timeout(*args: object) -> tuple[int, str]:
        raise socket.timeout()

    monkeypatch.setattr("legal_redactor.status._http_get", raise_timeout)
    assert probe_model_manager(environ={}, timeout=0.01).state == "error"

    def raise_oserror(*args: object) -> tuple[int, str]:
        raise OSError("connection refused")

    monkeypatch.setattr("legal_redactor.status._http_get", raise_oserror)
    assert probe_model_manager(environ={}, timeout=0.01).state == "missing"


def test_model_manager_failure_reports_degraded_recognition_mode() -> None:
    api = StatusItem("model_manager", "本地模型 API", "missing", "down", "configure")
    fallback = probe_recognition_mode(api)

    assert fallback.state == "degraded"
    assert "低于 LLM 辅助模式" in fallback.message


def test_case_root_probe_ready_missing_and_unwritable(tmp_path) -> None:
    assert probe_case_root(tmp_path / "missing").state == "missing"
    assert probe_case_root(tmp_path).state == "ready"

    locked = tmp_path / "locked"
    locked.mkdir()
    old_mode = locked.stat().st_mode
    try:
        locked.chmod(0o500)
        assert probe_case_root(locked).state == "error"
    finally:
        locked.chmod(old_mode)


def test_status_payload_does_not_expose_secrets_or_sensitive_text(tmp_path, monkeypatch) -> None:
    api_config = tmp_path / "api.local.json"
    api_config.write_text(
        json.dumps(
            {
                "case_root": str(tmp_path),
                "api_token": "office-secret-token",
                "discord_bot_token": "discord-secret-token",
                "discord_command_channel_id": "123456",
            }
        ),
        encoding="utf-8",
    )
    mcp_config = tmp_path / "mcp.local.json"
    mcp_config.write_text(
        json.dumps({"api_url": "http://100.64.0.1:8787", "api_token": "mcp-secret-token"}),
        encoding="utf-8",
    )

    payload = build_status_payload(
        environ={
            "LEGAL_REDACTOR_API_CONFIG": str(api_config),
            "LEGAL_REDACTOR_MCP_CONFIG": str(mcp_config),
        },
        case_root=tmp_path,
        model_timeout=0.01,
    )
    text = json.dumps(payload, ensure_ascii=False)

    assert payload["status"] == "ok"
    assert "office-secret-token" not in text
    assert "discord-secret-token" not in text
    assert "mcp-secret-token" not in text
    assert str(tmp_path) not in text
    assert "/Users/" not in text
    assert "/Volumes/" not in text
    assert "张三" not in text
    assert "【PERSON_001】" not in text
    assert all(set(item) <= {"id", "label", "state", "message", "action", "details"} for item in payload["components"])
