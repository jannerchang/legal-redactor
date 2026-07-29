from __future__ import annotations

import asyncio
import http.client
import html
import json
import os
import re
import secrets
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import base64
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import BadZipFile

from . import deps
from .deps import (
    CN_ORDINALS,
    DEFAULT_MODEL_ID,
    EXCEL_INPUT_SUFFIXES,
    ExcelFormulaLeakError,
    File,
    Form,
    HTMLResponse,
    JSONResponse,
    MappingEntry,
    PipelineConfig,
    RecognitionRunStats,
    RedactedDocument,
    RedactionMap,
    Request,
    TypeCounters,
    UploadFile,
    XLSX_MEDIA_TYPE,
    _filter_noise_entity_mappings,
    _page,
    derived_organization_alias_cores,
    extract_workbook_text,
    is_noise_entity_text,
    preview_restore,
    redact_workbook,
    redaction_map_from_json,
    redaction_map_to_json,
    render_batch_redaction_result_page,
    render_home_page,
    render_redaction_result_page,
    render_status_panel,
    restore_docx,
    sort_mapping_entries,
    MAPPING_REVIEW_CATEGORY_LABELS,
    RESTORE_RISK_REASON_LABELS,
)

from ..cases import (
    CaseError,
    InvalidDiscordThreadError,
    InvalidWorkflowInputError,
    case_dir,
    create_or_update_manifest,
    case_root_from_source_dir,
    case_workflow_public,
    case_workflow_state,
    default_case_root,
    load_manifest,
    manifest_fields_for_case_dir,
    parse_discord_thread_id,
    persist_case_redaction,
    raise_for_forged_workflow_fields,
    record_hermes_thread_request,
    suggest_case_location_from_filenames,
    case_location_search_roots,
    case_thread_binding_status,
    validate_case_folder_name,
    workflow_state_message,
)


from .models import DiscordApiError
from .workflow import (
    _case_error_response,
    _reject_forged_workflow_fields,
    _safe_public_error_message,
    _waiting_hermes_response,
)


async def send_redacted_to_discord(request: Request) -> JSONResponse:
    body = await request.json()
    invalid = _reject_forged_workflow_fields(body)
    if invalid is not None:
        return invalid
    thread_url = str(body.get("discord_thread_url", "")).strip()
    filename = Path(str(body.get("filename", "redacted.txt"))).name or "redacted.txt"
    content = str(body.get("content", ""))
    if not thread_url:
        return _case_error_response("缺少 Discord 帖子链接")
    if not content:
        return _case_error_response("没有可发送的脱敏内容")
    try:
        thread_id = parse_discord_thread_id(thread_url)
    except InvalidDiscordThreadError as exc:
        return _case_error_response(str(exc), code=exc.code)
    try:
        result = _post_discord_thread_file(
            thread_id,
            filename,
            content,
            _safe_discord_attachment_message(filename, str(body.get("message", ""))),
        )
    except DiscordApiError as exc:
        return _case_error_response(str(exc), code=exc.code)
    except RuntimeError as exc:
        return _case_error_response(str(exc))
    return JSONResponse({"status": "success", "workflow_state": "sent_discord", **result})



