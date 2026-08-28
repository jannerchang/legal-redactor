"""FastAPI application assembly for the local legal redactor Web UI."""
from __future__ import annotations

try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse  # noqa: F401
except ImportError as exc:
    raise RuntimeError("启动 Web UI 需要先安装依赖：pip install -r requirements.txt") from exc

from . import case_location as _case_location
from . import discord_ops as _discord_ops
from . import mapping_ops as _mapping_ops
from . import redact_routes as _redact_routes
from . import restore_ops as _restore_ops
from . import samples_ops as _samples_ops
from . import status_ops as _status_ops

app = FastAPI(title="本地法律文书脱敏系统", version="0.2.2")

_MODULE = {
    "status_ops": _status_ops,
    "case_location": _case_location,
    "discord_ops": _discord_ops,
    "mapping_ops": _mapping_ops,
    "redact_routes": _redact_routes,
    "samples_ops": _samples_ops,
    "restore_ops": _restore_ops,
}


def register_routes(application: FastAPI | None = None) -> FastAPI:
    """Attach HTTP routes and return the application instance."""
    application = application or app

    application.add_api_route("/health", _MODULE["status_ops"].health, methods=["GET"])
    application.add_api_route("/api/status", _MODULE["status_ops"].api_status, methods=["GET"])
    application.add_api_route("/api/models", _MODULE["status_ops"].api_models, methods=["GET"])
    application.add_api_route("/api/model-status", _MODULE["status_ops"].api_model_status, methods=["GET"])
    application.add_api_route("/api/suggest-case-location", _MODULE["case_location"].suggest_case_location, methods=["POST"])
    application.add_api_route("/api/discord/send-redacted", _MODULE["discord_ops"].send_redacted_to_discord, methods=["POST"])
    application.add_api_route("/api/discord/create-thread", _MODULE["discord_ops"].create_discord_thread, methods=["POST"])
    application.add_api_route("/api/discord/bind-thread", _MODULE["discord_ops"].bind_discord_thread, methods=["POST"])
    application.add_api_route("/api/discord/attach-bound-thread", _MODULE["discord_ops"].attach_to_bound_discord_thread, methods=["POST"])
    application.add_api_route("/api/mapping/suggest-entry", _MODULE["mapping_ops"].suggest_mapping_entry, methods=["POST"])
    application.add_api_route("/", _MODULE["redact_routes"].index, methods=["GET"], response_class=HTMLResponse)
    application.add_api_route("/analyze", _MODULE["redact_routes"].analyze_page, methods=["POST"], response_class=HTMLResponse)
    application.add_api_route("/redact/confirmed", _MODULE["redact_routes"].redact_confirmed_page, methods=["POST"], response_class=HTMLResponse)
    application.add_api_route("/redact", _MODULE["redact_routes"].redact_page, methods=["POST"], response_class=HTMLResponse)
    application.add_api_route("/redact/apply-map", _MODULE["redact_routes"].apply_map_page, methods=["POST"], response_class=HTMLResponse)
    application.add_api_route("/redact/apply-edited-map", _MODULE["redact_routes"].apply_edited_map_page, methods=["POST"], response_class=HTMLResponse)
    application.add_api_route("/redact/save-sample", _MODULE["samples_ops"].save_sample_page, methods=["POST"], response_class=HTMLResponse)
    application.add_api_route("/samples/edit", _MODULE["samples_ops"].edit_samples_page, methods=["GET"], response_class=HTMLResponse)
    application.add_api_route("/samples/update/{idx}", _MODULE["samples_ops"].update_sample_entry, methods=["POST"])
    application.add_api_route("/samples/add", _MODULE["samples_ops"].add_sample_entry, methods=["POST"])
    application.add_api_route("/samples/delete/{idx}", _MODULE["samples_ops"].delete_sample_entry, methods=["GET"], response_class=HTMLResponse)
    application.add_api_route("/samples/compact", _MODULE["samples_ops"].compact_samples_page, methods=["GET"], response_class=HTMLResponse)
    application.add_api_route("/samples/clear", _MODULE["samples_ops"].clear_samples_page, methods=["GET"], response_class=HTMLResponse)
    application.add_api_route("/api/samples/clear", _MODULE["samples_ops"].api_clear_samples, methods=["POST"])
    application.add_api_route("/restore/preview", _MODULE["restore_ops"].restore_preview_page, methods=["POST"], response_class=HTMLResponse)
    return application


register_routes(app)
