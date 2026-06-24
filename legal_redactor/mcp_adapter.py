from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from .local_config import config_value, load_json_config


def get_case_status_by_thread(discord_thread_id: str) -> dict[str, Any]:
    return _request("GET", f"/cases/by-discord-thread/{discord_thread_id}")


def bind_discord_thread_to_case(
    case_folder: str,
    discord_thread_url: str,
    source_dir: str | None = None,
) -> dict[str, Any]:
    return _request(
        "POST",
        "/cases/bind-discord-thread",
        {
            "case_folder": case_folder,
            "discord_thread_url": discord_thread_url,
            "source_dir": source_dir,
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
        return {"ok": False, "error": {"code": "missing_api_url"}}
    if not token:
        return {"ok": False, "error": {"code": "missing_api_token"}}

    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": {"code": "office_api_error", "status": exc.code, "body": body}}
    except OSError as exc:
        return {"ok": False, "error": {"code": "office_unreachable", "message": str(exc)}}


def run_stdio() -> None:
    if _run_fastmcp_stdio():
        return
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        message = _read_framed_message(stdin)
        if message is None:
            break
        response = _handle_jsonrpc(message)
        if response is not None:
            _write_framed_message(stdout, response)


def _run_fastmcp_stdio() -> bool:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        return False

    server = FastMCP("legal-redactor")

    @server.tool(name="restore_judgment_from_thread")
    def restore_judgment_from_thread_tool(discord_thread_id: str, draft_text: str) -> str:
        """Restore a drafted judgment using the Office Mac mapping bound to a Discord thread."""

        return json.dumps(
            restore_judgment_from_thread(discord_thread_id, draft_text),
            ensure_ascii=False,
        )

    @server.tool(name="get_case_status_by_thread")
    def get_case_status_by_thread_tool(discord_thread_id: str) -> str:
        """Return non-sensitive Office Mac case status for a Discord thread."""

        return json.dumps(get_case_status_by_thread(discord_thread_id), ensure_ascii=False)

    @server.tool(name="bind_discord_thread_to_case")
    def bind_discord_thread_to_case_tool(
        case_folder: str,
        discord_thread_url: str,
        source_dir: str | None = None,
    ) -> str:
        """Bind a Discord thread URL to an Office Mac case manifest."""

        return json.dumps(
            bind_discord_thread_to_case(case_folder, discord_thread_url, source_dir),
            ensure_ascii=False,
        )

    server.run()
    return True


def _handle_jsonrpc(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "legal-redactor", "version": "0.1.0"},
            }
        elif method == "notifications/initialized":
            return None
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "restore_judgment_from_thread",
                        "description": "Restore a drafted judgment using the Office Mac case mapping bound to a Discord thread.",
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
                result = {"content": [{"type": "text", "text": json.dumps(restore_judgment_from_thread(**arguments), ensure_ascii=False)}]}
            elif name == "get_case_status_by_thread":
                result = {"content": [{"type": "text", "text": json.dumps(get_case_status_by_thread(**arguments), ensure_ascii=False)}]}
            elif name == "bind_discord_thread_to_case":
                result = {"content": [{"type": "text", "text": json.dumps(bind_discord_thread_to_case(**arguments), ensure_ascii=False)}]}
            else:
                raise ValueError(f"unknown tool: {name}")
        else:
            result = {}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}


def _read_framed_message(stream) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if line == b"":
            return None
        if line in {b"\r\n", b"\n"}:
            break
        if b":" in line:
            key, value = line.decode("ascii", errors="ignore").split(":", 1)
            headers[key.lower()] = value.strip()
        elif line.strip().startswith(b"{"):
            return json.loads(line.decode("utf-8"))

    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = stream.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write_framed_message(stream, message: dict[str, Any]) -> None:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    stream.write(body)
    stream.flush()


if __name__ == "__main__":
    run_stdio()