async def create_discord_thread(request: Request) -> JSONResponse:
    body = await request.json()
    invalid = _reject_forged_workflow_fields(body)
    if invalid is not None:
        return invalid
    case_folder = str(body.get("case_folder", "")).strip()
    case_cause = str(body.get("case_cause", "")).strip()
    if not case_folder:
        return _case_error_response("缺少案件文件夹名")
    source_dir = str(body.get("source_dir", "")).strip() or None
    try:
        source_root = case_root_from_source_dir(source_dir, case_folder) if source_dir else None
        case_root = str(source_root or str(body.get("case_root", "")).strip() or default_case_root())
        case_path = case_dir(case_root, case_folder)
        manifest = load_manifest(case_path) if (case_path / "manifest.json").exists() else None
    except CaseError as exc:
        return _case_error_response(str(exc), code=getattr(exc, "code", "case_error"))
    except Exception as exc:
        return _case_error_response(f"案件 manifest 读取失败: {exc}")
    if manifest and manifest.discord_thread_url:
        return JSONResponse(
            {
                "status": "bound",
                "workflow_state": "bound_thread",
                "thread_url": manifest.discord_thread_url,
                "thread_id": manifest.discord_thread_id,
                "message": "案件已绑定 Discord 帖子",
            }
        )
    if manifest and manifest.hermes_request_id:
        try:
            recovered_thread_url = _find_discord_thread_for_case(case_folder, case_cause)
            if recovered_thread_url:
                manifest = create_or_update_manifest(
                    case_root,
                    case_folder,
                    recovered_thread_url,
                    source_dir=source_dir,
                )
                return JSONResponse(
                    {
                        "status": "bound",
                        "workflow_state": "bound_thread",
                        "thread_url": manifest.discord_thread_url,
                        "thread_id": manifest.discord_thread_id,
                        "message": "已从 Discord 找到 Hermes 创建的帖子并完成绑定",
                    }
                )
        except (DiscordApiError, RuntimeError):
            pass
        return JSONResponse(
            {
                "status": "pending",
                "workflow_state": "waiting_hermes",
                "request_id": manifest.hermes_request_id,
                "command_message_id": manifest.hermes_command_message_id,
                "channel_id": manifest.hermes_command_channel_id,
                "message": "已有 Hermes 建帖请求，继续等待写回帖子链接",
            }
        )
    request_id = str(body.get("request_id") or _new_discord_request_id())
    try:
        command = _case_creation_command(
            case_folder,
            request_id,
            case_cause,
        )
        result = _post_discord_channel_message(_discord_command_channel_id(), command)
        manifest = record_hermes_thread_request(
            case_root,
            case_folder,
            request_id,
            source_dir=source_dir,
            command_message_id=result.get("message_id", ""),
            command_channel_id=result.get("channel_id", ""),
        )
    except CaseError as exc:
        return _case_error_response(str(exc), code=getattr(exc, "code", "case_error"))
    except DiscordApiError as exc:
        return _case_error_response(str(exc), code=exc.code)
    except RuntimeError as exc:
        return _case_error_response(str(exc))
    return JSONResponse({
        "status": "pending",
        "workflow_state": "waiting_hermes",
        "request_id": manifest.hermes_request_id or request_id,
        "command_message_id": manifest.hermes_command_message_id or result.get("message_id", ""),
        "channel_id": manifest.hermes_command_channel_id or result.get("channel_id", ""),
        "message": "已发送建帖请求，等待 Hermes 通过 MCP 写回帖子链接",
    })



async def attach_to_bound_discord_thread(request: Request) -> JSONResponse:
    body = await request.json()
    invalid = _reject_forged_workflow_fields(body)
    if invalid is not None:
        return invalid
    case_folder = str(body.get("case_folder", "")).strip()
    source_dir = str(body.get("source_dir", "")).strip() or None
    case_cause = str(body.get("case_cause", "")).strip()
    source_root = case_root_from_source_dir(source_dir, case_folder) if case_folder else None
    case_root = str(source_root or str(body.get("case_root", "")).strip() or default_case_root())
    filename = Path(str(body.get("filename", "redacted.txt"))).name or "redacted.txt"
    content = str(body.get("content", ""))
    map_json = str(body.get("map_json", ""))
    if not case_folder:
        return _case_error_response("缺少案件文件夹名")
    if not content:
        return _case_error_response("没有可发送的脱敏内容")
    try:
        case_path = case_dir(case_root, case_folder)
    except CaseError as exc:
        return _case_error_response(str(exc), code=getattr(exc, "code", "case_error"))
    try:
        manifest = load_manifest(case_path)
    except FileNotFoundError:
        return _waiting_hermes_response()
    except Exception as exc:
        return _case_error_response(f"案件 manifest 读取失败: {exc}")
    if not manifest.discord_thread_url and manifest.hermes_request_id:
        try:
            recovered_thread_url = _find_discord_thread_for_case(case_folder, case_cause)
            if recovered_thread_url:
                manifest = create_or_update_manifest(
                    case_root,
                    case_folder,
                    recovered_thread_url,
                    source_dir=source_dir,
                )
        except (DiscordApiError, RuntimeError):
            pass
    if not manifest.discord_thread_url:
        return _waiting_hermes_response()
    try:
        redaction_map = redaction_map_from_json(map_json)
    except Exception as exc:
        return _case_error_response(f"映射表解析失败: {exc}")
    try:
        thread_id = parse_discord_thread_id(manifest.discord_thread_url)
        result = _post_discord_thread_file(
            thread_id,
            filename=filename,
            content=content,
            message=_safe_discord_attachment_message(filename, str(body.get("message", ""))),
        )
        persist_case_redaction(
            case_root,
            case_folder,
            manifest.discord_thread_url,
            [RedactedDocument(source_file=filename, original_text="", redacted_text=content)],
            redaction_map,
            source_dir=source_dir,
        )
    except DiscordApiError as exc:
        return _case_error_response(str(exc), code=exc.code)
    except (CaseError, InvalidDiscordThreadError, RuntimeError) as exc:
        return _case_error_response(str(exc), code=getattr(exc, "code", "case_error"))
    return JSONResponse({
        "status": "success",
        "workflow_state": "sent_discord",
        "thread_url": manifest.discord_thread_url,
        "thread_id": thread_id,
        "case_folder": case_folder,
        **result,
    })



