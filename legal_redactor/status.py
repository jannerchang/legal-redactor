from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .cases import default_case_root
from .local_config import JsonConfigDiagnostic, config_value, diagnose_json_config


EXPECTED_MLX_MODEL = "mlx-community/Qwen3.5-9B-MLX-4bit"
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
    mlx_timeout: float = 0.6,
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
    mlx = probe_mlx_server(environ=env, timeout=mlx_timeout)
    components = [
        mlx,
        probe_mlx_runtime(environ=env),
        probe_recognition_mode(mlx),
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
        "expected_model": EXPECTED_MLX_MODEL,
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


def probe_mlx_server(
    *,
    environ: Mapping[str, str] | None = None,
    host: str | None = None,
    port: int | None = None,
    expected_model: str = EXPECTED_MLX_MODEL,
    timeout: float = 0.6,
) -> StatusItem:
    env = os.environ if environ is None else environ
    host = host or env.get("LEGAL_REDACTOR_MLX_HOST", "127.0.0.1")
    try:
        port = port or int(env.get("LEGAL_REDACTOR_MLX_PORT", "18080"))
    except ValueError:
        details = {"host": host, "port": env.get("LEGAL_REDACTOR_MLX_PORT"), "expected_model": expected_model}
        return StatusItem(
            "mlx_server",
            "MLX 本地模型",
            "error",
            "LEGAL_REDACTOR_MLX_PORT 不是有效端口号。",
            "改成数字端口，例如 18080",
            details,
        )
    if not (1 <= port <= 65535):
        details = {"host": host, "port": port, "expected_model": expected_model}
        return StatusItem(
            "mlx_server",
            "MLX 本地模型",
            "error",
            "LEGAL_REDACTOR_MLX_PORT 超出有效端口范围。",
            "改成 1-65535 之间的数字端口，例如 18080",
            details,
        )
    details: dict[str, Any] = {"host": host, "port": port, "expected_model": expected_model}
    if env.get("LEGAL_REDACTOR_SKIP_MLX") == "1":
        details["reason"] = "skip_env"
        return StatusItem(
            "mlx_server",
            "MLX 本地模型",
            "skipped",
            "已设置跳过 MLX，将以规则/样本/HanLP 可用部分运行。",
            "取消 LEGAL_REDACTOR_SKIP_MLX=1 后重新运行 ./start.sh",
            details,
        )

    try:
        status_code, body = _http_get_models(host, port, timeout)
    except socket.timeout:
        details["reason"] = "timeout"
        return StatusItem("mlx_server", "MLX 本地模型", "error", "探测 /v1/models 超时。", "检查 mlx_lm.server 日志或重启 MLX", details)
    except OSError:
        listening = _safe_port_is_listening(host, port, timeout=min(timeout, 0.25))
        details["reason"] = "unreachable"
        details["port_listening"] = listening
        if listening:
            return StatusItem(
                "mlx_server",
                "MLX 本地模型",
                "error",
                "端口有服务但 /v1/models 不可用。",
                "停止占用端口的进程，或设置 LEGAL_REDACTOR_MLX_PORT",
                details,
            )
        return StatusItem("mlx_server", "MLX 本地模型", "missing", "MLX 服务未在预期端口响应。", "运行 ./start.sh 或 scripts/start_mlx9b_server.sh", details)
    except http.client.HTTPException:
        details["reason"] = "http_exception"
        return StatusItem("mlx_server", "MLX 本地模型", "error", "MLX HTTP 探测失败。", "检查端口占用和 MLX 日志", details)

    details["http_status"] = status_code
    if status_code >= 400:
        details["reason"] = "http_error"
        return StatusItem("mlx_server", "MLX 本地模型", "error", f"/v1/models 返回 HTTP {status_code}。", "检查 MLX 服务或端口占用", details)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        details["reason"] = "invalid_json"
        return StatusItem("mlx_server", "MLX 本地模型", "error", "/v1/models 未返回有效 JSON。", "确认 18080 不是其他服务", details)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        details["reason"] = "invalid_models_payload"
        return StatusItem("mlx_server", "MLX 本地模型", "error", "/v1/models 返回结构不符合模型列表格式。", "确认 18080 不是其他服务", details)

    model_ids = [
        item.get("id")
        for item in payload.get("data", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    details["model_ids"] = model_ids[:8]
    if expected_model not in model_ids:
        details["reason"] = "model_mismatch"
        return StatusItem(
            "mlx_server",
            "MLX 本地模型",
            "error",
            "端口可用，但未返回当前项目固定模型。",
            "停止错误服务，或用 scripts/start_mlx9b_server.sh 启动固定模型",
            details,
        )
    details["reason"] = "model_ready"
    return StatusItem("mlx_server", "MLX 本地模型", "ready", "固定 9B MLX 模型已就绪。", "无需处理", details)


def _mlx_start_script_path() -> Path:
    return Path(__file__).resolve().parent.parent / "scripts" / "start_mlx9b_server.sh"


def ensure_mlx_server_ready(
    *,
    environ: Mapping[str, str] | None = None,
    timeout: float = 0.6,
    start_timeout_seconds: int = 130,
) -> StatusItem:
    """Probe MLX; if missing, attempt scripts/start_mlx9b_server.sh once."""
    item = probe_mlx_server(environ=environ, timeout=timeout)
    if item.state == "ready":
        return item
    env = os.environ if environ is None else environ
    if env.get("LEGAL_REDACTOR_SKIP_MLX") == "1":
        return item
    script = _mlx_start_script_path()
    if not script.is_file():
        return item
    try:
        subprocess.run(
            ["bash", str(script)],
            check=True,
            timeout=start_timeout_seconds,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    return probe_mlx_server(environ=environ, timeout=max(timeout, 2.0))


def probe_mlx_runtime(*, environ: Mapping[str, str] | None = None, expected_model: str = EXPECTED_MLX_MODEL) -> StatusItem:
    env = os.environ if environ is None else environ
    cli_path = shutil.which("mlx_lm.server", path=env.get("PATH"))
    hf_home = Path(env.get("HF_HOME", "~/.cache/huggingface")).expanduser()
    model_cache = hf_home / "hub" / f"models--{expected_model.replace('/', '--')}"
    sidecar_count = _appledouble_count(model_cache)
    details = {
        "mlx_lm_server_available": bool(cli_path),
        "hf_home": str(hf_home),
        "model_cache": str(model_cache),
        "model_cache_exists": model_cache.exists(),
        "appledouble_count": sidecar_count,
    }
    if not cli_path:
        return StatusItem("mlx_runtime", "MLX 运行依赖", "missing", "未找到 mlx_lm.server。", "安装 mlx-lm 后再启动 MLX", details)
    if sidecar_count:
        return StatusItem("mlx_runtime", "MLX 运行依赖", "degraded", "模型缓存中存在 macOS AppleDouble 旁路文件。", "清理缓存旁路文件后再启动 MLX", details)
    if not model_cache.exists():
        return StatusItem("mlx_runtime", "MLX 运行依赖", "degraded", "尚未看到固定模型的本地缓存。", "首次启动会下载模型；建议保持 HF_HOME 在本机磁盘", details)
    return StatusItem("mlx_runtime", "MLX 运行依赖", "ready", "MLX CLI 和本地模型缓存可见。", "无需处理", details)


def probe_recognition_mode(mlx_item: StatusItem) -> StatusItem:
    if mlx_item.state == "ready":
        return StatusItem("recognition_mode", "识别模式", "ready", "LLM 辅助识别可用。", "无需处理")
    return StatusItem(
        "recognition_mode",
        "识别模式",
        "degraded",
        "当前将退回规则/样本/HanLP 可用部分，识别支持低于 MLX 模式。",
        "需要更高召回时先修复 MLX 状态",
        {"mlx_state": mlx_item.state},
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


def _http_get_models(host: str, port: int, timeout: float) -> tuple[int, str]:
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", "/v1/models")
        response = conn.getresponse()
        return response.status, response.read().decode("utf-8", errors="replace")
    finally:
        conn.close()


def _port_is_listening(host: str, port: int, *, timeout: float) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def _safe_port_is_listening(host: str, port: int, *, timeout: float) -> bool:
    try:
        return _port_is_listening(host, port, timeout=timeout)
    except OSError:
        return False


def _appledouble_count(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    for item in path.rglob("._*"):
        if item.is_file():
            count += 1
            if count >= 50:
                break
    return count


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
        return f"{key}_name", _path_display_name(value)
    if isinstance(value, str) and _looks_like_local_path(value):
        return f"{key}_name", _path_display_name(value)
    return key, _public_detail_value(value)


def _public_detail_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _public_details(value)
    if isinstance(value, (list, tuple)):
        return [_public_detail_value(item) for item in value]
    if isinstance(value, str):
        if _looks_like_local_path(value):
            return _path_display_name(value)
        if _looks_like_secret_value(value):
            return "<redacted>"
    return value


def _looks_like_local_path(value: str) -> bool:
    text = value.strip()
    return text.startswith(("/", "~")) or "/Users/" in text or "/Volumes/" in text


def _looks_like_secret_value(value: str) -> bool:
    text = value.strip().lower()
    return text.startswith("bearer ") or " secret" in text or "secret-" in text or "-secret" in text or "token" in text


def _path_display_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return Path(text).expanduser().name or "configured"
