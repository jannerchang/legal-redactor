from __future__ import annotations

import http.client
import json
import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .cases import default_case_root
from .config import DEFAULT_MODEL_MANAGER_HOST, DEFAULT_MODEL_MANAGER_PORT
from .local_config import JsonConfigDiagnostic, config_value, diagnose_json_config
from .model_manager import DEFAULT_MODEL_ID
ALLOWED_STATES = {"ready", "degraded", "missing", "error", "skipped"}


@dataclass(frozen=True)
class StatusItem:
    id: str
    label: str
    state: str
    message: str
    action: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        if self.state not in ALLOWED_STATES:
            raise ValueError(f"unsupported status state: {self.state}")
        payload: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "state": self.state,
            "message": self.message,
            "action": self.action,
        }
        if self.details:
            payload["details"] = _public_details(self.details)
        return payload


def build_status_payload(
    *,
    environ: Mapping[str, str] | None = None,
    config_dir: str | Path | None = None,
    case_root: str | Path | None = None,
    model_timeout: float = 0.6,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    api_config = diagnose_json_config(
        "LEGAL_REDACTOR_API_CONFIG",
        "api.local.json",
        environ=env,
        config_dir=config_dir,
    )
    mcp_config = diagnose_json_config(
        "LEGAL_REDACTOR_MCP_CONFIG",
        "mcp.local.json",
        environ=env,
        config_dir=config_dir,
    )
    model_manager = probe_model_manager(environ=env, timeout=model_timeout)
    components = [
        model_manager,
        probe_recognition_mode(model_manager),
        probe_json_config("api_config", "Office/API config", api_config),
        probe_case_root(case_root if case_root is not None else env.get("LEGAL_REDACTOR_CASE_ROOT")),
        probe_office_api_config(api_config, environ=env),
        probe_mcp_config(mcp_config, environ=env),
        probe_discord_config(api_config, environ=env),
    ]
    public_components = [item.to_dict() for item in components]
    return {
        "status": "ok",
        "overall_state": _overall_state(public_components),
        "default_model_id": DEFAULT_MODEL_ID,
        "components": public_components,
    }


def probe_json_config(id: str, label: str, diagnostic: JsonConfigDiagnostic) -> StatusItem:
    details = diagnostic.public_dict()
    if diagnostic.state == "ready":
        return StatusItem(id, label, "ready", "配置文件可读取。", "无需处理", details)
    if diagnostic.state == "missing":
        return StatusItem(id, label, "missing", "未找到本地配置文件。", f"需要时复制 config/{_example_name(diagnostic.path.name)} 并填写本机配置", details)
    if diagnostic.state == "non_object":
        return StatusItem(id, label, "error", "配置文件不是 JSON object。", "改成顶层对象格式，例如 {\"api_token\":\"...\"}", details)
    return StatusItem(id, label, "error", "配置文件不是有效 JSON。", "修正 JSON 语法后重试", details)


def probe_case_root(case_root: str | Path | None = None) -> StatusItem:
    path = Path(case_root).expanduser() if case_root else default_case_root()
    details = {"path": str(path)}
    if not path.exists():
        return StatusItem(
            "case_root",
            "案件库目录",
            "missing",
            "案件库根目录尚不存在。",
            "首次归档前创建该目录，或设置 LEGAL_REDACTOR_CASE_ROOT",
            details,
        )
    if not path.is_dir():
        return StatusItem("case_root", "案件库目录", "error", "案件库路径不是目录。", "改为可写目录路径", details)
    writable = os.access(path, os.W_OK | os.X_OK)
    details["writable"] = writable
    if not writable:
        return StatusItem("case_root", "案件库目录", "error", "案件库目录不可写。", "修正目录权限后重试", details)
    return StatusItem("case_root", "案件库目录", "ready", "案件库目录存在且可写。", "无需处理", details)


def _model_manager_endpoint(environ: Mapping[str, str]) -> tuple[str, int] | None:
    host = environ.get("LEGAL_REDACTOR_MODEL_MANAGER_HOST", DEFAULT_MODEL_MANAGER_HOST).strip()
    raw_port = environ.get("LEGAL_REDACTOR_MODEL_MANAGER_PORT", str(DEFAULT_MODEL_MANAGER_PORT)).strip()
    if not host:
        return None
    try:
        port = int(raw_port)
    except ValueError:
        return None
    return (host, port) if 1 <= port <= 65535 else None


def probe_model_manager(
    *,
    environ: Mapping[str, str] | None = None,
    timeout: float = 0.6,
) -> StatusItem:
    env = os.environ if environ is None else environ
    if env.get("LEGAL_REDACTOR_SKIP_MLX") == "1":
        return StatusItem(
            "model_manager",
            "本地模型 API",
            "skipped",
            "本地模型 API 已由 LEGAL_REDACTOR_SKIP_MLX=1 跳过；将使用纯规则模式。",
            "取消该环境变量后启动本地模型 API",
            {"host": DEFAULT_MODEL_MANAGER_HOST, "port": DEFAULT_MODEL_MANAGER_PORT, "reason": "skip_requested"},
        )
    endpoint = _model_manager_endpoint(env)
    if endpoint is None:
        return StatusItem(
            "model_manager",
            "本地模型 API",
            "error",
            "本地模型 API 地址无效。",
            "设置有效的 LEGAL_REDACTOR_MODEL_MANAGER_HOST 和 PORT",
            {"reason": "invalid_endpoint"},
        )
    host, port = endpoint
    details: dict[str, Any] = {"host": host, "port": port}
    try:
        health_status, health_body = _http_get(host, port, "/health", timeout)
    except socket.timeout:
        return StatusItem("model_manager", "本地模型 API", "error", "本地模型 API 健康检查超时。", "检查模型管理器后重试", details)
    except OSError:
        return StatusItem("model_manager", "本地模型 API", "missing", "本地模型 API 未在配置地址响应。", "启动本地模型管理器", details)
    except http.client.HTTPException:
        return StatusItem("model_manager", "本地模型 API", "error", "本地模型 API 健康检查失败。", "检查模型管理器后重试", details)
    if health_status >= 400:
        details["reason"] = f"health_http_{health_status}"
        return StatusItem("model_manager", "本地模型 API", "error", f"本地模型 API /health 返回 HTTP {health_status}。", "检查模型管理器", details)
    try:
        health_payload = json.loads(health_body)
    except json.JSONDecodeError:
        return StatusItem("model_manager", "本地模型 API", "error", "本地模型 API /health 未返回有效 JSON。", "检查模型管理器", details)
    if not isinstance(health_payload, dict) or health_payload.get("status") != "ok":
        return StatusItem("model_manager", "本地模型 API", "error", "本地模型 API /health 返回结构不符合协议。", "检查模型管理器", details)
    worker_state = health_payload.get("worker_state")
    if worker_state in {"ready", "stopped", "starting", "error"}:
        details["worker_state"] = worker_state
    try:
        models_status, models_body = _http_get(host, port, "/v1/models", timeout)
    except socket.timeout:
        return StatusItem("model_manager", "本地模型 API", "error", "本地模型 API 模型列表请求超时。", "检查模型管理器后重试", details)
    except (OSError, http.client.HTTPException):
        return StatusItem("model_manager", "本地模型 API", "error", "本地模型 API 模型列表请求失败。", "检查模型管理器后重试", details)
    if models_status >= 400:
        details["reason"] = f"models_http_{models_status}"
        return StatusItem("model_manager", "本地模型 API", "error", f"本地模型 API /v1/models 返回 HTTP {models_status}。", "检查模型管理器", details)
    try:
        models_payload = json.loads(models_body)
    except json.JSONDecodeError:
        return StatusItem("model_manager", "本地模型 API", "error", "本地模型 API /v1/models 未返回有效 JSON。", "检查模型管理器", details)
    if not isinstance(models_payload, dict) or not isinstance(models_payload.get("data"), list):
        return StatusItem("model_manager", "本地模型 API", "error", "本地模型 API /v1/models 返回结构不符合模型列表格式。", "检查模型管理器", details)
    model_ids = list(dict.fromkeys(
        item["id"].strip()
        for item in models_payload["data"]
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
    ))
    details["model_ids"] = model_ids[:8]
    if not model_ids:
        details["reason"] = "no_models_registered"
        return StatusItem("model_manager", "本地模型 API", "error", "本地模型 API 当前没有可用模型。", "下载或配置至少一个 MLX 模型", details)
    return StatusItem("model_manager", "本地模型 API", "ready", f"本地模型 API 已就绪，可选 {len(model_ids)} 个模型。", "无需处理", details)


def probe_recognition_mode(model_manager_item: StatusItem) -> StatusItem:
    if model_manager_item.state == "ready":
        return StatusItem("recognition_mode", "识别模式", "ready", "LLM 辅助识别可用。", "无需处理")
    return StatusItem(
        "recognition_mode",
        "识别模式",
        "degraded",
        "当前将退回规则/HanLP 可用部分，识别支持低于 LLM 辅助模式。",
        "需要更高召回时先修复本地模型 API 状态",
        {"model_manager_state": model_manager_item.state},
    )






def probe_office_api_config(
    diagnostic: JsonConfigDiagnostic,
    *,
    environ: Mapping[str, str] | None = None,
) -> StatusItem:
    env = os.environ if environ is None else environ
    token_present = _configured_secret(env.get("LEGAL_REDACTOR_API_TOKEN") or config_value(diagnostic.value, "api_token"))
    case_root_present = bool(config_value(diagnostic.value, "case_root") or env.get("LEGAL_REDACTOR_CASE_ROOT"))
    details = {
        "config_state": diagnostic.state,
        "config_path": str(diagnostic.path),
        "api_token_present": token_present,
        "case_root_configured": case_root_present,
    }
    if diagnostic.state not in {"ready", "missing"}:
        return StatusItem("office_api", "Office 还原 API", "error", "Office API 配置文件不可用。", "先修正 api.local.json", details)
    if not token_present:
        return StatusItem("office_api", "Office 还原 API", "missing", "未配置 Office API token。", "在本机环境或 api.local.json 中配置 api_token", details)
    return StatusItem("office_api", "Office 还原 API", "ready", "还原 API 凭证存在。", "启动 remote_api 时继续使用私网地址", details)


def probe_mcp_config(
    diagnostic: JsonConfigDiagnostic,
    *,
    environ: Mapping[str, str] | None = None,
) -> StatusItem:
    env = os.environ if environ is None else environ
    url_present = bool(env.get("LEGAL_REDACTOR_API_URL") or config_value(diagnostic.value, "api_url"))
    token_present = _configured_secret(env.get("LEGAL_REDACTOR_API_TOKEN") or config_value(diagnostic.value, "api_token"))
    details = {
        "config_state": diagnostic.state,
        "config_path": str(diagnostic.path),
        "api_url_present": url_present,
        "api_token_present": token_present,
    }
    if diagnostic.state not in {"ready", "missing"}:
        return StatusItem("mcp_adapter", "Hermes MCP 配置", "error", "MCP 配置文件不可用。", "先修正 mcp.local.json", details)
    if not url_present or not token_present:
        return StatusItem("mcp_adapter", "Hermes MCP 配置", "missing", "MCP 尚未配置 Office API URL 或 token。", "填写 mcp.local.json 或设置 LEGAL_REDACTOR_API_URL/API_TOKEN", details)
    return StatusItem("mcp_adapter", "Hermes MCP 配置", "ready", "MCP 到 Office API 的本地配置存在。", "无需处理")


def probe_discord_config(
    diagnostic: JsonConfigDiagnostic,
    *,
    environ: Mapping[str, str] | None = None,
) -> StatusItem:
    env = os.environ if environ is None else environ
    token_present = _configured_secret(env.get("LEGAL_REDACTOR_DISCORD_BOT_TOKEN") or config_value(diagnostic.value, "discord_bot_token"))
    channel_present = bool(env.get("LEGAL_REDACTOR_DISCORD_COMMAND_CHANNEL_ID") or config_value(diagnostic.value, "discord_command_channel_id"))
    details = {
        "config_state": diagnostic.state,
        "config_path": str(diagnostic.path),
        "discord_bot_token_present": token_present,
        "discord_command_channel_id_present": channel_present,
    }
    if diagnostic.state not in {"ready", "missing"}:
        return StatusItem("discord", "Discord 指令通道", "error", "Discord 所在配置文件不可用。", "先修正 api.local.json", details)
    if not token_present or not channel_present:
        return StatusItem("discord", "Discord 指令通道", "missing", "Discord bot token 或指令频道未配置。", "需要自动发帖时填写 token 和 command channel id", details)
    return StatusItem("discord", "Discord 指令通道", "ready", "Discord 指令通道配置存在。", "无需处理")


def _http_get(host: str, port: int, path: str, timeout: float) -> tuple[int, str]:
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read().decode("utf-8", errors="replace")
    finally:
        connection.close()




def _configured_secret(value: str | None) -> bool:
    if not value:
        return False
    return not str(value).startswith(("optional-", "replace-with"))


def _example_name(filename: str) -> str:
    if filename == "api.local.json":
        return "api.example.json"
    if filename == "mcp.local.json":
        return "mcp.example.json"
    return filename


def _overall_state(components: list[dict[str, Any]]) -> str:
    states = [item.get("state") for item in components]
    if "error" in states:
        return "error"
    if any(state in {"degraded", "missing", "skipped"} for state in states):
        return "degraded"
    return "ready"


def _public_details(details: dict[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {}
    for key, value in details.items():
        public_key, public_value = _public_detail_entry(key, value)
        if public_key is None:
            continue
        public[public_key] = public_value
    return public


def _public_detail_entry(key: str, value: Any) -> tuple[str | None, Any]:
    lower = key.lower()
    blocked = {"token", "secret", "authorization", "original_text", "restored_text", "redaction_map", "sample"}
    path_like_keys = {"path", "config_path", "hf_home", "model_cache"}
    if any(word in lower for word in blocked) and not lower.endswith("_present"):
        return None, None
    if lower in path_like_keys:
        return f"{key}_configured", _path_configured_value(value)
    if isinstance(value, str) and _looks_like_local_path(value):
        return f"{key}_configured", _path_configured_value(value)
    return key, _public_detail_value(value)


def _public_detail_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _public_details(value)
    if isinstance(value, (list, tuple)):
        return [_public_detail_value(item) for item in value]
    if isinstance(value, str):
        if _looks_like_local_path(value):
            return _path_configured_value(value)
        if _looks_like_secret_value(value):
            return "<redacted>"
    return value


def _looks_like_local_path(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    # POSIX absolute / home, and common host-sensitive prefixes.
    if text.startswith(("/", "~")) or "/Users/" in text or "/Volumes/" in text:
        return True
    # Windows drive absolute: C:\path or C:/path (mixed separators included).
    if len(text) >= 3 and text[0].isalpha() and text[1] == ":" and text[2] in "\\/":
        return True
    # UNC: \\server\share ... and //server/share ...
    if text.startswith("\\\\"):
        return True
    if text.startswith("//") and len(text) > 2 and text[2] not in "/\\":
        return True
    return False


def _looks_like_secret_value(value: str) -> bool:
    text = value.strip().lower()
    return text.startswith("bearer ") or " secret" in text or "secret-" in text or "-secret" in text or "token" in text


def _path_configured_value(value: Any) -> str:
    return "configured" if str(value or "").strip() else ""
