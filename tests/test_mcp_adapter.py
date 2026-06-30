from __future__ import annotations

import io
import json
import urllib.error

from legal_redactor import mcp_adapter


def test_mcp_adapter_requires_api_url(monkeypatch) -> None:
    monkeypatch.delenv("LEGAL_REDACTOR_API_URL", raising=False)
    monkeypatch.setenv("LEGAL_REDACTOR_API_TOKEN", "token")
    monkeypatch.setattr(mcp_adapter, "load_json_config", lambda *args, **kwargs: {})

    result = mcp_adapter.restore_judgment_from_thread("3", "draft")

    assert result["ok"] is False
    assert result["error"]["code"] == "missing_api_url"
    assert result["error"]["status"] is None
    assert result["error"]["next_action"] == "configure_office_api_url"


def test_mcp_adapter_reports_office_unreachable(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_REDACTOR_API_URL", "http://office.local")
    monkeypatch.setenv("LEGAL_REDACTOR_API_TOKEN", "token")

    def fail(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(mcp_adapter.urllib.request, "urlopen", fail)

    result = mcp_adapter.restore_judgment_from_thread("3", "draft")

    assert result["ok"] is False
    assert result["error"]["code"] == "office_unreachable"
    assert "network down" not in str(result)


def test_mcp_adapter_reads_json_config(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "mcp.local.json"
    config_path.write_text(
        json.dumps({"api_url": "http://office.local", "api_token": "token"}),
        encoding="utf-8",
    )
    monkeypatch.delenv("LEGAL_REDACTOR_API_URL", raising=False)
    monkeypatch.delenv("LEGAL_REDACTOR_API_TOKEN", raising=False)
    monkeypatch.setenv("LEGAL_REDACTOR_MCP_CONFIG", str(config_path))

    def fail(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(mcp_adapter.urllib.request, "urlopen", fail)

    result = mcp_adapter.restore_judgment_from_thread("3", "draft")

    assert result["ok"] is False
    assert result["error"]["code"] == "office_unreachable"


def test_jsonrpc_lists_tools() -> None:
    response = mcp_adapter._handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    names = {tool["name"] for tool in response["result"]["tools"]}
    assert "restore_judgment_from_thread" in names
    assert "get_case_status_by_thread" in names
    assert "bind_discord_thread_to_case" in names


def test_mcp_adapter_strips_raw_http_error_body(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_REDACTOR_API_URL", "http://office.local")
    monkeypatch.setenv("LEGAL_REDACTOR_API_TOKEN", "secret-token-value")
    raw_body = json.dumps(
        {
            "detail": {
                "ok": False,
                "error": {
                    "code": "missing_map",
                    "status": 409,
                    "message": "张三 /Users/jannerchang/private secret-token-value",
                    "next_action": "upload_mapping",
                },
            }
        },
        ensure_ascii=False,
    ).encode("utf-8")

    def fail(*args, **kwargs):
        raise urllib.error.HTTPError(
            "http://office.local/cases/by-discord-thread/3",
            409,
            "Conflict",
            {},
            io.BytesIO(raw_body),
        )

    monkeypatch.setattr(mcp_adapter.urllib.request, "urlopen", fail)

    result = mcp_adapter.restore_judgment_from_thread("3", "draft")

    assert result["ok"] is False
    assert result["error"]["code"] == "office_api_error"
    assert result["error"]["status"] == 409
    assert result["error"]["next_action"] == "upload_mapping"
    assert "body" not in result["error"]
    assert "张三" not in str(result)
    assert "/Users/" not in str(result)
    assert "secret-token-value" not in str(result)


def test_jsonrpc_restore_result_omits_draft_text(monkeypatch) -> None:
    def fake_restore(discord_thread_id: str, draft_text: str) -> dict:
        return {
            "ok": True,
            "code": "restored",
            "case": {"case_folder": "case", "discord_thread_id": discord_thread_id},
            "restore": {"status": "restored", "restored_filename": "judgment.txt"},
        }

    monkeypatch.setattr(mcp_adapter, "restore_judgment_from_thread", fake_restore)
    response = mcp_adapter._handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "restore_judgment_from_thread",
                "arguments": {"discord_thread_id": "3", "draft_text": "张三 draft text"},
            },
        }
    )

    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["ok"] is True
    assert "张三 draft text" not in response["result"]["content"][0]["text"]


def test_jsonrpc_calls_bind_discord_thread_to_case(monkeypatch) -> None:
    calls = []

    def fake_bind(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "discord_thread_url": "https://discord.com/channels/1/2/3",
            "discord_thread_id": "3",
        }

    monkeypatch.setattr(mcp_adapter, "bind_discord_thread_to_case", fake_bind)
    response = mcp_adapter._handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "bind_discord_thread_to_case",
                "arguments": {
                    "case_folder": "2025 8765",
                    "discord_thread_url": "https://discord.com/channels/1/2/3",
                },
            },
        }
    )

    assert calls == [
        {
            "case_folder": "2025 8765",
            "discord_thread_url": "https://discord.com/channels/1/2/3",
        }
    ]
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["ok"] is True
    assert payload["discord_thread_url"] == "https://discord.com/channels/1/2/3"


def test_jsonrpc_initialize_advertises_tools() -> None:
    response = mcp_adapter._handle_jsonrpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"})

    assert response["result"]["serverInfo"]["name"] == "legal-redactor"
    assert "tools" in response["result"]["capabilities"]
