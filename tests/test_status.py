from __future__ import annotations

import json
import socket

from legal_redactor.local_config import diagnose_json_config, load_json_config
from legal_redactor.status import (
    EXPECTED_MLX_MODEL,
    StatusItem,
    build_status_payload,
    probe_case_root,
    probe_mlx_runtime,
    probe_mlx_server,
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
        "mlx_server",
        "MLX",
        "ready",
        "ok",
        "none",
        {
            "model_ids": [
                EXPECTED_MLX_MODEL,
                "/Users/jannerchang/private-model",
                {"path": "/Volumes/cases/model.bin", "note": "Bearer secret-token-value"},
            ],
            "nested": {"config_path": "/Users/jannerchang/config/api.local.json"},
        },
    ).to_dict()

    text = json.dumps(item, ensure_ascii=False)
    assert EXPECTED_MLX_MODEL in text
    assert "/Users/" not in text
    assert "/Volumes/" not in text
    assert "secret-token-value" not in text
    assert "private-model" in text
    assert "model.bin" in text
    assert "api.local.json" in text


def test_json_config_diagnostics_preserve_legacy_safe_default(tmp_path, monkeypatch) -> None:
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


def test_mlx_probe_requires_expected_model(monkeypatch) -> None:
    monkeypatch.setattr(
        "legal_redactor.status._http_get_models",
        lambda host, port, timeout: (200, json.dumps({"data": [{"id": "other-model"}]})),
    )

    item = probe_mlx_server(environ={}, timeout=0.01)

    assert item.state == "error"
    assert item.details["reason"] == "model_mismatch"

    monkeypatch.setattr(
        "legal_redactor.status._http_get_models",
        lambda host, port, timeout: (
            200,
            json.dumps({"data": [{"id": EXPECTED_MLX_MODEL}, {"id": "/Users/jannerchang/private-model"}]}),
        ),
    )

    ready = probe_mlx_server(environ={}, timeout=0.01)
    assert ready.state == "ready"
    text = json.dumps(ready.to_dict(), ensure_ascii=False)
    assert "/Users/" not in text
    assert "private-model" in text


def test_mlx_probe_classifies_http_invalid_json_timeout_and_unreachable(monkeypatch) -> None:
    monkeypatch.setattr("legal_redactor.status._http_get_models", lambda host, port, timeout: (503, "{}"))
    assert probe_mlx_server(environ={}, timeout=0.01).details["reason"] == "http_error"

    monkeypatch.setattr("legal_redactor.status._http_get_models", lambda host, port, timeout: (200, "not-json"))
    assert probe_mlx_server(environ={}, timeout=0.01).details["reason"] == "invalid_json"

    monkeypatch.setattr("legal_redactor.status._http_get_models", lambda host, port, timeout: (200, "[]"))
    assert probe_mlx_server(environ={}, timeout=0.01).details["reason"] == "invalid_models_payload"

    monkeypatch.setattr("legal_redactor.status._http_get_models", lambda host, port, timeout: (200, '{"data": {}}'))
    assert probe_mlx_server(environ={}, timeout=0.01).details["reason"] == "invalid_models_payload"

    def raise_timeout(host: str, port: int, timeout: float) -> tuple[int, str]:
        raise socket.timeout()

    monkeypatch.setattr("legal_redactor.status._http_get_models", raise_timeout)
    assert probe_mlx_server(environ={}, timeout=0.01).details["reason"] == "timeout"

    def raise_oserror(host: str, port: int, timeout: float) -> tuple[int, str]:
        raise OSError("connection refused")

    monkeypatch.setattr("legal_redactor.status._http_get_models", raise_oserror)
    monkeypatch.setattr("legal_redactor.status._safe_port_is_listening", lambda host, port, timeout: False)
    unreachable = probe_mlx_server(environ={}, timeout=0.01)
    assert unreachable.state == "missing"
    assert unreachable.details["reason"] == "unreachable"


def test_mlx_probe_rejects_out_of_range_port_without_network_call(monkeypatch) -> None:
    called = False

    def fake_http_get(host: str, port: int, timeout: float) -> tuple[int, str]:
        nonlocal called
        called = True
        return 200, "{}"

    monkeypatch.setattr("legal_redactor.status._http_get_models", fake_http_get)

    item = probe_mlx_server(environ={"LEGAL_REDACTOR_MLX_PORT": "70000"}, timeout=0.01)

    assert item.state == "error"
    assert item.details["port"] == 70000
    assert called is False


def test_mlx_skip_reports_degraded_recognition_mode() -> None:
    mlx = probe_mlx_server(environ={"LEGAL_REDACTOR_SKIP_MLX": "1"}, timeout=0.01)
    fallback = probe_recognition_mode(mlx)

    assert mlx.state == "skipped"
    assert fallback.state == "degraded"
    assert "低于 MLX" in fallback.message


def test_mlx_runtime_reports_cache_sidecars_without_deleting(tmp_path, monkeypatch) -> None:
    model_cache = tmp_path / "hub" / f"models--{EXPECTED_MLX_MODEL.replace('/', '--')}"
    model_cache.mkdir(parents=True)
    sidecar = model_cache / "._main"
    sidecar.write_text("sidecar", encoding="utf-8")
    monkeypatch.setattr("legal_redactor.status.shutil.which", lambda name, path=None: "/usr/local/bin/mlx_lm.server")

    item = probe_mlx_runtime(environ={"HF_HOME": str(tmp_path)})

    assert item.state == "degraded"
    assert item.details["appledouble_count"] == 1
    assert sidecar.exists()


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
    monkeypatch.setattr("legal_redactor.status.shutil.which", lambda name, path=None: None)

    payload = build_status_payload(
        environ={
            "LEGAL_REDACTOR_API_CONFIG": str(api_config),
            "LEGAL_REDACTOR_MCP_CONFIG": str(mcp_config),
            "LEGAL_REDACTOR_SKIP_MLX": "1",
            "HF_HOME": str(tmp_path / "hf"),
        },
        case_root=tmp_path,
        mlx_timeout=0.01,
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