def _discord_create_thread_section(
    *,
    discord_thread_url: str,
    case_root: str,
    case_folder: str,
    source_dir: str,
    filename: str,
    textarea_id: str,
    map_textarea_id: str,
    message_id: str,
) -> str:
    if discord_thread_url.strip() or not case_folder.strip():
        return ""
    status_id = f"{message_id}-status"
    link_id = f"{message_id}-link"
    cause_id = f"{message_id}-case-cause"
    return (
        f'<section class="local-save-section" style="border-left: 4px solid #5865f2; background: linear-gradient(135deg, var(--surface) 0%, rgba(88, 101, 242, 0.04) 100%); padding: 18px 24px; border-radius: var(--radius); border: 1px solid var(--border); margin-bottom: 18px; box-shadow: var(--shadow);">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:15px;">'
        f'<div style="flex:1;min-width:280px;">'
        f'<h3 style="margin:0 0 8px 0;font-size:14px;font-weight:600;color:var(--ink);">请求 Hermes 新建案件帖</h3>'
        f'<p class="hint" style="margin:0;">向 Discord 指令频道发送建帖请求；Hermes 建帖后通过 MCP 写回链接，系统随后发送脱敏附件并写入本地案件库：{html.escape(case_folder)}</p>'
        f'<textarea id="{html.escape(message_id, quote=True)}" rows="2" placeholder="建帖后发送附件时附言" style="margin-top:10px;max-width:680px;">脱敏文件已生成，请见附件。</textarea>'
        f'</div>'
        f'<div style="display:flex;flex-direction:column;gap:8px;align-items:flex-start;min-width:220px;">'
        f'<button type="button" class="btn discord-create-thread-button" '
        f'data-case-root="{html.escape(case_root, quote=True)}" '
        f'data-case-folder="{html.escape(case_folder, quote=True)}" '
        f'data-source-dir="{html.escape(source_dir, quote=True)}" '
        f'data-filename="{html.escape(filename, quote=True)}" '
        f'data-textarea-id="{html.escape(textarea_id, quote=True)}" '
        f'data-map-textarea-id="{html.escape(map_textarea_id, quote=True)}" '
        f'data-message-id="{html.escape(message_id, quote=True)}" '
        f'data-status-id="{html.escape(status_id, quote=True)}" '
        f'data-case-cause-id="{html.escape(cause_id, quote=True)}" '
        f'data-link-id="{html.escape(link_id, quote=True)}">'
        f'请求 Hermes 建帖并绑定</button>'
        f'<input type="text" id="{html.escape(cause_id, quote=True)}" placeholder="案由（目录只有案号时填写）" style="width:100%;max-width:260px;">'
        f'<span id="{html.escape(status_id, quote=True)}" class="hint"></span>'
        f'<a id="{html.escape(link_id, quote=True)}" href="#" target="_blank" style="display:none;font-size:12px;">打开 Discord 帖子</a>'
        f'</div></div></section>'
    )



