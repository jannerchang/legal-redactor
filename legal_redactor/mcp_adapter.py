from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from .cases import assert_remote_payload_safe
from .local_config import config_value, load_json_config


def get_case_status_by_thread(discord_thread_id: str) -> dict[str, Any]:
    return _request("GET", f"/cases/by-discord-thread/{discord_thread_id}")


def bind_discord_thread_to_case(
    case_folder: str,
    discord_thread_url: str,
    source_dir: str | None = None,
    case_root: str | None = None,
) -> dict[str, Any]:
    return _request(
        "POST",
        "/cases/bind-discord-thread",
        {
            "case_folder": case_folder,
            "discord_thread_url": discord_thread_url,
            "source_dir": source_dir,
            "case_root": case_root,
        },
    )


def restore_judgment_from_thread(discord_thread_id: str, draft_text: str) -> dict[str, Any]:
    return _request(
        "POST",
        f"/cases/by-discord-thread/{discord_thread_id}/restore-text",
        {"draft_text": draft_text},
    )


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_json_config("LEGAL_REDACTOR_MCP_CONFIG", "mcp.local.json")
    raw_base_url = os.environ.get("LEGAL_REDACTOR_API_URL") or config_value(config, "api_url") or ""
    base_url = raw_base_url.rstrip("/")
    token = os.environ.get("LEGAL_REDACTOR_API_TOKEN") or config_value(config, "api_token")
    if not base_url:
        return _safe_error("missing_api_url", None, "Office API URL is not configured", "configure_office_api_url")
    if not token:
        return _safe_error("missing_api_token", None, "Office API token is not configured", "configure_office_api_token")

    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return _safe_success_result(json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        office_error = _parse_office_error(body)
        return _safe_error(
            "office_api_error",
            exc.code,
            "Office API returned an error",
            office_error.get("next_action") or "check_office_api",
        )
    except OSError:
        return _safe_error("office_unreachable", None, "Office API is unreachable", "start_office_api")


def run_stdio() -> None:
    """Serve MCP JSON-RPC messages over the Gateway's newline-delimited stdio transport."""

    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        message = _read_json_line(stdin)
        if message is None:
            return
        response = _handle_jsonrpc(message)
        if response is not None:
            _write_json_line(stdout, response)


def _handle_jsonrpc(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "legal-redactor", "version": "0.2.0"},
            }
        elif method == "notifications/initialized":
            return None
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "restore_judgment_from_thread",
                        "description": "Restore an authorized legal-document draft using the local matter mapping bound to a collaboration thread.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "discord_thread_id": {"type": "string"},
                                "draft_text": {"type": "string"},
                            },
                            "required": ["discord_thread_id", "draft_text"],
                        },
                    },
                    {
                        "name": "get_case_status_by_thread",
                        "description": "Return non-sensitive Office Mac case status for a Discord thread.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"discord_thread_id": {"type": "string"}},
                            "required": ["discord_thread_id"],
                        },
                    },
                    {
                        "name": "bind_discord_thread_to_case",
                        "description": "Bind a Discord thread URL to an Office Mac case manifest.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "case_folder": {"type": "string"},
                                "discord_thread_url": {"type": "string"},
                                "source_dir": {"type": "string"},
                                "case_root": {"type": "string"},
                            },
                            "required": ["case_folder", "discord_thread_url"],
                        },
                    },
                ]
            }
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if name == "restore_judgment_from_thread":
                result = {"content": [{"type": "text", "text": _safe_json_text(restore_judgment_from_thread(**arguments))}]}
            elif name == "get_case_status_by_thread":
                result = {"content": [{"type": "text", "text": _safe_json_text(get_case_status_by_thread(**arguments))}]}
            elif name == "bind_discord_thread_to_case":
                result = {"content": [{"type": "text", "text": _safe_json_text(bind_discord_thread_to_case(**arguments))}]}
            else:
                raise ValueError(f"unknown tool: {name}")
        else:
            result = {}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": "Adapter error"}}


def _read_json_line(stream) -> dict[str, Any] | None:
    while True:
        line = stream.readline()
        if line == b"":
            return None
        if line.strip():
            return json.loads(line.decode("utf-8"))


def _write_json_line(stream, message: dict[str, Any]) -> None:
    stream.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
    stream.flush()


def _safe_error(code: str, status: int | None, message: str, next_action: str) -> dict[str, Any]:
    payload = {
        "ok": False,
        "error": {
            "code": code,
            "status": status,
            "message": message,
            "next_action": next_action,
        },
    }
    assert_remote_payload_safe(payload)
    return payload


def _safe_success_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _safe_error("office_api_error", None, "Office API returned invalid JSON", "check_office_api")
    try:
        assert_remote_payload_safe(payload)
    except ValueError:
        return _safe_error("office_api_error", None, "Unsafe Office API response was blocked", "check_office_api")
    return payload


def _safe_json_text(payload: dict[str, Any]) -> str:
    safe_payload = _safe_success_result(payload) if payload.get("ok") is True else payload
    try:
        assert_remote_payload_safe(safe_payload)
    except ValueError:
        safe_payload = _safe_error("office_api_error", None, "Unsafe MCP response was blocked", "check_office_api")
    return json.dumps(safe_payload, ensure_ascii=False)


def _parse_office_error(body: str) -> dict[str, Any]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {}
    detail = data.get("detail") if isinstance(data, dict) else None
    if isinstance(detail, dict):
        error = detail.get("error")
        if isinstance(error, dict):
            return error
        return detail
    return {}


if __name__ == "__main__":
    run_stdio()