def _discord_send_section(discord_thread_url: str, filename: str, textarea_id: str, message_id: str) -> str:
    thread_url = discord_thread_url.strip()
    if not thread_url:
        return ""
    default_message = "脱敏文件已生成，请见附件。"
    status_id = f"{message_id}-status"
    return (
        f'<section class="local-save-section" style="border-left: 4px solid #5865f2; background: linear-gradient(135deg, var(--surface) 0%, rgba(88, 101, 242, 0.04) 100%); padding: 18px 24px; border-radius: var(--radius); border: 1px solid var(--border); margin-bottom: 18px; box-shadow: var(--shadow);">'
        f'<div style="display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 14px;">'
        f'<div style="flex: 1; min-width: 280px;">'
        f'<h3 style="margin: 0 0 8px 0; font-size: 14px; font-weight: 600; color: var(--ink);">发送到 Discord 帖子</h3>'
        f'<p class="hint" style="margin: 0 0 8px 0;">只发送脱敏文本附件，不发送映射表。</p>'
        f'<textarea id="{html.escape(message_id, quote=True)}" rows="3" style="width: 100%; min-height: 70px; resize: vertical;">{html.escape(default_message)}</textarea>'
        f'</div>'
        f'<div style="display: flex; align-items: flex-start; justify-content: flex-end; flex-direction: column; gap: 8px; min-height: 120px;">'
        f'<button type="button" class="btn discord-send-button" '
        f'data-thread-url="{html.escape(thread_url, quote=True)}" '
        f'data-filename="{html.escape(filename, quote=True)}" '
        f'data-textarea-id="{html.escape(textarea_id, quote=True)}" '
        f'data-message-id="{html.escape(message_id, quote=True)}" '
        f'data-status-id="{html.escape(status_id, quote=True)}">'
        f'一键发送到 Discord</button>'
        f'<span id="{html.escape(status_id, quote=True)}" class="hint" style="min-height: 18px;"></span>'
        f'</div></div></section>'
    )



def _discord_bot_token(config: dict | None = None) -> str:
    config = config if config is not None else deps.load_json_config("LEGAL_REDACTOR_API_CONFIG", "api.local.json")
    token = os.environ.get("LEGAL_REDACTOR_DISCORD_BOT_TOKEN") or deps.config_value(config, "discord_bot_token")
    if not token or token.startswith("optional-"):
        raise RuntimeError("未配置 Discord bot token")
    return str(token)



def _new_discord_request_id() -> str:
    return f"lr_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"



def _case_creation_command(
    case_folder: str,
    request_id: str,
    case_cause: str = "",
    *,
    case_root: str = "",
    source_dir: str = "",
) -> str:
    _ = case_root, source_dir
    folder = validate_case_folder_name(case_folder)
    lines = [
        f"新建案件，{_case_creation_title(folder, case_cause)}",
        f"请求ID：{_safe_discord_request_id(request_id)}",
        f"案件目录：{folder}",
    ]
    return "\n".join(lines)



def _safe_discord_request_id(request_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.:-]+", "_", request_id.strip())[:80]
    return value or _new_discord_request_id()



def _case_creation_title(case_folder: str, case_cause: str = "") -> str:
    value = case_folder.strip()
    cause = _clean_case_cause(case_cause)
    paren_match = re.match(r"^[（(]\s*(\d{4})\s*[）)]\s*(\d{1,8})(?:\s*号)?\s*(.*)$", value)
    space_match = re.match(r"^(\d{4})\s+(\d{1,8})(?:\s*号)?\s*(.*)$", value)
    match = paren_match or space_match
    if not match:
        return f"{value} {cause}" if cause else value
    year, number, tail = match.groups()
    normalized = f"（{year}）{number}"
    tail = tail.strip() or cause
    return f"{normalized} {tail}" if tail else normalized



def _clean_case_cause(case_cause: str) -> str:
    value = re.sub(r"\s+", " ", case_cause).strip()
    value = re.sub(r"^案由\s*[:：]\s*", "", value)
    if _contains_local_path_text(value):
        return ""
    return value[:80]



def _find_discord_thread_for_case(case_folder: str, case_cause: str = "") -> str:
    config = deps.load_json_config("LEGAL_REDACTOR_API_CONFIG", "api.local.json")
    token = _discord_bot_token(config)
    channel_id = _discord_command_channel_id()
    guild_id = str(
        os.environ.get("LEGAL_REDACTOR_DISCORD_GUILD_ID")
        or deps.config_value(config, "discord_guild_id")
        or ""
    ).strip()
    if not guild_id:
        channel = _get_discord_json(f"/channels/{channel_id}", token)
        guild_id = str(channel.get("guild_id", "")).strip()
    if not guild_id:
        raise DiscordApiError("Discord 指令频道缺少服务器 id")

    payload = _get_discord_json(f"/guilds/{guild_id}/threads/active", token)
    threads = payload.get("threads", []) if isinstance(payload, dict) else []
    expected_title = _case_creation_title(case_folder, case_cause)
    year_number = re.match(r"^（(\d{4})）(\d{1,8})", expected_title)
    case_tokens = [expected_title]
    if year_number:
        year, number = year_number.groups()
        case_tokens.extend((f"（{year}）{number}号", f"{year} {number}"))
    matches = []
    for thread in threads if isinstance(threads, list) else []:
        if not isinstance(thread, dict):
            continue
        name = str(thread.get("name", ""))
        if any(token and token in name for token in case_tokens):
            thread_id = str(thread.get("id", "")).strip()
            if thread_id:
                matches.append(thread_id)
    if len(matches) != 1:
        return ""
    return f"https://discord.com/channels/{guild_id}/{matches[0]}"



def _get_discord_json(path: str, token: str) -> dict:
    request = urllib.request.Request(
        f"https://discord.com/api/v10{path}",
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "legal-redactor/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        exc.read()
        raise DiscordApiError(f"Discord 帖子查询失败: HTTP {exc.code}") from exc
    except OSError as exc:
        raise DiscordApiError("Discord 帖子查询失败: 网络不可达") from exc
    if not isinstance(data, dict):
        raise DiscordApiError("Discord 帖子查询返回格式错误")
    return data



def _contains_local_path_text(value: str) -> bool:
    return bool(
        re.search(r"(^|\s)(~?/|/Users/|/Volumes/|/private/|/var/folders/|[A-Za-z]:[\\/]|\\\\)", value)
        or re.search(r"[\\/].+[\\/]", value)
    )



def _discord_command_channel_id() -> str:
    config = deps.load_json_config("LEGAL_REDACTOR_API_CONFIG", "api.local.json")
    return str(
        os.environ.get("LEGAL_REDACTOR_DISCORD_COMMAND_CHANNEL_ID")
        or deps.config_value(config, "discord_command_channel_id")
        or ""
    )



def _post_discord_channel_message(channel_id: str, content: str) -> dict[str, str]:
    config = deps.load_json_config("LEGAL_REDACTOR_API_CONFIG", "api.local.json")
    token = _discord_bot_token(config)
    channel_id = str(channel_id).strip()
    if not channel_id:
        raise RuntimeError("未配置 Discord 指令频道 id")

    payload = {"content": content.strip()[:1900]}
    request = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "legal-redactor/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        exc.read()
        raise DiscordApiError(f"Discord 指令发送失败: HTTP {exc.code}") from exc
    except OSError as exc:
        raise DiscordApiError("Discord 指令发送失败: 网络不可达") from exc
    return {
        "message_id": str(data.get("id", "")),
        "channel_id": str(data.get("channel_id") or channel_id),
    }



def _post_discord_thread_file(thread_id: str, filename: str, content: str, message: str = "") -> dict[str, str]:
    config = deps.load_json_config("LEGAL_REDACTOR_API_CONFIG", "api.local.json")
    token = _discord_bot_token(config)
    message = _safe_discord_attachment_message(filename, message)

    payload = {
        "content": message,
        "attachments": [{"id": 0, "filename": filename}],
    }
    fields = [
        ("payload_json", "application/json", None, json.dumps(payload, ensure_ascii=False).encode("utf-8")),
        ("files[0]", "text/plain; charset=utf-8", filename, content.encode("utf-8")),
    ]
    body, content_type = _multipart_form_data(fields)
    request = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{thread_id}/messages",
        data=body,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": content_type,
            "User-Agent": "legal-redactor/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        exc.read()
        raise DiscordApiError(f"Discord 发送失败: HTTP {exc.code}") from exc
    except OSError as exc:
        raise DiscordApiError("Discord 发送失败: 网络不可达") from exc
    return {
        "message_id": str(data.get("id", "")),
        "channel_id": str(data.get("channel_id", "")),
    }



def _safe_discord_attachment_message(filename: str, message: str = "") -> str:
    safe_filename = Path(filename).name or "redacted.txt"
    default = f"脱敏文件已生成，请见附件：{safe_filename}"
    value = re.sub(r"\r\n?", "\n", str(message)).strip()
    if not value or _contains_local_path_text(value):
        return default[:1900]
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return (value or default)[:1900]



def _multipart_form_data(fields: list[tuple[str, str, str | None, bytes]]) -> tuple[bytes, str]:
    boundary = f"----legal-redactor-{next(tempfile._get_candidate_names())}"
    chunks: list[bytes] = []
    for name, content_type, filename, value in fields:
        chunks.append(f"--{boundary}\r\n".encode("ascii"))
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename:
            disposition += f'; filename="{filename}"'
        chunks.append(f"{disposition}\r\n".encode("utf-8"))
        chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        chunks.append(value)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
