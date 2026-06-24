from __future__ import annotations

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
import importlib.util
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile

from .config import PipelineConfig
from .cases import CaseError, InvalidDiscordThreadError, case_dir, default_case_root, load_manifest, parse_discord_thread_id, persist_case_redaction
from .counters import CN_ORDINALS, TypeCounters
from .io import is_encrypted_map, load_redaction_map_encrypted, redaction_map_from_json, redaction_map_to_json
from .local_config import config_value, load_json_config
from .models import MappingEntry, RedactedDocument, RedactionMap
from .pipeline import RedactionPipeline
from .restore import preview_restore, restore_docx

try:
    from fastapi import FastAPI, File, Form, Request, UploadFile
    from fastapi.responses import HTMLResponse, JSONResponse
except ImportError as exc:
    raise RuntimeError("启动 Web UI 需要先安装依赖：pip install -r requirements.txt") from exc


app = FastAPI(title="本地法律文书脱敏系统", version="0.1.0")


@dataclass(frozen=True)
class InputDocument:
    source_file: str
    text: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "bind_host": "127.0.0.1", "network": "offline"}


@app.post("/api/save-to-local")
async def save_to_local(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        directory = body.get("directory", "").strip()
        files = body.get("files", [])
        
        if not directory:
            return JSONResponse({"status": "error", "message": "保存目录不能为空"}, status_code=400)
            
        expanded_dir = os.path.abspath(os.path.expanduser(directory))
        
        try:
            os.makedirs(expanded_dir, exist_ok=True)
        except Exception as e:
            return JSONResponse({"status": "error", "message": f"创建/访问目录失败: {str(e)}"}, status_code=400)
            
        saved_paths = []
        for file_item in files:
            filename = file_item.get("filename", "").strip()
            content = file_item.get("content", "")
            if not filename:
                continue
            file_path = os.path.join(expanded_dir, filename)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            saved_paths.append(file_path)
            
        if not saved_paths:
            return JSONResponse({"status": "error", "message": "没有需要保存的文件内容"}, status_code=400)
            
        return JSONResponse({
            "status": "success",
            "message": f"已成功保存 {len(saved_paths)} 个文件至本地目录：\n{expanded_dir}",
            "directory": expanded_dir,
            "saved_paths": saved_paths
        })
    except Exception as exc:
        return JSONResponse({"status": "error", "message": f"保存失败: {str(exc)}"}, status_code=500)


@app.post("/api/suggest-case-location")
async def suggest_case_location(request: Request) -> JSONResponse:
    body = await request.json()
    filenames = body.get("filenames", [])
    suggestion = _suggest_case_location_from_filenames(filenames)
    return JSONResponse(suggestion)


@app.post("/api/discord/send-redacted")
async def send_redacted_to_discord(request: Request) -> JSONResponse:
    body = await request.json()
    thread_url = str(body.get("discord_thread_url", "")).strip()
    filename = Path(str(body.get("filename", "redacted.txt"))).name or "redacted.txt"
    content = str(body.get("content", ""))
    message = str(body.get("message", "")).strip()
    if not thread_url:
        return JSONResponse({"status": "error", "message": "缺少 Discord 帖子链接"}, status_code=400)
    if not content:
        return JSONResponse({"status": "error", "message": "没有可发送的脱敏内容"}, status_code=400)
    try:
        thread_id = parse_discord_thread_id(thread_url)
    except InvalidDiscordThreadError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)
    try:
        result = _post_discord_thread_file(thread_id, filename, content, message)
    except RuntimeError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)
    return JSONResponse({"status": "success", **result})


@app.post("/api/discord/create-thread")
async def create_discord_thread(request: Request) -> JSONResponse:
    body = await request.json()
    case_folder = str(body.get("case_folder", "")).strip()
    case_cause = str(body.get("case_cause", "")).strip()
    if not case_folder:
        return JSONResponse({"status": "error", "message": "缺少案件文件夹名"}, status_code=400)
    request_id = str(body.get("request_id") or _new_discord_request_id())
    try:
        command = _case_creation_command(case_folder, request_id, case_cause)
        result = _post_discord_channel_message(_discord_command_channel_id(), command)
    except RuntimeError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)
    return JSONResponse({
        "status": "pending",
        "request_id": request_id,
        "command_message_id": result.get("message_id", ""),
        "channel_id": result.get("channel_id", ""),
        "message": "已发送建帖请求，等待 Hermes 通过 MCP 写回帖子链接",
    })


@app.post("/api/discord/attach-bound-thread")
async def attach_to_bound_discord_thread(request: Request) -> JSONResponse:
    body = await request.json()
    case_folder = str(body.get("case_folder", "")).strip()
    case_root = str(body.get("case_root", "")).strip() or str(default_case_root())
    source_dir = str(body.get("source_dir", "")).strip() or None
    filename = Path(str(body.get("filename", "redacted.txt"))).name or "redacted.txt"
    content = str(body.get("content", ""))
    message = str(body.get("message", "")).strip()
    map_json = str(body.get("map_json", ""))
    if not case_folder:
        return JSONResponse({"status": "error", "message": "缺少案件文件夹名"}, status_code=400)
    if not content:
        return JSONResponse({"status": "error", "message": "没有可发送的脱敏内容"}, status_code=400)
    try:
        case_path = case_dir(case_root, case_folder)
    except CaseError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)
    try:
        manifest = load_manifest(case_path)
    except FileNotFoundError:
        return JSONResponse({"status": "pending", "message": "等待 Hermes 写回 Discord 帖子链接"}, status_code=202)
    except Exception as exc:
        return JSONResponse({"status": "error", "message": f"案件 manifest 读取失败: {exc}"}, status_code=400)
    if not manifest.discord_thread_url:
        return JSONResponse({"status": "pending", "message": "等待 Hermes 写回 Discord 帖子链接"}, status_code=202)
    try:
        redaction_map = redaction_map_from_json(map_json)
    except Exception as exc:
        return JSONResponse({"status": "error", "message": f"映射表解析失败: {exc}"}, status_code=400)
    try:
        thread_id = parse_discord_thread_id(manifest.discord_thread_url)
        result = _post_discord_thread_file(
            thread_id,
            filename=filename,
            content=content,
            message=message,
        )
        persist_case_redaction(
            case_root,
            case_folder,
            manifest.discord_thread_url,
            [RedactedDocument(source_file=filename, original_text="", redacted_text=content)],
            redaction_map,
            source_dir=source_dir,
        )
    except (CaseError, InvalidDiscordThreadError, RuntimeError) as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)
    return JSONResponse({
        "status": "success",
        "thread_url": manifest.discord_thread_url,
        "thread_id": thread_id,
        "case_folder": case_folder,
        **result,
    })


@app.post("/api/mapping/suggest-entry")
async def suggest_mapping_entry(request: Request) -> JSONResponse:
    body = await request.json()
    selected_text = str(body.get("selected_text", "")).strip()
    entity_type = str(body.get("entity_type", "")).strip()
    map_json = str(body.get("map_json", ""))
    if not selected_text:
        return JSONResponse({"status": "error", "message": "未选择文字"}, status_code=400)
    if len(selected_text) > 80:
        return JSONResponse({"status": "error", "message": "选择文字过长，请只选择一个实体"}, status_code=400)
    if entity_type not in {"person", "organization", "location"}:
        return JSONResponse({"status": "error", "message": "不支持的实体类型"}, status_code=400)
    try:
        redaction_map = redaction_map_from_json(map_json)
    except Exception as exc:
        return JSONResponse({"status": "error", "message": f"映射表解析失败: {exc}"}, status_code=400)

    existing = _find_mapping_by_original(redaction_map.mappings, selected_text)
    if existing:
        return JSONResponse({
            "status": "exists",
            "entry": existing.to_dict(),
            "message": f"已存在映射：{existing.original} → {existing.masked}",
        })

    entry = _suggest_manual_mapping_entry(selected_text, entity_type, redaction_map.mappings)
    return JSONResponse({"status": "success", "entry": entry.to_dict()})


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    from ._samples import load_all_samples
    sample_lookup, sample_blacklist = load_all_samples()
    sample_info = ""

    return _page(
        "本地法律文书脱敏系统",
        sample_info + f"""
        <section>
          <h2>脱敏</h2>
          <form action="/redact" method="post" enctype="multipart/form-data">
            <label>粘贴文本</label>
            <textarea name="text" id="text-input" rows="12" placeholder="粘贴文书原文，或拖拽 txt/md/doc/docx/pdf 文件到此处"></textarea>
            <label>或上传 txt / md / doc / docx / pdf（可多选）</label>
            <input type="file" id="source-files" name="files" accept=".txt,.md,.doc,.docx,.pdf" multiple>
            <div class="row">
              <p class="hint">统一标准脱敏：人名、地名、机构名称及敏感编号按同一套规则处理。</p>
              <input type="hidden" name="enable_llm" value="1">
            </div>
            <label style="display:flex; align-items:center; gap:8px; margin-top:12px; margin-bottom:12px; cursor:pointer;">
              <input type="checkbox" name="enable_samples" value="1" checked style="width:auto; margin:0;">
              <span>使用样本库（利用历史黑名单与正样本）</span>
            </label>
            <label>分析模型</label>
            <p class="hint">固定使用 MLX Qwen3.5 9B 本地模型。</p>
            <input type="hidden" name="llm_mode" value="max-effect">
            <label style="display:flex; align-items:center; gap:8px; margin-top:12px; margin-bottom:12px; cursor:pointer;">
              <input type="checkbox" name="enable_hanlp" value="1" {_hanlp_checked_attr()} style="width:auto; margin:0;">
              <span>HanLP 本地候选识别（已安装时默认启用）</span>
            </label>
            <label>HanLP 模型（故障排查时再调整）</label>
            <input type="text" name="hanlp_model" value="MSRA_NER_ELECTRA_SMALL_ZH" style="max-width:320px">
            <label>已有映射表（保持替换一致性，选填，支持粘贴JSON或上传文件）</label>
            <textarea name="base_map_json" rows="3" placeholder="粘贴已有映射表 JSON（可选）"></textarea>
            <input type="file" name="base_map_file" accept=".json,.enc">
            <fieldset>
              <legend>案件工作流（选填）</legend>
              <label>案件文件夹名</label>
              <input type="text" id="case-folder-input" name="case_folder" placeholder="例如：2025 8765">
              <label>Discord 帖子链接</label>
              <input type="url" id="discord-thread-url-input" name="discord_thread_url" placeholder="可留空，脱敏完成后可请求 Hermes 新建并回写 Discord 链接">
              <label>案件库根目录</label>
              <input type="text" id="case-root-input" name="case_root" value="{html.escape(str(default_case_root()))}">
              <label>原文件所在目录</label>
              <input type="text" id="upload-source-dir-input" name="upload_source_dir" value="" placeholder="可选：自动识别失败时粘贴完整案件目录">
              <p class="hint">浏览器不会提供上传文件的本机绝对路径，所以系统会用文件名在案件库中反查目录。自动识别失败时，可在“原文件所在目录”粘贴完整目录。若未填写 Discord 链接，脱敏结果页可请求 Hermes 新建案件帖并通过 MCP 写回链接；映射表不会上传到 Discord。</p>
            </fieldset>
            <button type="submit" class="btn">一键脱敏</button>
          </form>
        </section>
        <section>
          <h2>还原</h2>
          <form action="/restore/preview" method="post" enctype="multipart/form-data">
            <label>粘贴脱敏后的文本</label>
            <textarea name="text" rows="6" placeholder="粘贴脱敏后的文书"></textarea>
            <label>或上传脱敏文本 / Word</label>
            <input type="file" name="file" accept=".txt,.md,.docx">
            <label style="display:flex; align-items:center; gap:8px; margin-top:12px; margin-bottom:12px; cursor:pointer;">
              <input type="checkbox" name="restore_docx_format" value="1" checked style="width:auto; margin:0;">
              <span>如果上传的是 Word，输出保留格式的 .docx</span>
            </label>
            <label>粘贴或上传映射表（支持加密文件）</label>
            <textarea name="map_json" rows="4" placeholder="粘贴 redaction_map.json"></textarea>
            <input type="file" name="map_file" accept=".json,.enc">
            <p class="hint">映射表中的全部条目将一次性还原。</p>
            <button type="submit" class="btn btn-secondary">全部还原</button>
          </form>
        </section>
        """,
    )

def _hanlp_checked_attr() -> str:
    return "checked" if importlib.util.find_spec("hanlp") is not None else ""


@app.post("/analyze", response_class=HTMLResponse)
async def analyze_page(
    text: str = Form(default=""),
    llm_mode: str = Form(default="max-effect"),
    enable_llm: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] = File(default=[]),
) -> str:
    try:
        documents = await _read_input_documents(text, file, files)
    except ValueError as exc:
        return _page("上传失败", str(exc))
        
    profile = "standard"
    llm_mode = "max-effect"
    config = PipelineConfig.from_llm_mode(llm_mode, profile_name=profile)
    pipeline = RedactionPipeline(config=config)
    
    # 执行语义审计
    raw_text = "\n\n".join(doc.text for doc in documents)
    analysis = pipeline.analyze(raw_text)
    
    return _render_audit_dashboard(
        analysis=analysis,
        original_documents=documents,
        profile=profile,
        llm_mode=llm_mode
    )

def _render_audit_dashboard(
    analysis: dict,
    original_documents: list[InputDocument],
    profile: str,
    llm_mode: str,
    round_num: int = 0,
    previous_map_json: str = "{}",
    previous_deselected_json: str = "[]",
    locked_entries: list[MappingEntry] | None = None,
) -> str:
    locked_entries = locked_entries or []

    # 已锁定的实体展示
    locked_html = ""
    if locked_entries and round_num > 0:
        locked_rows = ""
        for e in locked_entries:
            locked_rows += f'<tr class="locked-row"><td><span class="tag tag-locked">已替换</span></td><td colspan="2">{html.escape(e.original)} → {html.escape(e.masked)}</td></tr>'
        locked_html = f"""
        <details class="locked-section" {'open' if len(locked_entries) <= 8 else ''}>
          <summary>已确认并替换 <span class="badge">{len(locked_entries)}</span> 条</summary>
          <table class="locked-table"><tbody>{locked_rows}</tbody></table>
        </details>
        """

    groups = analysis.get("entity_groups", [])
    groups_html = ""
    for g in groups:
        aliases = [a for a in g.get("aliases", []) if a]
        aliases_str = "、".join(aliases) if aliases else "无"
        entity_type_label = "公司/机构" if g.get("type") == "organization" else "个人"
        groups_html += f"""
        <tr class="entity-row">
          <td><input type="checkbox" checked name="group_{g.get('id')}_enabled" value="1"></td>
          <td><span class="tag type-{g.get('type')}">{entity_type_label}</span></td>
          <td><span class="tag role-{g.get('role')}">{g.get('role', '') or ''}</span></td>
          <td class="full-name"><strong>{html.escape(g.get('full_name', ''))}</strong></td>
          <td class="aliases">{html.escape(aliases_str)}</td>
          <td><input type="text" name="group_{g.get('id')}_mask" placeholder="自动生成" class="mask-input"></td>
        </tr>
        """

    locations = analysis.get("locations", [])
    locations_html = "".join(
        f'<li><label><input type="checkbox" checked name="loc_{idx}" value="{html.escape(str(l))}"> {html.escape(str(l))}</label></li>'
        for idx, l in enumerate(locations)
    )

    bundle_json = json.dumps([{"source_file": d.source_file, "text": d.text} for d in original_documents], ensure_ascii=False)

    round_badge = f' <span class="round-badge">第 {round_num + 1} 轮</span>' if round_num > 0 else ""
    subtitle = "（基于已脱敏文本的二次扫描）" if round_num > 0 else "（基于原文首次扫描）"

    return _page(
        f"分级确认 - 语义审计{round_badge}",
        f"""
        <nav><a href="/">返回首页</a></nav>
        <section class="info-card">
          <h2>识别到的主体与关联关系 {round_badge}</h2>
          <p class="hint">{subtitle} 大模型已自动将"全称"与"简称"归组。您可以取消勾选不需脱敏的项，或手动指定脱敏后的代号。</p>
          {locked_html}
          <form action="/redact/confirmed" method="post">
            <input type="hidden" name="profile" value="{profile}">
            <input type="hidden" name="llm_mode" value="{llm_mode}">
            <input type="hidden" name="bundle_json" value="{html.escape(bundle_json)}">
            <input type="hidden" name="analysis_json" value="{html.escape(json.dumps(analysis, ensure_ascii=False))}">
            <input type="hidden" name="round" value="{round_num}">
            <input type="hidden" name="previous_map_json" value="{html.escape(previous_map_json)}">
            <input type="hidden" name="previous_deselected_json" value="{html.escape(previous_deselected_json)}">
            {'<p class="hint" style="color:var(--muted)">未发现新实体 — 点击"完成脱敏"查看最终结果。</p>' if not groups and not locations else ''}
            {'<table class="audit-table">'
             '<thead><tr><th>脱敏</th><th>类型</th><th>角色</th><th>全称</th><th>关联简称</th><th>指定代号</th></tr></thead>'
             '<tbody>' + groups_html + '</tbody></table>' if groups else ''}
            {'<h3>识别到的地名</h3><ul class="tag-list">' + locations_html + '</ul>' if locations else ''}
            <div style="margin-top:30px; border-top:1px solid #eee; padding-top:20px; display:flex; gap:10px">
              <button type="submit" name="action" value="continue" class="btn">确认并继续分析</button>
              <button type="submit" name="action" value="finish" class="btn btn-secondary">完成脱敏</button>
            </div>
          </form>
        </section>
        <style>
          .audit-table {{ width:100%; border-collapse:collapse; margin:20px 0; }}
          .audit-table th, .audit-table td {{ padding:12px; border-bottom:1px solid #eee; text-align:left; }}
          .tag {{ padding:3px 8px; border-radius:4px; font-size:12px; font-weight:bold; }}
          .type-organization {{ background:#f0f7ff; color:#0052cc; }}
          .type-person {{ background:#fff7e6; color:#d46b08; }}
          .role-原告 {{ color:#52c41a; }}
          .role-被告 {{ color:#ff4d4f; }}
          .mask-input {{ border:1px solid #ddd; padding:5px; border-radius:4px; width:100px; }}
          .tag-list {{ list-style:none; padding:0; display:flex; flex-wrap:wrap; gap:10px; }}
          .tag-list li {{ background:#f5f5f5; padding:5px 12px; border-radius:20px; font-size:13px; }}
          .round-badge {{ font-size:13px; background:var(--accent); color:#fff; padding:2px 10px; border-radius:99px; font-weight:500 }}
          .locked-section {{ margin-bottom:18px; padding:12px; background:var(--bg); border-radius:var(--radius-sm); border:1px solid var(--border) }}
          .locked-section summary {{ cursor:pointer; font-weight:600; color:var(--muted); font-size:13px }}
          .locked-table {{ width:100%; border-collapse:collapse; margin-top:8px; font-size:12px }}
          .locked-table td {{ padding:6px 8px; border-bottom:1px solid var(--border) }}
          .locked-row {{ opacity:0.55 }}
          .tag-locked {{ background:#d4edda; color:#155724 }}
          .badge {{ background:var(--ink); color:#fff; padding:1px 7px; border-radius:99px; font-size:11px; font-weight:600 }}
        </style>
        """
    )


@app.post("/redact/confirmed", response_class=HTMLResponse)
async def redact_confirmed_page(request: Request) -> str:
    """增量脱敏：每轮确认后立即替换，再用已脱敏文本做下一轮分析。

    用户勾选的实体本轮生效，未勾选的不会出现在下一轮。
    每轮替换后的文本会传给 LLM 做二次审计，只展示新发现的实体。
    """
    form = await request.form()
    bundle_json = form.get("bundle_json", "")
    analysis_json = form.get("analysis_json", "")
    profile = "standard"
    llm_mode = "max-effect"
    round_num = int(form.get("round", "0"))
    previous_map_json = form.get("previous_map_json", "{}")
    previous_deselected_json = form.get("previous_deselected_json", "[]")
    action = form.get("action", "continue")

    docs_data = json.loads(bundle_json)
    is_batch = len(docs_data) > 1

    analysis = json.loads(analysis_json)
    prev_data = json.loads(previous_map_json) if previous_map_json else {}
    prev_mappings_dicts: list[dict] = prev_data.get("mappings", [])
    prev_confirmed_texts: set[str] = set(prev_data.get("confirmed_texts", []))
    all_deselected_texts: set[str] = set(json.loads(previous_deselected_json))

    # 收集本轮勾选的实体文本和自定义掩码
    confirmed_texts: set[str] = set()
    user_masks: dict[str, str] = {}

    for g in analysis.get("entity_groups", []):
        gid = g.get("id")
        if form.get(f"group_{gid}_enabled"):
            full = g.get("full_name", "").strip()
            if full:
                confirmed_texts.add(full)
            for alias in g.get("aliases", []):
                alias = alias.strip()
                if alias:
                    confirmed_texts.add(alias)
            custom = (form.get(f"group_{gid}_mask") or "").strip()
            if custom and full:
                user_masks[full] = custom

    for idx, loc in enumerate(analysis.get("locations", [])):
        if form.get(f"loc_{idx}"):
            loc = str(loc).strip()
            if loc:
                confirmed_texts.add(loc)

    # 记录本轮未勾选的实体 → 永久排除
    for g in analysis.get("entity_groups", []):
        gid = g.get("id")
        if not form.get(f"group_{gid}_enabled"):
            full = g.get("full_name", "").strip()
            if full:
                all_deselected_texts.add(full)
            for alias in g.get("aliases", []):
                alias = alias.strip()
                if alias:
                    all_deselected_texts.add(alias)

    for idx, loc in enumerate(analysis.get("locations", [])):
        if not form.get(f"loc_{idx}"):
            loc = str(loc).strip()
            if loc:
                all_deselected_texts.add(loc)

    # 合并所有轮次的已确认实体
    all_confirmed = prev_confirmed_texts | confirmed_texts

    # 生成本轮新增的映射条目（按实体组：同组全称和简称共用掩码）
    counters = TypeCounters()
    for g in analysis.get("entity_groups", []):
        gid = g.get("id")
        if not form.get(f"group_{gid}_enabled"):
            continue
        full = g.get("full_name", "").strip()
        if not full:
            continue
        custom = (form.get(f"group_{gid}_mask") or "").strip()
        group_mask = custom or _simple_mask(full, counters)
        prev_mappings_dicts.append({
            "type": "manual", "original": full, "masked": group_mask,
            "role": g.get("role"), "source": "user_confirmed",
            "confidence": 1.0, "restore_by_default": True,
        })
        for alias in g.get("aliases", []):
            alias = alias.strip()
            if alias and alias != full:
                prev_mappings_dicts.append({
                    "type": "manual", "original": alias, "masked": group_mask,
                    "role": g.get("role"), "source": "user_confirmed_alias",
                    "confidence": 1.0, "restore_by_default": True,
                })

    # 地名使用独立掩码（强制用地点掩码，即使无后缀）
    for idx, loc in enumerate(analysis.get("locations", [])):
        if not form.get(f"loc_{idx}"):
            continue
        loc = str(loc).strip()
        if not loc:
            continue
        # 地名可能无后缀（如"石家庄""沧州"），不能用 _simple_mask（会误判为姓名）
        loc_masked = _simple_mask(loc, counters)
        if "自然人" in loc_masked:
            loc_masked = _guess_location_mask(loc)
        prev_mappings_dicts.append({
            "type": "manual", "original": loc, "masked": loc_masked,
            "role": None, "source": "user_confirmed",
            "confidence": 1.0, "restore_by_default": True,
        })

    # 合并去重（同一原文只保留一条）
    merged: dict[str, dict] = {}
    for m in prev_mappings_dicts:
        merged.setdefault(m["original"], m)
    all_mapping_dicts = list(merged.values())

    all_mappings = [
        MappingEntry(
            type=m.get("type", "manual"),
            original=m.get("original", ""),
            masked=m.get("masked", ""),
            role=m.get("role"),
            source=m.get("source", "user_confirmed"),
            confidence=float(m.get("confidence", 1.0)),
            restore_by_default=m.get("restore_by_default", True),
        )
        for m in all_mapping_dicts
    ]

    # 应用所有已确认映射
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm(profile))
    redaction_map = RedactionMap.create(mappings=all_mappings, mode=profile)

    # 当前轮次的映射数据（传给下一轮）
    current_map_json = json.dumps({
        "mappings": all_mapping_dicts,
        "confirmed_texts": list(all_confirmed),
    }, ensure_ascii=False)
    deselected_json = json.dumps(list(all_deselected_texts), ensure_ascii=False)

    # ── 批量文档：直接展示最终结果（不支持多轮） ──
    if is_batch:
        redacted_docs: list[RedactedDocument] = []
        all_leaks: list = []
        for d in docs_data:
            rt = pipeline.apply_redaction_map(d["text"], redaction_map)
            lks = pipeline.scan_high_risk_leaks(rt)
            redacted_docs.append(RedactedDocument(
                source_file=d.get("source_file", ""),
                original_text=d["text"],
                redacted_text=rt,
                leaks=lks,
            ))
            all_leaks.extend(lks)
        return _render_batch_redaction_result(
            title="脱敏完成",
            documents=redacted_docs,
            redaction_map=redaction_map,
            review_candidates=[],
            leaks=all_leaks,
            warnings=[],
        )

    # ── 单文档：增量多轮确认 ──
    original_text = docs_data[0]["text"]
    redacted_text = pipeline.apply_redaction_map(original_text, redaction_map)

    # 点了"完成" → 直接展示最终结果
    if action == "finish":
        leaks = pipeline.scan_high_risk_leaks(redacted_text)
        return _render_redaction_result(
            title="脱敏完成",
            original_text=original_text,
            redacted_text=redacted_text,
            redaction_map=redaction_map,
            review_candidates=[],
            leaks=leaks,
            warnings=[],
        )

    # 对已脱敏文本做新一轮 LLM 分析
    config = PipelineConfig.from_llm_mode(llm_mode, profile_name=profile)
    pipeline2 = RedactionPipeline(config=config)
    new_analysis = pipeline2.analyze(redacted_text)

    # 过滤掉已确认和已排除的实体
    new_groups = []
    for g in new_analysis.get("entity_groups", []):
        full = g.get("full_name", "").strip()
        aliases = [a.strip() for a in g.get("aliases", []) if a.strip()]
        all_texts = {full, *aliases}
        if all(t in all_confirmed or t in all_deselected_texts for t in all_texts if t):
            continue
        g["aliases"] = [a for a in aliases if a not in all_confirmed and a not in all_deselected_texts]
        new_groups.append(g)

    new_locations = [
        l for l in new_analysis.get("locations", [])
        if l not in all_confirmed and l not in all_deselected_texts
    ]

    new_analysis["entity_groups"] = new_groups
    new_analysis["locations"] = new_locations

    if new_groups or new_locations:
        return _render_audit_dashboard(
            analysis=new_analysis,
            original_documents=[InputDocument(source_file="", text=redacted_text)],
            profile=profile,
            llm_mode=llm_mode,
            round_num=round_num + 1,
            previous_map_json=current_map_json,
            previous_deselected_json=deselected_json,
            locked_entries=all_mappings,
        )
    else:
        leaks = pipeline.scan_high_risk_leaks(redacted_text)
        return _render_redaction_result(
            title="脱敏完成",
            original_text=original_text,
            redacted_text=redacted_text,
            redaction_map=redaction_map,
            review_candidates=[],
            leaks=leaks,
            warnings=[],
        )


@app.post("/redact", response_class=HTMLResponse)
async def redact_page(
    text: str = Form(default=""),
    llm_mode: str = Form(default="max-effect"),
    enable_llm: str | None = Form(default=None),
    enable_hanlp: str | None = Form(default=None),
    hanlp_model: str = Form(default=""),
    enable_samples: str | None = Form(default=None),
    base_map_json: str = Form(default=""),
    case_folder: str = Form(default=""),
    discord_thread_url: str = Form(default=""),
    case_root: str = Form(default=""),
    upload_source_dir: str = Form(default=""),
    base_map_file: UploadFile | None = File(default=None),
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] = File(default=[]),
) -> str:
    try:
        documents = await _read_input_documents(text, file, files)
    except ValueError as exc:
        return _page("上传失败", str(exc))

    base_redaction_map = None
    if base_map_json.strip() or (base_map_file and base_map_file.filename):
        try:
            map_text = await _read_restore_map_text(base_map_json, base_map_file)
            base_redaction_map = redaction_map_from_json(map_text)
        except Exception as exc:
            return _page("已有映射表解析失败", f"解析错误: {exc}")

    llm_mode = "max-effect"
    config = PipelineConfig.from_llm_mode(
        llm_mode,
        profile_name="standard",
    )
    config = replace(
        config,
        enable_sample_library=bool(enable_samples),
        enable_hanlp_ner=bool(enable_hanlp),
        hanlp_model=hanlp_model.strip() or "MSRA_NER_ELECTRA_SMALL_ZH",
    )
    pipeline = RedactionPipeline(config=config)
    source_files = [item.source_file for item in documents]
    inferred_case_location = _resolve_case_location(upload_source_dir, source_files)
    inferred_source_dir = str(inferred_case_location.get("matched_dir") or "")
    effective_case_folder = case_folder.strip() or str(inferred_case_location.get("case_folder") or "")
    effective_case_root = case_root.strip() or str(inferred_case_location.get("case_root") or "")
    effective_discord_thread_url = discord_thread_url.strip() or str(inferred_case_location.get("discord_thread_url") or "")
    if len(documents) > 1:
        result = pipeline.redact_many([(item.source_file, item.text) for item in documents], base_redaction_map=base_redaction_map)
        warnings = list(result.warnings)
        try:
            _persist_optional_case_redaction(effective_case_root, effective_case_folder, effective_discord_thread_url, result.documents, result.redaction_map)
        except CaseError as exc:
            return _page("案件保存失败", f"保存错误: {exc}")
        except Exception as exc:
            return _page("案件保存失败", f"保存错误: {exc}")
        if effective_case_folder and effective_discord_thread_url:
            warnings.append(f"已保存到案件库：{effective_case_folder}")
        return _render_batch_redaction_result(
            "脱敏结果",
            result.documents,
            result.redaction_map,
            result.review_candidates,
            result.leaks,
            warnings,
            save_dir=inferred_source_dir,
            discord_thread_url=effective_discord_thread_url,
            case_root=effective_case_root,
            case_folder=effective_case_folder,
            source_dir=inferred_source_dir,
        )
    
    result = pipeline.redact(documents[0].text, source_file=documents[0].source_file, base_redaction_map=base_redaction_map)
    warnings = list(result.warnings)
    redacted_doc = RedactedDocument(
        source_file=documents[0].source_file,
        original_text=result.original_text,
        redacted_text=result.redacted_text,
        leaks=result.leaks,
    )
    try:
        _persist_optional_case_redaction(effective_case_root, effective_case_folder, effective_discord_thread_url, [redacted_doc], result.redaction_map)
    except CaseError as exc:
        return _page("案件保存失败", f"保存错误: {exc}")
    except Exception as exc:
        return _page("案件保存失败", f"保存错误: {exc}")
    if effective_case_folder and effective_discord_thread_url:
        warnings.append(f"已保存到案件库：{effective_case_folder}")
    return _render_redaction_result(
        "脱敏结果",
        result.original_text,
        result.redacted_text,
        result.redaction_map,
        result.review_candidates,
        result.leaks,
        warnings,
        save_dir=inferred_source_dir,
        discord_thread_url=effective_discord_thread_url,
        case_root=effective_case_root,
        case_folder=effective_case_folder,
        source_dir=inferred_source_dir,
    )


@app.post("/redact/apply-map", response_class=HTMLResponse)
async def apply_map_page(
    original_text: str = Form(...),
    map_json: str = Form(...),
    original_bundle_json: str = Form(default=""),
) -> str:
    try:
        redaction_map = redaction_map_from_json(map_json)
    except Exception as exc:
        return _page("映射表解析失败", f"错误详情: {exc}")

    pipeline = RedactionPipeline(config=PipelineConfig(redaction_profile=RedactionProfile.from_preset("standard")))
    if original_bundle_json.strip():
        documents = _documents_from_bundle_json(original_bundle_json)
        redacted_documents = []
        all_leaks = []
        for doc in documents:
            redacted_text = pipeline.apply_redaction_map(doc.text, redaction_map)
            leaks = pipeline.scan_high_risk_leaks(redacted_text)
            redacted_documents.append(
                RedactedDocument(
                    source_file=doc.source_file,
                    original_text=doc.text,
                    redacted_text=redacted_text,
                    leaks=leaks,
                )
            )
            all_leaks.extend(leaks)
        return _render_batch_redaction_result(
            title="应用映射表结果",
            documents=redacted_documents,
            redaction_map=redaction_map,
            review_candidates=[],
            leaks=all_leaks,
            warnings=["已重新应用您上传/修改后的映射表。"],
        )

    redacted_text = pipeline.apply_redaction_map(original_text, redaction_map)
    leaks = pipeline.scan_high_risk_leaks(redacted_text)
    return _render_redaction_result(
        title="应用映射表结果",
        original_text=original_text,
        redacted_text=redacted_text,
        redaction_map=redaction_map,
        review_candidates=[],
        leaks=leaks,
        warnings=["已重新应用您上传/修改后的映射表。"],
    )


@app.post("/redact/apply-edited-map", response_class=HTMLResponse)
async def apply_edited_map_page(request: Request) -> str:
    form = await request.form()
    original_text = form.get("original_text", "")
    original_bundle_json = form.get("original_bundle_json", "")
    save_dir = str(form.get("save_dir", ""))
    discord_thread_url = str(form.get("discord_thread_url", ""))
    case_root = str(form.get("case_root", ""))
    case_folder = str(form.get("case_folder", ""))
    source_dir = str(form.get("source_dir", ""))
    map_version = form.get("map_version", "1.0")
    map_created_at = form.get("map_created_at", "")
    map_mode = form.get("map_mode", "normal")
    map_source_file = form.get("map_source_file", "")

    map_type = form.getlist("map_type")
    map_original = form.getlist("map_original")
    map_masked = form.getlist("map_masked")
    map_role = form.getlist("map_role")
    map_source = form.getlist("map_source")
    map_confidence = form.getlist("map_confidence")
    map_restore_by_default = form.getlist("map_restore_by_default")
    row_delete = form.getlist("row_delete")

    redaction_map = _redaction_map_from_rows(
        version=map_version, created_at=map_created_at, mode=map_mode,
        source_file=map_source_file, map_type=map_type, map_original=map_original,
        map_masked=map_masked, map_role=map_role, map_source=map_source,
        map_confidence=map_confidence, map_restore_by_default=map_restore_by_default,
        row_delete=row_delete,
    )
    pipeline = RedactionPipeline(config=PipelineConfig.offline_without_llm())
    documents = _documents_from_bundle_json(original_bundle_json)
    if documents:
        redacted_documents = _apply_map_to_documents(pipeline, documents, redaction_map)
        leaks = [lk for d in redacted_documents for lk in d.leaks]
        return _render_batch_redaction_result(
            "编辑映射后结果",
            redacted_documents,
            redaction_map,
            [],
            leaks,
            ["已手动调整映射表。"],
            save_dir=save_dir,
            discord_thread_url=discord_thread_url,
            case_root=case_root,
            case_folder=case_folder,
            source_dir=source_dir,
        )
    redacted_text = pipeline.apply_redaction_map(original_text, redaction_map)
    leaks = pipeline.scan_high_risk_leaks(redacted_text)
    return _render_redaction_result(
        "编辑映射后结果",
        original_text,
        redacted_text,
        redaction_map,
        [],
        leaks,
        ["已手动调整映射表。"],
        save_dir=save_dir,
        discord_thread_url=discord_thread_url,
        case_root=case_root,
        case_folder=case_folder,
        source_dir=source_dir,
    )


@app.post("/redact/save-sample", response_class=HTMLResponse)
async def save_sample_page(request: Request) -> str:
    form = await request.form()
    map_type = form.getlist("map_type")
    map_original = form.getlist("map_original")
    map_masked = form.getlist("map_masked")
    map_role = form.getlist("map_role")
    map_source = form.getlist("map_source")
    map_confidence = form.getlist("map_confidence")
    map_restore_by_default = form.getlist("map_restore_by_default")
    row_delete = form.getlist("row_delete")
    map_source_file = form.get("map_source_file", "")
    original_mapping_json = form.get("original_mapping_json", "")

    from ._samples import is_global_delete_sample_allowed, save_sample_auto

    try:
        original_data = json.loads(original_mapping_json) if original_mapping_json else {}
    except json.JSONDecodeError:
        original_data = {}
    original_mappings = original_data.get("mappings", [])
    original_index = {e.get("original", ""): e for e in original_mappings}

    deleted = set(str(r) for r in row_delete)
    edited_index: dict[str, str] = {}
    edited_types: dict[str, str] = {}
    for i in range(max(len(map_original), len(map_masked))):
        if str(i) in deleted: continue
        orig = (map_original[i] if i < len(map_original) else "").strip()
        masked = (map_masked[i] if i < len(map_masked) else "").strip()
        t = (map_type[i] if i < len(map_type) else "other").strip()
        if orig and masked:
            edited_index[orig] = masked
            edited_types[orig] = t

    entries: list[dict] = []
    processed: set[str] = set()
    skipped_risky_deletes: list[str] = []
    for i_str in deleted:
        try:
            i = int(i_str)
            if i < len(map_original):
                orig = map_original[i].strip()
                if orig and orig not in processed:
                    entry = {"action": "delete", "type": map_type[i] if i < len(map_type) else "other", "original": orig}
                    if is_global_delete_sample_allowed(entry):
                        entries.append(entry)
                    else:
                        skipped_risky_deletes.append(orig)
                    processed.add(orig)
        except (ValueError, IndexError):
            continue
    for orig, masked in edited_index.items():
        if orig in processed: continue
        processed.add(orig)
        t = edited_types.get(orig, "other")
        if orig in original_index:
            old_masked = original_index[orig].get("masked", "")
            if masked != old_masked:
                entries.append({"action": "modify", "type": t, "old_original": orig, "new_original": orig, "old_masked": old_masked, "new_masked": masked})
            # keep 条目不保存（识别正确的无需记录）
        else:
            entries.append({"action": "add", "type": t, "original": orig, "masked": masked})

    if not entries:
        if skipped_risky_deletes:
            return HTMLResponse('<script>parent.postMessage({type:"toast",msg:"短中文人名未写入全局黑名单，请用修改映射或规则修正处理",cls:"warn"},"*")</script>')
        return HTMLResponse('<script>parent.postMessage({type:"toast",msg:"无变化，未追加"},"*")</script>')

    try:
        save_sample_auto(entries, source=map_source_file or "web_ui")
    except Exception as exc:
        return HTMLResponse(f'<script>parent.postMessage({{type:"toast",msg:"保存失败:{html.escape(str(exc))}",cls:"warn"}},"*")</script>')

    added = len(entries)
    new_count = sum(1 for e in entries if e["action"] in ("add", "modify"))
    del_count = sum(1 for e in entries if e["action"] == "delete")
    msg = f'已追加 {added} 条 | 匹配 {new_count} | 黑名单 {del_count}'
    if skipped_risky_deletes:
        msg += f' | 跳过短人名黑名单 {len(skipped_risky_deletes)}'
    return HTMLResponse(f'<script>parent.postMessage({{type:"toast",msg:{json.dumps(msg)}}},"*")</script>')


def _diagnose_sample_entry(entry: dict) -> str:
    action = entry.get("action", "")
    orig = entry.get("original") or entry.get("new_original", "")
    masked = entry.get("masked") or entry.get("new_masked", "")
    
    if action == "delete":
        matched_rules = []
        # 1. 手机/电话
        if re.search(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)", orig):
            matched_rules.append("手机号正则")
        # 2. 身份证
        if re.search(r"(?<![0-9Xx])\d{6}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![0-9Xx])", orig):
            matched_rules.append("身份证号正则")
        # 3. 信用代码
        if re.search(r"(?<![A-Z0-9])[0-9A-Z]{18}(?![A-Z0-9])", orig):
            matched_rules.append("信用代码正则")
        # 4. 案号
        if re.search(r"[（(][12]\d{3}[）)][\u4e00-\u9fa5A-Za-z0-9]{1,16}?(?:知民初|知民终|执异|执复|民辖终|民辖初|民辖|民初|民终|民申|民再|行初|行终|行申|刑初|刑终|刑申|刑再|商初|商终|破申|执|民撤|民特|民保|强清|管辖)", orig):
            matched_rules.append("案号结构化正则")
        # 5. 地名/行政区划
        if re.search(r"[\u4e00-\u9fa5]{2,6}?(?:省|自治区|市|自治州|盟|区|县|旗|镇|乡|街道|村|社区)$", orig):
            matched_rules.append("启发式地名匹配")
        # 6. 常见人名兜底
        if len(orig) in (2, 3):
            matched_rules.append("姓名兜底匹配")
        # 7. 机构/公司
        if any(orig.endswith(sfx) for sfx in ["有限责任公司", "股份有限公司", "集团有限公司", "有限公司", "公司", "集团", "律师事务所", "会计师事务所", "经营部", "商行", "工作室", "厂", "店"]):
            matched_rules.append("机构后缀特征")
            
        if not matched_rules:
            matched_rules.append("LLM语义审计或规则兜底")
            
        rules_str = "、".join(matched_rules)
        return f"<span style='color:var(--danger);font-weight:500'>误匹配为实体</span>（触发「{rules_str}」）。<b>已加入黑名单，下次分析相同文本将自动豁免，不再误判！</b>"

    elif action == "modify":
        old_masked = entry.get("old_masked", "")
        new_masked = entry.get("new_masked", "")
        return f"<span style='color:#e65100;font-weight:500'>修正脱敏掩码</span>（从「{old_masked}」修正为「{new_masked}」）。<b>已载入精准映射，下次直接以此格式脱敏该词。</b>"

    elif action == "add":
        return f"<span style='color:#1565c0;font-weight:500'>手动新增实体</span>。<b>已载入精准映射，下次该词将直接脱敏为「{masked}」。</b>"

    elif action == "keep":
        return f"<span style='color:#2e7d32;font-weight:500'>确认无误（保留）</span>。<b>已记录，下次将直接命中并直接脱敏。</b>"

    return "已作为脱敏样本库记录并投入使用。"


@app.get("/samples/edit", response_class=HTMLResponse)
def edit_samples_page() -> str:
    from ._samples import _auto_sample_path
    filepath = _auto_sample_path()
    entries = []
    if filepath.exists():
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
        except (json.JSONDecodeError, KeyError):
            pass

    rows = ""
    for i, e in enumerate(entries):
        action = e.get("action", "?")
        orig = e.get("original") or e.get("new_original", "")
        masked = e.get("masked") or e.get("new_masked", "")
        old = e.get("old_original", "")
        action_label = {"keep": "保留", "delete": "黑名单", "add": "新增", "modify": "修改"}.get(action, action)
        row_class = "style='opacity:.6'" if action == "delete" else ""
        row_diagnose = _diagnose_sample_entry(e)
        rows += f"""<tr {row_class}>
          <td><span class="tag tag-{action}">{action_label}</span></td>
          <td><input name="orig_{i}" value="{html.escape(orig)}" style="width:180px"></td>
          <td><input name="masked_{i}" value="{html.escape(masked)}" style="width:140px"></td>
          <td style="font-size:11px;color:var(--muted)">{html.escape(old)}</td>
          <td style="font-size:12px;color:var(--ink);max-width:320px;word-break:break-all">{row_diagnose}</td>
          <td>
            <button class="btn btn-sm" onclick="saveRow({i},this)">保存</button>
            <a href="/samples/delete/{i}" class="btn btn-sm btn-secondary" style="margin-left:4px">删除</a>
          </td>
        </tr>"""
    rows += f"""<tr>
      <td><select id="new-action" style="width:80px"><option value="add">新增</option><option value="delete">黑名单</option></select></td>
      <td><input id="new-orig" placeholder="原文" style="width:180px"></td>
      <td><input id="new-masked" placeholder="替换为" style="width:140px"></td>
      <td></td>
      <td></td>
      <td><button class="btn btn-sm" onclick="saveNewRow({len(entries)},this)">＋</button></td>
    </tr>"""

    return _page(
        "编辑样本库",
        f"""
        <nav><a href="/">返回首页</a></nav>
        <style>
          .tag{{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11px;font-weight:600}}
          .tag-keep{{background:#e8f5e9;color:#2e7d32}}
          .tag-delete{{background:#fce4ec;color:#c62828}}
          .tag-add{{background:#e3f2fd;color:#1565c0}}
          .tag-modify{{background:#fff3e0;color:#e65100}}
        </style>
        <section>
          <h2>样本库（{len(entries)} 条）</h2>
          <p class="hint">编辑后自动保存。删除操作立即生效。</p>
          <table>
            <thead><tr><th>类型</th><th>原文</th><th>替换为</th><th>旧值</th><th>诊断与优化分析</th><th>操作</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </section>
        """,
    )


@app.post("/samples/update/{idx}")
async def update_sample_entry(idx: int, request: Request) -> JSONResponse:
    from ._samples import _auto_sample_path, save_sample_auto
    filepath = _auto_sample_path()
    body = await request.json()
    if not filepath.exists():
        return JSONResponse({"msg": "样本库为空"})
    data = json.loads(filepath.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    if 0 <= idx < len(entries):
        e = entries[idx]
        action = e.get("action", "")
        if action in ("keep", "add"):
            e["original"] = body.get("original", e.get("original", ""))
            e["masked"] = body.get("masked", e.get("masked", ""))
        elif action == "modify":
            e["new_original"] = body.get("original", e.get("new_original", ""))
            e["new_masked"] = body.get("masked", e.get("new_masked", ""))
        save_sample_auto([e], source=e.get("source", "samples_edit"))
        return JSONResponse({"msg": "已保存"})
    return JSONResponse({"msg": "索引无效"}, status_code=400)


@app.post("/samples/add")
async def add_sample_entry(request: Request) -> JSONResponse:
    from ._samples import is_global_delete_sample_allowed, save_sample_auto
    body = await request.json()
    action = body.get("action", "add")
    orig = body.get("original", "").strip()
    masked = body.get("masked", "").strip()
    if not orig:
        return JSONResponse({"msg": "原文不能为空"}, status_code=400)
    if action == "delete":
        entry = {"action": "delete", "type": "manual", "original": orig}
        if not is_global_delete_sample_allowed(entry):
            return JSONResponse({"msg": "短中文人名不写入全局黑名单，请改用精确映射校准。"}, status_code=400)
        save_sample_auto([entry], source="samples_edit")
    else:
        save_sample_auto([{"action": "add", "type": "manual", "original": orig, "masked": masked}], source="samples_edit")
    return JSONResponse({"msg": "已添加"})


@app.get("/samples/delete/{idx}", response_class=HTMLResponse)
def delete_sample_entry(idx: int) -> str:
    from ._samples import _auto_sample_path
    filepath = _auto_sample_path()
    if not filepath.exists():
        return _page("错误", '<p>样本库为空。</p><a href="/samples/edit">返回</a>')
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
        if 0 <= idx < len(entries):
            entries.pop(idx)
            data["entries"] = entries
            data["total"] = len(entries)
            filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return _page("已删除", f'<p>第 {idx+1} 条已删除。</p><a href="/samples/edit">返回样本库</a>')
    except Exception as exc:
        return _page("错误", f'<p>{html.escape(str(exc))}</p><a href="/samples/edit">返回</a>')


@app.get("/samples/compact", response_class=HTMLResponse)
def compact_samples_page() -> str:
    from ._samples import compact_samples
    compact_samples()
    return _page("整理完成", '<p class="success">样本库已去重并优化。</p><nav><a href="/">返回首页</a></nav>')


@app.post("/restore/preview", response_class=HTMLResponse)
async def restore_preview_page(
    text: str = Form(default=""),
    file: UploadFile | None = File(default=None),
    map_json: str = Form(default=""),
    map_file: UploadFile | None = File(default=None),
    restore_docx_format: str | None = Form(default=None),
) -> str:
    try:
        redacted_text = text.strip()
        redacted_docx_bytes: bytes | None = None
        redacted_filename = ""
        if file and file.filename:
            data = await file.read()
            redacted_filename = file.filename
            if _suffix_for_filename(file.filename) == ".docx":
                redacted_docx_bytes = data
                redacted_text = _docx_bytes_to_text(data)
            else:
                redacted_text = _decode_text_bytes(data, file.filename)
        map_text = await _read_restore_map_text(map_json, map_file)

        if not map_text or not redacted_text:
            return _page("参数缺失", '<nav><a href="/">返回</a></nav><section class="warning"><p>请粘贴或上传脱敏文本/Word，并提供映射表。</p></section>')

        redaction_map = redaction_map_from_json(map_text)
        if redacted_docx_bytes is not None and restore_docx_format:
            return _render_docx_restore_result(redacted_docx_bytes, redacted_filename, redaction_map)
        preview = preview_restore(redacted_text, redaction_map)
    except Exception as exc:
        return _page("还原错误", f'<nav><a href="/">返回</a></nav><section class="warning"><p>{html.escape(str(exc))}</p></section>')

    default_dir = os.path.expanduser("~/Desktop")
    restored_url = _data_download("restored.txt", "text/plain", preview.restored_text)
    restored_rows = "".join(
        f"<tr><td>{html.escape(i.type)}</td><td>{html.escape(i.masked)}</td><td>{html.escape(i.original)}</td></tr>"
        for i in preview.restored_entries
    )
    return _page("还原预览", f"""
        <nav><a href="/">返回首页</a></nav>
        <div class="downloads"><a download="restored.txt" href="{restored_url}" class="btn">下载还原文本</a></div>
        
        <section class="local-save-section" style="border-left: 4px solid var(--accent); background: linear-gradient(135deg, var(--surface) 0%, rgba(26, 122, 109, 0.02) 100%); padding: 18px 24px; border-radius: var(--radius); border: 1px solid var(--border); margin-bottom: 18px; box-shadow: var(--shadow);">
          <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 15px;">
            <div style="flex: 1; min-width: 280px;">
              <h3 style="margin: 0 0 6px 0; font-size: 14px; font-weight: 600; color: var(--ink); display: flex; align-items: center; gap: 6px;">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-folder"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
                本地直接保存 <span class="hint" style="font-weight: normal; font-size: 11px; margin-left: 4px;">(保存至本地任意文件夹)</span>
              </h3>
              <div style="display: flex; gap: 8px; align-items: center; margin-top: 8px;">
                <span class="hint" style="white-space: nowrap; font-weight: 500;">保存路径:</span>
                <input type="text" id="local-save-dir" value="{html.escape(default_dir)}" style="flex: 1; min-width: 200px; padding: 6px 10px; border-radius: 6px; font-family: monospace; font-size: 13px;" placeholder="例如: ~/Desktop">
              </div>
            </div>
            <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px;">
              <button type="button" class="btn btn-sm" onclick="saveToLocalPath([{{filename: 'restored.txt', content: document.getElementById('restored-output').value}}], this)">保存还原文本</button>
            </div>
          </div>
          <script>
            (function(){{
              var savedDir = localStorage.getItem('last_local_save_dir');
              if (savedDir) {{
                var inp = document.getElementById('local-save-dir');
                if (inp) inp.value = savedDir;
              }}
            }})();
          </script>
        </section>
        
        <section class="grid">
          <div><h2>脱敏文本</h2><textarea rows="20" readonly>{html.escape(redacted_text)}</textarea></div>
          <div><h2>还原后</h2><textarea id="restored-output" rows="20" readonly>{html.escape(preview.restored_text)}</textarea></div>
        </section>
        <section>
          <h2>已还原</h2><table><thead><tr><th>类型</th><th>占位符</th><th>原文</th></tr></thead><tbody>{restored_rows}</tbody></table>
          <details><summary>差异预览</summary><pre>{html.escape(preview.diff)}</pre></details>
        </section>
    """)


def _render_docx_restore_result(
    redacted_docx_bytes: bytes,
    redacted_filename: str,
    redaction_map: RedactionMap,
) -> str:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / "redacted.docx"
        output_path = temp_path / "restored.docx"
        input_path.write_bytes(redacted_docx_bytes)
        replacements = restore_docx(input_path, output_path, redaction_map)
        restored_bytes = output_path.read_bytes()

    stem = Path(redacted_filename or "restored.docx").stem
    restored_filename = f"{stem}.restored.docx"
    restored_url = _binary_download(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        restored_bytes,
    )
    restored_rows = "".join(
        f"<tr><td>{html.escape(i.type)}</td><td>{html.escape(i.masked)}</td><td>{html.escape(i.original)}</td></tr>"
        for i in redaction_map.mappings
    )
    return _page("Word 还原完成", f"""
        <nav><a href="/">返回首页</a></nav>
        <div class="downloads">
          <a download="{html.escape(restored_filename)}" href="{restored_url}" class="btn" data-no-intercept="true">下载还原 Word</a>
        </div>
        <section class="info-card">
          <h2>还原完成</h2>
          <p>已按映射表生成保留格式的 Word 文档。</p>
          <p class="hint">替换次数：{replacements}；映射条目：{len(redaction_map.mappings)}。</p>
        </section>
        <section>
          <h2>映射表条目</h2>
          <table><thead><tr><th>类型</th><th>占位符</th><th>原文</th></tr></thead><tbody>{restored_rows}</tbody></table>
        </section>
    """)


def _render_redaction_result(
    title: str,
    original_text: str,
    redacted_text: str,
    redaction_map: RedactionMap,
    review_candidates: list,
    leaks: list,
    warnings: list[str],
    save_dir: str = "",
    discord_thread_url: str = "",
    case_root: str = "",
    case_folder: str = "",
    source_dir: str = "",
) -> str:
    default_dir = save_dir.strip() or os.path.expanduser("~/Desktop")
    map_json = redaction_map_to_json(redaction_map)
    leaks_html = "".join(f"<li><strong>{html.escape(lk.type)}</strong>: <mark>{html.escape(lk.text)}</mark></li>" for lk in leaks)
    warnings_html = "".join(f"<li>{html.escape(w)}</li>" for w in warnings)
    redacted_filename = "redacted.txt"
    redacted_filename_json = json.dumps(redacted_filename, ensure_ascii=False)
    redacted_url = _data_download(redacted_filename, "text/plain", redacted_text)
    map_url = _data_download("redaction_map.json", "application/json", map_json)
    discord_create_section = _discord_create_thread_section(
        discord_thread_url=discord_thread_url,
        case_root=case_root,
        case_folder=case_folder,
        source_dir=source_dir or save_dir,
        filename=redacted_filename,
        textarea_id="redacted-output",
        map_textarea_id="mapping-json-output",
        message_id="discord-create-message",
    )
    discord_section = _discord_send_section(discord_thread_url, redacted_filename, "redacted-output", "discord-message")
    review_html = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{:.2f}</td><td>{}</td></tr>".format(
            html.escape(c.type), html.escape(c.text), html.escape(c.source),
            c.confidence, html.escape(c.reason or ""))
        for c in review_candidates
    )
    return _page(
        title,
        f"""
        <nav><a href="/">返回首页</a></nav>
        <div class="downloads">
          <a download="{html.escape(redacted_filename)}" href="{redacted_url}" class="btn">下载脱敏文本</a>
          <a download="redaction_map.json" href="{map_url}" class="btn btn-secondary">下载 redaction_map</a>
          <button type="button" class="btn btn-secondary btn-sm" onclick="var t=document.getElementById('redacted-output');if(t)navigator.clipboard.writeText(t.value).then(function(){{toast('已复制')}})">复制脱敏文本</button>
        </div>
        
        <section class="local-save-section" style="border-left: 4px solid var(--accent); background: linear-gradient(135deg, var(--surface) 0%, rgba(26, 122, 109, 0.02) 100%); padding: 18px 24px; border-radius: var(--radius); border: 1px solid var(--border); margin-bottom: 18px; box-shadow: var(--shadow);">
          <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 15px;">
            <div style="flex: 1; min-width: 280px;">
              <h3 style="margin: 0 0 6px 0; font-size: 14px; font-weight: 600; color: var(--ink); display: flex; align-items: center; gap: 6px;">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-folder"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
                本地直接保存 <span class="hint" style="font-weight: normal; font-size: 11px; margin-left: 4px;">(保存至本地任意文件夹)</span>
              </h3>
              <div style="display: flex; gap: 8px; align-items: center; margin-top: 8px;">
                <span class="hint" style="white-space: nowrap; font-weight: 500;">保存路径:</span>
                <input type="text" id="local-save-dir" value="{html.escape(default_dir)}" style="flex: 1; min-width: 200px; padding: 6px 10px; border-radius: 6px; font-family: monospace; font-size: 13px;" placeholder="例如: ~/Desktop">
              </div>
            </div>
            <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px;">
              <button type="button" class="btn btn-sm" onclick="saveToLocalPath([{{filename: {html.escape(redacted_filename_json)}, content: document.getElementById('redacted-output').value}}], this)">保存脱敏文本</button>
              <button type="button" class="btn btn-secondary btn-sm" onclick="saveToLocalPath([{{filename: 'redaction_map.json', content: document.getElementById('mapping-json-output').value}}], this)">保存映射表</button>
              <button type="button" class="btn btn-sm" style="background: #e18c12; border-color: #e18c12; color: #fff;" onclick="saveToLocalPath([{{filename: {html.escape(redacted_filename_json)}, content: document.getElementById('redacted-output').value}}, {{filename: 'redaction_map.json', content: document.getElementById('mapping-json-output').value}}], this)">一键保存全部</button>
            </div>
          </div>
          <script>
            (function(){{
              var savedDir = localStorage.getItem('last_local_save_dir');
              var hasPreferredDir = {json.dumps(bool(save_dir.strip()))};
              if (savedDir && !hasPreferredDir) {{
                var inp = document.getElementById('local-save-dir');
                if (inp) inp.value = savedDir;
              }}
            }})();
          </script>
        </section>

        {discord_create_section}
        {discord_section}
        
        {f'<section class="warning"><h2>高危泄漏</h2><ul>{leaks_html}</ul></section>' if leaks_html else ''}
        {f'<section class="notice"><h2>运行提示</h2><ul>{warnings_html}</ul></section>' if warnings_html else ''}
        <section class="grid">
          <div>
            <h2>原文预览 <span class="hint">（高亮部分 = 已替换）</span></h2>
            <div class="highlight-box original-highlight selection-add-source">{_highlight_replaced_text(original_text, redaction_map.mappings)}</div>
          </div>
          <div>
            <h2>脱敏文</h2>
            <textarea id="redacted-output" class="hidden-raw">{html.escape(redacted_text)}</textarea>
            <div class="highlight-box redacted-highlight">{_highlight_replaced_text(redacted_text, redaction_map.mappings, reverse=True)}</div>
          </div>
        </section>
        <section>
          <h2>确认将替换的具体文字</h2>
          <p class="hint">修改表格中的原文或替换词后点「应用表格修改」即可重新脱敏。</p>
          <form id="mapping-edit-form" action="/redact/apply-edited-map" method="post">
            <textarea name="original_text" class="hidden-raw">{html.escape(original_text)}</textarea>
            <textarea name="original_bundle_json" class="hidden-raw"></textarea>
            <textarea id="mapping-json-output" name="original_mapping_json" class="hidden-raw">{html.escape(map_json)}</textarea>
            <input type="hidden" name="save_dir" value="{html.escape(save_dir)}">
            <input type="hidden" name="discord_thread_url" value="{html.escape(discord_thread_url)}">
            <input type="hidden" name="case_root" value="{html.escape(case_root)}">
            <input type="hidden" name="case_folder" value="{html.escape(case_folder)}">
            <input type="hidden" name="source_dir" value="{html.escape(source_dir or save_dir)}">
            <input type="hidden" name="map_version" value="{html.escape(redaction_map.version)}">
            <input type="hidden" name="map_created_at" value="{html.escape(redaction_map.created_at)}">
            <input type="hidden" name="map_mode" value="{html.escape(redaction_map.mode)}">
            <input type="hidden" name="map_source_file" value="{html.escape(redaction_map.source_file or '')}">
            <table>
              <thead><tr><th>类型</th><th>原文（精确匹配）</th><th>替换为</th><th>来源</th><th>置信度</th><th>操作</th></tr></thead>
              <tbody>{_render_mapping_edit_rows(redaction_map)}</tbody>
            </table>
            <button type="button" class="btn btn-secondary btn-sm" onclick="addBlankRow(this)" style="margin-bottom:12px">＋ 新增一行</button>
            <button type="submit" class="btn">应用表格修改/删除</button>
            <button type="submit" formaction="/redact/save-sample" formtarget="save-iframe" class="btn btn-secondary" style="margin-left:8px;">保存为样本</button>
          </form>
        </section>
        {'<section><h2>需人工复核</h2><table><thead><tr><th>类型</th><th>文本</th><th>来源</th><th>置信度</th><th>原因</th></tr></thead><tbody>' + review_html + '</tbody></table></section>' if review_html else ''}
        """,
    )


def _render_batch_redaction_result(
    title: str,
    documents: list[RedactedDocument],
    redaction_map: RedactionMap,
    review_candidates: list,
    leaks: list,
    warnings: list[str],
    save_dir: str = "",
    discord_thread_url: str = "",
    case_root: str = "",
    case_folder: str = "",
    source_dir: str = "",
) -> str:
    default_dir = save_dir.strip() or os.path.expanduser("~/Desktop")
    
    # 构建各个独立文件的脱敏文本列表供 JS 使用
    individual_files = []
    for index, document in enumerate(documents, start=1):
        out_name = f"document-{index}.redacted.txt"
        individual_files.append({"filename": out_name, "content": document.redacted_text})
    individual_files_json = json.dumps(individual_files, ensure_ascii=False)
    
    map_json = redaction_map_to_json(redaction_map)
    bundle_json = _documents_bundle_json(documents)
    combined_redacted = "\n\n".join(d.redacted_text for d in documents)
    leaks_html = "".join(f"<li><strong>{html.escape(lk.type)}</strong>: <mark>{html.escape(lk.text)}</mark></li>" for lk in leaks)
    warnings_html = "".join(f"<li>{html.escape(w)}</li>" for w in warnings)
    map_url = _data_download("redaction_map.json", "application/json", map_json)
    combined_filename = "batch.redacted.txt"
    combined_filename_json = json.dumps(combined_filename, ensure_ascii=False)
    redacted_url = _data_download(combined_filename, "text/plain", combined_redacted)
    discord_create_section = _discord_create_thread_section(
        discord_thread_url=discord_thread_url,
        case_root=case_root,
        case_folder=case_folder,
        source_dir=source_dir or save_dir,
        filename=combined_filename,
        textarea_id="redacted-output",
        map_textarea_id="mapping-json-output",
        message_id="discord-create-message-batch",
    )
    discord_section = _discord_send_section(discord_thread_url, combined_filename, "redacted-output", "discord-message-batch")
    doc_sections = "".join(
        f'<article class="doc-result">'
        f'<h3>{html.escape(d.source_file)}</h3>'
        f'<h4>原文高亮</h4><div class="highlight-box original-highlight selection-add-source">{_highlight_replaced_text(d.original_text, redaction_map.mappings)}</div>'
        f'<h4>脱敏文</h4><div class="highlight-box redacted-highlight">{_highlight_replaced_text(d.redacted_text, redaction_map.mappings, reverse=True)}</div>'
        f'</article>'
        for d in documents
    )
    return _page(
        title,
        f"""
        <nav><a href="/">返回首页</a></nav>
        <div class="downloads">
          <a download="{combined_filename}" href="{redacted_url}" class="btn">下载合并脱敏文本</a>
          <a download="redaction_map.json" href="{map_url}" class="btn btn-secondary">下载统一映射表</a>
          <button type="button" class="btn btn-secondary btn-sm" onclick="var t=document.getElementById('redacted-output');if(t)navigator.clipboard.writeText(t.value).then(function(){{toast('已复制')}})">复制合并文本</button>
        </div>
        
        <textarea id="redacted-output" class="hidden-raw">{html.escape(combined_redacted)}</textarea>
        
        <section class="local-save-section" style="border-left: 4px solid var(--accent); background: linear-gradient(135deg, var(--surface) 0%, rgba(26, 122, 109, 0.02) 100%); padding: 18px 24px; border-radius: var(--radius); border: 1px solid var(--border); margin-bottom: 18px; box-shadow: var(--shadow);">
          <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 15px;">
            <div style="flex: 1; min-width: 280px;">
              <h3 style="margin: 0 0 6px 0; font-size: 14px; font-weight: 600; color: var(--ink); display: flex; align-items: center; gap: 6px;">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-folder"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
                本地直接保存 <span class="hint" style="font-weight: normal; font-size: 11px; margin-left: 4px;">(保存至本地任意文件夹)</span>
              </h3>
              <div style="display: flex; gap: 8px; align-items: center; margin-top: 8px;">
                <span class="hint" style="white-space: nowrap; font-weight: 500;">保存路径:</span>
                <input type="text" id="local-save-dir" value="{html.escape(default_dir)}" style="flex: 1; min-width: 200px; padding: 6px 10px; border-radius: 6px; font-family: monospace; font-size: 13px;" placeholder="例如: ~/Desktop">
              </div>
            </div>
            <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px;">
              <button type="button" class="btn btn-sm" onclick="saveToLocalPath([{{filename: {html.escape(combined_filename_json)}, content: document.getElementById('redacted-output').value}}], this)">保存合并文本</button>
              <button type="button" class="btn btn-secondary btn-sm" onclick="saveToLocalPath([{{filename: 'redaction_map.json', content: document.getElementById('mapping-json-output').value}}], this)">保存统一映射表</button>
              <button type="button" class="btn btn-sm" style="background: #e18c12; border-color: #e18c12; color: #fff;" onclick="saveToLocalPath([{{filename: {html.escape(combined_filename_json)}, content: document.getElementById('redacted-output').value}}, {{filename: 'redaction_map.json', content: document.getElementById('mapping-json-output').value}}].concat(_individualRedactedFiles), this)">一键保存全部</button>
            </div>
          </div>
          <script>
            var _individualRedactedFiles = {individual_files_json};
            (function(){{
              var savedDir = localStorage.getItem('last_local_save_dir');
              var hasPreferredDir = {json.dumps(bool(save_dir.strip()))};
              if (savedDir && !hasPreferredDir) {{
                var inp = document.getElementById('local-save-dir');
                if (inp) inp.value = savedDir;
              }}
            }})();
          </script>
        </section>

        {discord_create_section}
        {discord_section}
        
        {f'<section class="warning"><h2>高危泄漏</h2><ul>{leaks_html}</ul></section>' if leaks_html else ''}
        {f'<section class="notice"><h2>运行提示</h2><ul>{warnings_html}</ul></section>' if warnings_html else ''}
        <section><h2>分文件结果</h2>{doc_sections}</section>
        <section>
          <h2>确认将替换的具体文字</h2>
          <form id="mapping-edit-form" action="/redact/apply-edited-map" method="post">
            <textarea name="original_text" class="hidden-raw"></textarea>
            <textarea name="original_bundle_json" class="hidden-raw">{html.escape(bundle_json)}</textarea>
            <textarea id="mapping-json-output" name="original_mapping_json" class="hidden-raw">{html.escape(map_json)}</textarea>
            <input type="hidden" name="save_dir" value="{html.escape(save_dir)}">
            <input type="hidden" name="discord_thread_url" value="{html.escape(discord_thread_url)}">
            <input type="hidden" name="case_root" value="{html.escape(case_root)}">
            <input type="hidden" name="case_folder" value="{html.escape(case_folder)}">
            <input type="hidden" name="source_dir" value="{html.escape(source_dir or save_dir)}">
            <input type="hidden" name="map_version" value="{html.escape(redaction_map.version)}">
            <input type="hidden" name="map_created_at" value="{html.escape(redaction_map.created_at)}">
            <input type="hidden" name="map_mode" value="{html.escape(redaction_map.mode)}">
            <input type="hidden" name="map_source_file" value="{html.escape(redaction_map.source_file or '')}">
            <table>
              <thead><tr><th>类型</th><th>原文</th><th>替换为</th><th>来源</th><th>置信度</th><th>操作</th></tr></thead>
              <tbody>{_render_mapping_edit_rows(redaction_map)}</tbody>
            </table>
            <button type="button" class="btn btn-secondary btn-sm" onclick="addBlankRow(this)" style="margin-bottom:12px">＋ 新增一行</button>
            <button type="submit" class="btn">应用表格修改/删除到全部文书</button>
            <button type="submit" formaction="/redact/save-sample" formtarget="save-iframe" class="btn btn-secondary" style="margin-left:8px;">保存为样本</button>
          </form>
        </section>
        """,
    )


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
        f'<textarea id="{html.escape(message_id, quote=True)}" rows="2" placeholder="可选：发送附件时附言" style="margin-top:10px;max-width:680px;">脱敏文件已生成，请见附件。</textarea>'
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


def _persist_optional_case_redaction(
    case_root: str,
    case_folder: str,
    discord_thread_url: str,
    documents: list[RedactedDocument],
    redaction_map: RedactionMap,
) -> None:
    has_case_folder = bool(case_folder.strip())
    has_thread_url = bool(discord_thread_url.strip())
    if not has_case_folder and not has_thread_url:
        return
    if has_case_folder and not has_thread_url:
        return
    if not has_case_folder and has_thread_url:
        raise CaseError("填写 Discord 帖子链接时必须同时填写案件文件夹名")
    root = case_root.strip() or str(default_case_root())
    persist_case_redaction(root, case_folder, discord_thread_url, documents, redaction_map)


def _resolve_case_location(upload_source_dir: str, source_files: list[str]) -> dict[str, object]:
    source_dir = upload_source_dir.strip()
    if source_dir:
        source_path = Path(source_dir).expanduser()
        result = {
            "status": "ok",
            "case_folder": source_path.name,
            "case_root": str(source_path.parent),
            "matched_dir": str(source_path),
        }
        result.update(_case_manifest_fields(source_path))
        return result
    suggestion = _suggest_case_location_from_filenames(source_files)
    if suggestion.get("status") == "ok":
        return suggestion
    return {"status": "not_found"}


def _discord_bot_token(config: dict | None = None) -> str:
    config = config if config is not None else load_json_config("LEGAL_REDACTOR_API_CONFIG", "api.local.json")
    token = os.environ.get("LEGAL_REDACTOR_DISCORD_BOT_TOKEN") or config_value(config, "discord_bot_token")
    if not token or token.startswith("optional-"):
        raise RuntimeError("未配置 Discord bot token")
    return str(token)


def _new_discord_request_id() -> str:
    return f"lr_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"


def _case_creation_command(case_folder: str, request_id: str, case_cause: str = "") -> str:
    folder = case_folder.strip()
    return "\n".join(
        [
            f"新建案件，{_case_creation_title(folder, case_cause)}",
            f"请求ID：{request_id.strip() or _new_discord_request_id()}",
            f"案件目录：{folder}",
        ]
    )


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
    return value[:80]


def _discord_command_channel_id() -> str:
    config = load_json_config("LEGAL_REDACTOR_API_CONFIG", "api.local.json")
    return str(
        os.environ.get("LEGAL_REDACTOR_DISCORD_COMMAND_CHANNEL_ID")
        or config_value(config, "discord_command_channel_id")
        or "1501248343823880345"
    )


def _post_discord_channel_message(channel_id: str, content: str) -> dict[str, str]:
    config = load_json_config("LEGAL_REDACTOR_API_CONFIG", "api.local.json")
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
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord 指令发送失败: HTTP {exc.code} {body_text}") from exc
    except OSError as exc:
        raise RuntimeError(f"Discord 指令发送失败: {exc}") from exc
    return {
        "message_id": str(data.get("id", "")),
        "channel_id": str(data.get("channel_id") or channel_id),
    }


def _post_discord_thread_file(thread_id: str, filename: str, content: str, message: str = "") -> dict[str, str]:
    config = load_json_config("LEGAL_REDACTOR_API_CONFIG", "api.local.json")
    token = _discord_bot_token(config)

    message = (message.strip() or "脱敏文件已生成，请见附件。")[:1900]
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
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord 发送失败: HTTP {exc.code} {body_text}") from exc
    except OSError as exc:
        raise RuntimeError(f"Discord 发送失败: {exc}") from exc
    return {
        "message_id": str(data.get("id", "")),
        "channel_id": str(data.get("channel_id", "")),
    }


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


def _suggest_case_location_from_filenames(
    filenames: list[str],
    search_roots: list[Path] | None = None,
) -> dict[str, object]:
    wanted = {Path(str(name)).name for name in filenames if str(name).strip()}
    wanted = {name for name in wanted if name and not name.startswith("._")}
    if not wanted:
        return {"status": "no_filename"}

    roots = search_roots or _case_location_search_roots()
    matches: list[tuple[Path, Path]] = []
    for root in roots:
        for path in _find_matching_files(root, wanted):
            matches.append((path, _case_dir_for_matched_file(root, path)))
        best_case_dir, ambiguous_dirs = _best_case_location(matches, wanted)
        if best_case_dir is not None or ambiguous_dirs:
            break

    best_case_dir, ambiguous_dirs = _best_case_location(matches, wanted)
    if best_case_dir is None:
        return {"status": "not_found"}
    if ambiguous_dirs:
        return {
            "status": "ambiguous",
            "matches": [str(path) for path in ambiguous_dirs[:8]],
        }

    case_dir_path = best_case_dir
    result = {
        "status": "ok",
        "case_folder": case_dir_path.name,
        "case_root": str(case_dir_path.parent),
        "matched_dir": str(case_dir_path),
    }
    result.update(_case_manifest_fields(case_dir_path))
    return result


def _best_case_location(
    matches: list[tuple[Path, Path]],
    wanted: set[str],
) -> tuple[Path | None, list[Path]]:
    if not matches:
        return None, []

    scores: dict[Path, set[str]] = {}
    for file_path, case_dir_path in matches:
        scores.setdefault(case_dir_path.resolve(), set()).add(file_path.name)
    ranked = sorted(scores.items(), key=lambda item: (-len(item[1]), str(item[0])))
    if not ranked:
        return None, []

    best_count = len(ranked[0][1])
    best_dirs = [path for path, names in ranked if len(names) == best_count]
    if len(best_dirs) == 1:
        return best_dirs[0], []
    return None, best_dirs


def _case_dir_for_matched_file(root: Path, path: Path) -> Path:
    root = root.resolve()
    path = path.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError:
        return path.parent.resolve()
    if _looks_like_case_root(root) and len(relative.parts) > 1:
        return (root / relative.parts[0]).resolve()
    return path.parent.resolve()


def _looks_like_case_root(root: Path) -> bool:
    try:
        if root.resolve() == default_case_root().resolve():
            return True
    except OSError:
        pass
    return root.name in {"案件资料", "legal-redactor-cases"}


def _case_manifest_fields(case_dir_path: Path) -> dict[str, str]:
    try:
        manifest = load_manifest(case_dir_path)
    except Exception:
        return {}
    return {
        "discord_thread_url": manifest.discord_thread_url,
        "discord_thread_id": manifest.discord_thread_id,
    }


def _case_location_search_roots() -> list[Path]:
    candidates: list[Path] = [
        default_case_root(),
        Path("~/Documents").expanduser(),
        Path("~/Downloads").expanduser(),
        Path("~/Desktop").expanduser(),
    ]
    volumes = Path("/Volumes")
    if volumes.exists():
        for volume in volumes.iterdir():
            if volume.name.startswith("."):
                continue
            candidates.append(volume)
            case_materials = volume / "案件资料"
            if case_materials.exists():
                candidates.insert(0, case_materials)

    seen: set[Path] = set()
    roots: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved.exists() and resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)
    return roots


def _find_matching_files(root: Path, wanted: set[str], *, max_depth: int = 5, max_entries: int = 30000) -> list[Path]:
    matches: list[Path] = []
    root = root.resolve()
    visited = 0
    for current, dirs, files in os.walk(root):
        visited += len(dirs) + len(files)
        if visited > max_entries:
            break
        current_path = Path(current)
        depth = len(current_path.relative_to(root).parts)
        dirs[:] = [item for item in dirs if not item.startswith(".") and item not in {"__pycache__", ".git", ".venv"}]
        if depth >= max_depth:
            dirs[:] = []
        for filename in files:
            if filename in wanted:
                matches.append(current_path / filename)
    return matches


def _render_mapping_edit_rows(redaction_map: RedactionMap) -> str:
    rows = [_render_mapping_edit_row(i, e) for i, e in enumerate(redaction_map.mappings)]
    rows.append(_render_blank_mapping_row(len(rows)))
    return "".join(rows)


def _render_mapping_edit_row(index: int, entry: MappingEntry) -> str:
    role = entry.role or ""
    restore = "1" if entry.restore_by_default else "0"
    return f"""
        <tr>
          <td><input name="map_type" value="{html.escape(entry.type)}"></td>
          <td><textarea name="map_original" rows="2">{html.escape(entry.original)}</textarea></td>
          <td><textarea name="map_masked" rows="2">{html.escape(entry.masked)}</textarea></td>
          <td>{html.escape(entry.source)}</td>
          <td>{entry.confidence:.2f}</td>
          <td><label class="inline"><input type="checkbox" name="row_delete" value="{index}"> 删除</label>
            <input type="hidden" name="map_role" value="{html.escape(role)}">
            <input type="hidden" name="map_source" value="{html.escape(entry.source)}">
            <input type="hidden" name="map_confidence" value="{entry.confidence}">
            <input type="hidden" name="map_restore_by_default" value="{restore}">
          </td>
        </tr>
    """


def _render_blank_mapping_row(index: int) -> str:
    return f"""
        <tr>
          <td><input name="map_type" value="manual" placeholder="person/org"></td>
          <td><textarea name="map_original" rows="2" placeholder="新增要替换的原文"></textarea></td>
          <td><textarea name="map_masked" rows="2" placeholder="替换为"></textarea></td>
          <td>manual</td>
          <td>1.0</td>
          <td><label class="inline"><input type="checkbox" name="row_delete" value="{index}"> 删除</label>
            <input type="hidden" name="map_role" value="">
            <input type="hidden" name="map_source" value="manual">
            <input type="hidden" name="map_confidence" value="1.0">
            <input type="hidden" name="map_restore_by_default" value="1">
          </td>
        </tr>
    """


async def _read_input_documents(text: str, file: UploadFile | None, files: list[UploadFile]) -> list[InputDocument]:
    documents = []
    if text.strip():
        documents.append(InputDocument(source_file="粘贴文本.txt", text=text))
    
    target_files = []
    if file and file.filename: target_files.append(file)
    if files: target_files.extend([f for f in files if f.filename])
    
    for item in target_files:
        try:
            content = await _read_upload_text(item)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"读取文件 {item.filename} 失败: {exc}") from exc
        documents.append(InputDocument(source_file=item.filename, text=content))
        
    if not documents: raise ValueError("未提供任何待脱敏的文本或文件")
    return documents

def _decode_text_bytes(data: bytes, filename: str) -> str:
    """尝试以不同编码解析上传的二进制文本字节流，主要支持 UTF-8, GB18030, GBK 等。"""
    for encoding in ("utf-8-sig", "gb18030", "gbk", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _suffix_for_filename(filename: str) -> str:
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".txt"


def _docx_bytes_to_text(data: bytes) -> str:
    from docx import Document
    doc = Document(BytesIO(data))
    texts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                texts.extend(p.text for p in cell.paragraphs)
    return "\n".join(texts)


def _legacy_doc_bytes_to_text(data: bytes, filename: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        try:
            result = subprocess.run(
                [
                    "/usr/bin/textutil",
                    "-convert",
                    "txt",
                    "-stdout",
                    "-encoding",
                    "UTF-8",
                    "--",
                    str(tmp_path),
                ],
                check=False,
                capture_output=True,
                timeout=60,
            )
        except FileNotFoundError as exc:
            raise ValueError("读取 .doc 需要 macOS textutil，请先用 Word/WPS 另存为 .docx 或导出为 .txt") from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"读取文件 {filename} 失败: .doc 转文本超时，请先另存为 .docx 或 .txt") from exc
        if result.returncode != 0:
            error = result.stderr.decode("utf-8", errors="replace").strip()
            detail = f": {error}" if error else ""
            raise ValueError(f"读取文件 {filename} 失败: .doc 转文本失败{detail}。请先另存为标准 .docx 或 .txt")
        return result.stdout.decode("utf-8", errors="replace")
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


async def _read_restore_map_text(map_json: str, map_file: UploadFile | None) -> str:
    """读取还原映射表，支持直接粘贴 JSON 和上传 JSON 文件（包括加密映射表）。"""
    map_text = ""
    if map_file and map_file.filename:
        data = await map_file.read()
        try:
            map_text = _decode_text_bytes(data, map_file.filename)
            json.loads(map_text)
        except (json.JSONDecodeError, UnicodeDecodeError):
            from ._crypto import decrypt
            map_text = decrypt(data)
    elif map_json.strip():
        map_text = map_json

    if not map_text:
        raise ValueError("请提供有效的映射表内容或文件")
    return map_text

async def _read_upload_text(file: UploadFile) -> str:
    data = await file.read()
    suffix = _suffix_for_filename(file.filename)
    if suffix in (".txt", ".md"):
        return _decode_text_bytes(data, file.filename)
    if suffix == ".docx":
        try:
            return _docx_bytes_to_text(data)
        except BadZipFile as exc:
            raise ValueError(
                f"读取文件 {file.filename} 失败: 该文件不是有效的 .docx。"
                "如果它是旧版 .doc、RTF、WPS 格式或文件已损坏，请先用 Word/WPS 另存为标准 .docx，或导出为 .txt 后再上传。"
            ) from exc
        except Exception as exc:
            raise ValueError(f"读取文件 {file.filename} 失败: {exc}") from exc
    if suffix == ".doc":
        return _legacy_doc_bytes_to_text(data, file.filename)
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("读取 pdf 需要安装 pypdf：pip install pypdf") from exc
        try:
            reader = PdfReader(BytesIO(data))
            text = []
            for page in reader.pages:
                text.append(page.extract_text() or "")
            return "\n".join(text)
        except Exception as exc:
            raise ValueError(f"读取文件 {file.filename} 失败: PDF 格式无效或文件已损坏") from exc
    return ""

def _redaction_map_from_rows(
    version: str, created_at: str, mode: str, source_file: str,
    map_type: list[str], map_original: list[str], map_masked: list[str],
    map_role: list[str], map_source: list[str], map_confidence: list[str],
    map_restore_by_default: list[str], row_delete: list[str],
) -> RedactionMap:
    deleted = set(row_delete)
    row_count = max(len(map_original), len(map_masked), len(map_type))
    mappings: list[MappingEntry] = []
    for index in range(row_count):
        if str(index) in deleted: continue
        original = _form_list_value(map_original, index).strip()
        masked = _form_list_value(map_masked, index).strip()
        if not original or not masked: continue
        role = _form_list_value(map_role, index).strip() or None
        try:
            confidence = float(_form_list_value(map_confidence, index) or "1.0")
        except ValueError:
            confidence = 1.0
        mappings.append(MappingEntry(
            type=_form_list_value(map_type, index).strip() or "manual",
            original=original, masked=masked, role=role,
            source=_form_list_value(map_source, index).strip() or "manual",
            confidence=confidence,
            restore_by_default=_form_list_value(map_restore_by_default, index) != "0",
        ))
    return RedactionMap(version=version or "1.0", created_at=created_at,
                        mode=mode or "normal", source_file=source_file or None, mappings=mappings)


def _find_mapping_by_original(mappings: list[MappingEntry], original: str) -> MappingEntry | None:
    value = original.strip()
    for entry in mappings:
        if entry.original == value:
            return entry
    return None


def _suggest_manual_mapping_entry(original: str, entity_type: str, existing: list[MappingEntry]) -> MappingEntry:
    value = original.strip()
    masked = _suggest_manual_mask(value, entity_type, existing)
    return MappingEntry(
        type=entity_type,
        original=value,
        masked=masked,
        role=None,
        source="manual_selection",
        confidence=1.0,
        restore_by_default=True,
    )


def _suggest_manual_mask(original: str, entity_type: str, existing: list[MappingEntry]) -> str:
    if entity_type == "person":
        if re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", original):
            surname = original[0]
            return f"{surname}某{_next_person_ordinal(surname, existing)}"
        return f"自然人{_next_mask_ordinal(existing, {'person'}, '自然人')}"
    if entity_type == "organization":
        suffix = _manual_organization_suffix(original)
        return f"{_next_mask_ordinal(existing, {'organization', 'individual_business'}, '')}{suffix}"
    if entity_type == "location":
        suffix = _manual_location_suffix(original)
        return f"{_next_mask_ordinal(existing, {'location', 'grassroots_org'}, '')}{suffix}"
    return f"敏感信息{_next_mask_ordinal(existing, {entity_type}, '敏感信息')}"


def _next_person_ordinal(surname: str, existing: list[MappingEntry]) -> str:
    used = 0
    pattern = re.compile(rf"^{re.escape(surname)}某([甲乙丙丁戊己庚辛壬癸]|\d+)$")
    for entry in existing:
        if entry.type != "person":
            continue
        match = pattern.match(entry.masked)
        if not match:
            continue
        used = max(used, _ordinal_index(match.group(1)))
    return _ordinal_value(used + 1)


def _next_mask_ordinal(existing: list[MappingEntry], entity_types: set[str], prefix: str) -> str:
    used = 0
    pattern = re.compile(rf"^{re.escape(prefix)}([甲乙丙丁戊己庚辛壬癸]|\d+)")
    for entry in existing:
        if entry.type not in entity_types:
            continue
        match = pattern.match(entry.masked)
        if match:
            used = max(used, _ordinal_index(match.group(1)))
    return _ordinal_value(used + 1)


def _ordinal_index(value: str) -> int:
    if value in CN_ORDINALS:
        return CN_ORDINALS.index(value) + 1
    try:
        return int(value)
    except ValueError:
        return 0


def _ordinal_value(index: int) -> str:
    if index <= len(CN_ORDINALS):
        return CN_ORDINALS[index - 1]
    return str(index)


def _manual_organization_suffix(original: str) -> str:
    for suffix in (
        "有限公司", "股份有限公司", "公司", "集团", "银行", "信用社", "合作社",
        "事务所", "律所", "学校", "医院", "法院", "检察院", "委员会",
        "村委会", "居委会", "商行", "经营部", "店", "厂",
    ):
        if original.endswith(suffix):
            if suffix in {"有限公司", "股份有限公司"}:
                return "公司"
            return suffix
    return "机构"


def _manual_location_suffix(original: str) -> str:
    for suffix in (
        "自治区", "自治州", "居民委员会", "村民委员会", "街道", "社区",
        "省", "市", "区", "县", "旗", "镇", "乡", "村", "小区", "项目", "工程",
    ):
        if original.endswith(suffix):
            if suffix in {"居民委员会", "村民委员会"}:
                return suffix
            return suffix
    return "地"


def _form_list_value(values: list[str], index: int) -> str:
    if index >= len(values): return ""
    return values[index]


def _data_download(filename: str, mime: str, content: str) -> str:
    return f"data:{mime};charset=utf-8,{urllib.parse.quote(content)}"


def _binary_download(mime: str, content: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"


def _documents_bundle_json(documents: list[RedactedDocument]) -> str:
    return json.dumps([{"source_file": d.source_file, "text": d.original_text} for d in documents], ensure_ascii=False)


def _documents_from_bundle_json(value: str) -> list[InputDocument]:
    if not value.strip(): return []
    try: payload = json.loads(value)
    except json.JSONDecodeError: return []
    if not isinstance(payload, list): return []
    return [InputDocument(source_file=str(i.get("source_file","")), text=str(i.get("text",""))) for i in payload if isinstance(i, dict)]


def _apply_map_to_documents(pipeline: RedactionPipeline, documents: list[InputDocument], redaction_map: RedactionMap) -> list[RedactedDocument]:
    return [RedactedDocument(source_file=d.source_file, original_text=d.text, redacted_text=pipeline.apply_redaction_map(d.text, redaction_map), leaks=pipeline.scan_high_risk_leaks(pipeline.apply_redaction_map(d.text, redaction_map))) for d in documents]


def _highlight_replaced_text(text: str, entries: list[MappingEntry], *, reverse: bool = False) -> str:
    """生成带 <mark> 高亮的 HTML 文本。

    reverse=False：高亮原文中被替换的词（title 显示替换后的内容）。
    reverse=True：高亮脱敏文本中的占位符（title 显示原文）。
    """
    if not entries:
        return html.escape(text)

    spans: list[tuple[int, int, str, str]] = []
    occupied: list[tuple[int, int]] = []

    sorted_entries = sorted(
        entries, key=lambda e: len(e.masked if reverse else e.original), reverse=True
    )

    for entry in sorted_entries:
        search_key = entry.masked if reverse else entry.original
        if not search_key:
            continue
        tooltip = entry.original if reverse else entry.masked

        pos = 0
        while True:
            idx = text.find(search_key, pos)
            if idx < 0:
                break
            end = idx + len(search_key)
            if not any(not (end <= occ_start or idx >= occ_end) for occ_start, occ_end in occupied):
                spans.append((idx, end, search_key, tooltip))
                occupied.append((idx, end))
            pos = idx + 1

    if not spans:
        return html.escape(text)

    spans.sort(key=lambda s: s[0])

    parts: list[str] = []
    last = 0
    for start, end, display, tooltip_text in spans:
        if start > last:
            parts.append(html.escape(text[last:start]))
        title = f"原文：{tooltip_text}" if reverse else f"→ {tooltip_text}"
        parts.append(f'<mark title="{html.escape(title)}">{html.escape(display)}</mark>')
        last = end

    if last < len(text):
        parts.append(html.escape(text[last:]))

    return "".join(parts)


def _guess_location_mask(text: str) -> str:
    """为无后缀的纯地名（如'石家庄''沧州'）猜测合适的掩码。"""
    # 如果原本就是带后缀的，直接返回通用掩码
    for sfx, mask in [("自治区", "某自治区"), ("自治州", "某自治州"),
                       ("街道", "某街道"), ("省", "某省"), ("市", "某市"),
                       ("区", "某区"), ("县", "某县"), ("镇", "某镇"),
                       ("乡", "某乡"), ("村", "某村")]:
        if text.endswith(sfx):
            return mask
    # 无后缀的地名简称：根据常见模式推测
    if re.fullmatch(r"[一-龥]{2,4}", text):
        return "某市"  # 最常见的地名简称是城市名
    return f"地点"


def _simple_mask(text: str, counters: TypeCounters) -> str:
    """为用户确认的实体生成简单掩码，供增量脱敏使用。"""
    # 公司/机构
    if re.search(r"(公司|集团|厂|店|经营部|商行|事务所|律所|银行|信用社)$", text):
        return f"公司{counters.next('company')}"
    # 地名后缀（必须在自然人检查之前，避免"河南省"被误判为姓名）
    # 注意：长后缀必须在短后缀之前检查，避免"内蒙古自治区"被"区"截断
    if text.endswith("自治区"):
        return "某自治区"
    if text.endswith("自治州"):
        return "某自治州"
    if text.endswith("街道"):
        return "某街道"
    if text.endswith("省"):
        return "某省"
    if text.endswith("市"):
        return "某市"
    if text.endswith("区"):
        return "某区"
    if text.endswith("县"):
        return "某县"
    if text.endswith("镇"):
        return "某镇"
    if text.endswith("乡"):
        return "某乡"
    if text.endswith("村"):
        return "某村"
    # 法院
    if "法院" in text:
        return "某法院"
    # 自然人（2-4字，不含地名后缀）
    if re.fullmatch(r"[一-龥]{2,4}", text):
        return f"自然人{counters.next('person')}"
    # 项目/工程
    if "工程" in text or "项目" in text:
        return f"项目{counters.next('project')}"
    # 其他
    return f"敏感信息{counters.next('other')}"


def _page(title: str, body: str) -> str:
    return f"""
    <!doctype html>
    <html lang="zh-CN">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{html.escape(title)}</title>
      <style>
        :root{{--bg:#fafaf8;--surface:#fff;--border:#e8e5df;--ink:#2c2c2a;--muted:#8a8880;--accent:#1a7a6d;--accent-hover:#156358;--danger:#c53b2e;--danger-bg:#fef4f2;--radius:10px;--radius-sm:7px;--shadow:0 1px 3px rgba(0,0,0,.05)}}
        *,*::before,*::after{{box-sizing:border-box}}
        body{{margin:0;padding:24px;color:var(--ink);background:var(--bg);font:15px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased}}
        main{{max-width:1080px;margin:0 auto}}
        h1{{font-size:22px;font-weight:700;margin:0 0 20px}}
        h2{{font-size:16px;font-weight:600;margin:0 0 12px}}
        section{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);padding:24px;margin-bottom:18px}}
        label{{display:block;font-size:13px;font-weight:500;color:var(--muted);margin:0 0 4px}}
        label.inline{{display:inline;font-size:13px;color:var(--ink);margin:0}}
        textarea{{width:100%;border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 12px;background:var(--bg);font:13px/1.6 "SF Mono","Menlo",monospace;resize:vertical}}
        textarea:focus{{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(26,122,109,.1)}}
        textarea[readonly]{{background:#fff;cursor:default}}
        input[type=text],input[type=url],select{{border:1px solid var(--border);border-radius:var(--radius-sm);padding:7px 10px;font-size:13px;background:var(--bg)}}
        input[type=text]:focus,input[type=url]:focus,select:focus{{outline:none;border-color:var(--accent)}}
        .btn,.downloads a,nav a{{display:inline-flex;align-items:center;gap:4px;border:0;border-radius:var(--radius-sm);padding:9px 18px;font-size:13px;font-weight:500;background:var(--accent);color:#fff;text-decoration:none;cursor:pointer}}
        .btn:hover,.downloads a:hover{{background:var(--accent-hover)}}
        .btn-secondary{{background:var(--ink)}}
        .btn-secondary:hover{{background:#444}}
        .btn-sm{{padding:5px 12px;font-size:12px}}
        table{{width:100%;border-collapse:collapse;font-size:12px}}
        th{{text-align:left;font-weight:600;color:var(--muted);padding:8px;border-bottom:2px solid var(--border);font-size:11px;text-transform:uppercase}}
        td{{padding:8px;border-bottom:1px solid var(--border)}}
        td textarea{{min-width:180px;padding:6px 8px;font-size:12px;resize:vertical}}
        td input[name=map_type]{{width:100px;padding:5px 6px;font-size:12px}}
        .grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
        .row{{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin:10px 0}}
        .row label{{margin:0}}
        .downloads{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 14px}}
        .hint{{color:var(--muted);font-size:12px}}
        .hidden-raw{{display:none}}
        .warning{{border-color:var(--danger)}}
        .notice{{background:var(--danger-bg)}}
        mark{{background:var(--danger-bg);color:var(--danger);padding:1px 3px;border-radius:2px}}
        .highlight-box{{background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 12px;font:13px/1.6 "SF Mono","Menlo",monospace;white-space:pre-wrap;word-wrap:break-word;overflow:auto;max-height:480px;user-select:text}}
        .highlight-box mark{{padding:1px 4px;border-radius:3px;cursor:help;border-bottom:2px solid transparent}}
        .original-highlight mark{{background:#fff3cd;color:#856404;border-bottom-color:#ffc107}}
        .redacted-highlight mark{{background:#d4edda;color:#155724;border-bottom-color:#28a745}}
        nav{{margin-bottom:14px}}
        .toast{{position:fixed;top:18px;right:18px;z-index:9999;background:var(--accent);color:#fff;padding:10px 20px;border-radius:var(--radius-sm);box-shadow:0 4px 20px rgba(0,0,0,.15);opacity:0;transform:translateY(-6px);transition:.2s;font-size:13px;font-weight:500}}
        .toast.show{{opacity:1;transform:translateY(0)}}
        .toast.warn{{background:var(--danger)}}
        .selection-menu{{position:absolute;z-index:10000;display:none;align-items:center;gap:4px;background:#fff;border:1px solid var(--border);border-radius:var(--radius-sm);box-shadow:0 8px 28px rgba(0,0,0,.18);padding:6px}}
        .selection-menu button{{border:0;border-radius:6px;padding:6px 9px;background:var(--bg);color:var(--ink);font-size:12px;cursor:pointer;white-space:nowrap}}
        .selection-menu button:hover{{background:var(--accent);color:#fff}}
        #text-input.dragover{{border-color:var(--accent);border-width:2px;background:rgba(26,122,109,.03)}}
        @media(max-width:768px){{body{{padding:14px}}section{{padding:18px}}.grid{{grid-template-columns:1fr}}}}
      </style>
    </head>
    <body>
      <iframe name="save-iframe" style="display:none"></iframe>
      <div id="toast" class="toast"></div>
      <div id="selection-add-menu" class="selection-menu">
        <button type="button" data-entity-type="person">添加为人名</button>
        <button type="button" data-entity-type="organization">添加为机构</button>
        <button type="button" data-entity-type="location">添加为地名</button>
      </div>
      <main>
        <h1>{html.escape(title)}</h1>
        {body}
      </main>
      <script>
      var _tt;function toast(m,c){{var e=document.getElementById('toast');if(!e)return;e.textContent=m;e.className='toast '+(c||'');clearTimeout(_tt);requestAnimationFrame(function(){{e.classList.add('show');}});_tt=setTimeout(function(){{e.classList.remove('show');}},2500);}}
      window.addEventListener('message',function(e){{if(e.data&&e.data.type==='toast')toast(e.data.msg,e.data.cls==='warn'?'warn':'');}});
      (function(){{var ta=document.getElementById('text-input');if(!ta)return;ta.addEventListener('dragover',function(e){{e.preventDefault();ta.classList.add('dragover');}});ta.addEventListener('dragleave',function(){{ta.classList.remove('dragover');}});ta.addEventListener('drop',function(e){{e.preventDefault();ta.classList.remove('dragover');var f=e.dataTransfer.files[0];if(!f)return;if(['txt','md'].indexOf(f.name.split('.').pop().toLowerCase())<0){{toast('不支持 .'+f.name.split('.').pop(),'warn');return;}}var r=new FileReader();r.onload=function(){{ta.value=r.result;toast('已加载: '+f.name);}};r.readAsText(f,'UTF-8');}});}})();
	      (function(){{
	        var input=document.getElementById('source-files');
	        if(!input)return;
	        input.addEventListener('change',async function(){{
	          var names=Array.prototype.map.call(input.files||[],function(f){{return f.name;}});
	          if(!names.length)return;
	          try{{
	            var resp=await fetch('/api/suggest-case-location',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{filenames:names}})}});
	            var data=await resp.json();
	            if(data.status==='ok'){{
	              var root=document.getElementById('case-root-input');
	              var folder=document.getElementById('case-folder-input');
	              var sourceDir=document.getElementById('upload-source-dir-input');
	              var discordUrl=document.getElementById('discord-thread-url-input');
	              if(root)root.value=data.case_root||'';
	              if(folder){{
	                var current=(folder.value||'').trim();
	                var last=folder.dataset.autoValue||'';
	                if(!current||current===last){{
	                  folder.value=data.case_folder||'';
	                  folder.dataset.autoValue=data.case_folder||'';
	                }}
	              }}
	              if(sourceDir)sourceDir.value=data.matched_dir||'';
	              if(discordUrl&&!discordUrl.value.trim()&&data.discord_thread_url)discordUrl.value=data.discord_thread_url;
	              toast(data.discord_thread_url?'已识别案件目录和 Discord 链接: '+data.case_folder:'已识别案件目录: '+data.case_folder);
	            }}else if(data.status==='ambiguous'){{
	              toast('匹配到多个案件目录，请手动填写案件文件夹名和根目录','warn');
	            }}else if(data.status==='not_found'){{
	              toast('未能自动识别案件目录，请手动填写','warn');
	            }}
	          }}catch(err){{
	            console.debug(err);
	            toast('案件目录自动识别失败','warn');
	          }}
	        }});
	      }})();
      function addBlankRow(btn){{var tb=btn.parentElement.querySelector('tbody');if(!tb)return;var rows=tb.querySelectorAll('tr');var last=rows[rows.length-1];var c=last.cloneNode(true);var n=rows.length;c.querySelectorAll('input,textarea').forEach(function(e){{if(e.name==='row_delete')e.value=n;if(e.name==='map_type')e.value='manual';if(e.name==='map_original'||e.name==='map_masked'||e.name==='map_role')e.value='';if(e.name==='map_source')e.value='manual';if(e.name==='map_confidence')e.value='1.0';if(e.name==='map_restore_by_default')e.value='1';e.checked=false;}});tb.appendChild(c);}}
      function saveRow(idx,btn){{var row=btn.closest('tr');var orig=row.querySelector('[name^=orig_]').value;var masked=row.querySelector('[name^=masked_]').value;fetch('/samples/update/'+idx,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{original:orig,masked:masked}})}}).then(function(r){{return r.json();}}).then(function(d){{toast(d.msg);}});}}
	      function saveNewRow(total,btn){{var act=document.getElementById('new-action').value;var orig=document.getElementById('new-orig').value;var masked=document.getElementById('new-masked').value;if(!orig||!masked){{toast('请填写原文和替换为','warn');return;}}fetch('/samples/add',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{action:act,original:orig,masked:masked}})}}).then(function(r){{return r.json();}}).then(function(d){{toast(d.msg);setTimeout(function(){{location.reload();}},1000);}});}}

	      (function(){{
	        var menu=document.getElementById('selection-add-menu');
	        var selectedText='';
	        function selectionInsideSource(sel){{
	          if(!sel||sel.rangeCount===0)return false;
	          var node=sel.anchorNode;
	          while(node){{
	            if(node.nodeType===1&&node.classList&&node.classList.contains('selection-add-source'))return true;
	            node=node.parentNode;
	          }}
	          return false;
	        }}
	        function hideMenu(){{
	          if(menu)menu.style.display='none';
	        }}
	        document.addEventListener('mouseup',function(){{
	          if(!menu)return;
	          setTimeout(function(){{
	            var sel=window.getSelection();
	            var text=sel?sel.toString().trim():'';
	            if(!text||!selectionInsideSource(sel)||text.length>80){{
	              hideMenu();
	              return;
	            }}
	            selectedText=text.replace(/\\s+/g,' ');
	            var rect=sel.getRangeAt(0).getBoundingClientRect();
	            menu.style.left=Math.max(8,rect.left+window.scrollX)+'px';
	            menu.style.top=Math.max(8,rect.bottom+window.scrollY+6)+'px';
	            menu.style.display='flex';
	          }},0);
	        }});
	        document.addEventListener('mousedown',function(e){{
	          if(menu&&menu.contains(e.target))return;
	          if(e.target&&e.target.closest&&e.target.closest('.selection-add-source'))return;
	          hideMenu();
	        }});
	        if(menu){{
	          menu.addEventListener('click',async function(e){{
	            var btn=e.target&&e.target.closest?e.target.closest('button[data-entity-type]'):null;
	            if(!btn)return;
	            var form=document.getElementById('mapping-edit-form');
	            var mapEl=document.getElementById('mapping-json-output');
	            if(!form||!mapEl){{
	              toast('当前页面不能直接添加映射','warn');
	              hideMenu();
	              return;
	            }}
	            try{{
	              var resp=await fetch('/api/mapping/suggest-entry',{{
	                method:'POST',
	                headers:{{'Content-Type':'application/json'}},
	                body:JSON.stringify({{
	                  selected_text:selectedText,
	                  entity_type:btn.dataset.entityType,
	                  map_json:mapEl.value||''
	                }})
	              }});
	              var data=await resp.json();
	              if(data.status==='exists'){{
	                toast(data.message||'该文字已有映射');
	                hideMenu();
	                return;
	              }}
	              if(!resp.ok||data.status!=='success'){{
	                toast(data.message||'添加映射失败','warn');
	                hideMenu();
	                return;
	              }}
	              appendMappingInputs(form,data.entry);
	              toast('已添加映射：'+data.entry.original+' → '+data.entry.masked);
	              hideMenu();
	              setTimeout(function(){{form.submit();}},120);
	            }}catch(err){{
	              toast('添加映射失败：'+err.message,'warn');
	              hideMenu();
	            }}
	          }});
	        }}
	        function appendHidden(form,name,value){{
	          var input=document.createElement('input');
	          input.type='hidden';
	          input.name=name;
	          input.value=value==null?'':String(value);
	          form.appendChild(input);
	        }}
	        function appendMappingInputs(form,entry){{
	          appendHidden(form,'map_type',entry.type||'manual');
	          appendHidden(form,'map_original',entry.original||'');
	          appendHidden(form,'map_masked',entry.masked||'');
	          appendHidden(form,'map_role',entry.role||'');
	          appendHidden(form,'map_source',entry.source||'manual_selection');
	          appendHidden(form,'map_confidence',entry.confidence==null?'1.0':entry.confidence);
	          appendHidden(form,'map_restore_by_default',entry.restore_by_default===false?'0':'1');
	        }}
	      }})();

	      async function sendRedactedToDiscord(threadUrl, filename, textareaId, messageId, buttonEl) {{
        var textEl = document.getElementById(textareaId);
        var messageEl = document.getElementById(messageId);
        var statusEl = buttonEl && buttonEl.dataset && buttonEl.dataset.statusId ? document.getElementById(buttonEl.dataset.statusId) : null;
        if (!textEl || !textEl.value) {{
          toast('没有可发送的脱敏内容', 'warn');
          if (statusEl) statusEl.textContent = '没有可发送的脱敏内容';
          return;
        }}
        var origText = '';
        if (buttonEl) {{
          buttonEl.disabled = true;
          origText = buttonEl.textContent || buttonEl.innerText;
          buttonEl.textContent = '正在发送...';
        }}
        try {{
          var resp = await fetch('/api/discord/send-redacted', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{
              discord_thread_url: threadUrl,
              filename: filename,
              content: textEl.value,
              message: messageEl ? messageEl.value : ''
            }})
          }});
          var res = await resp.json();
          if (resp.ok && res.status === 'success') {{
            toast('已发送到 Discord 帖子');
            if (statusEl) statusEl.textContent = '已发送到 Discord 帖子';
          }} else {{
            toast(res.message || 'Discord 发送失败', 'warn');
            if (statusEl) statusEl.textContent = res.message || 'Discord 发送失败';
          }}
        }} catch (err) {{
          toast('Discord 发送失败：' + err.message, 'warn');
          if (statusEl) statusEl.textContent = 'Discord 发送失败：' + err.message;
        }} finally {{
          if (buttonEl) {{
            buttonEl.disabled = false;
            buttonEl.textContent = origText;
          }}
        }}
      }}
      document.addEventListener('click', function(e) {{
        var btn = e.target && e.target.closest ? e.target.closest('.discord-send-button') : null;
        if (!btn) return;
        sendRedactedToDiscord(
          btn.dataset.threadUrl || '',
          btn.dataset.filename || 'redacted.txt',
          btn.dataset.textareaId || 'redacted-output',
          btn.dataset.messageId || '',
          btn
        );
      }});

	      function discordWait(ms) {{
	        return new Promise(function(resolve) {{ setTimeout(resolve, ms); }});
	      }}

	      async function waitForBoundDiscordThread(buttonEl, payload, statusEl, linkEl, origText) {{
	        var maxAttempts = 40;
	        for (var attempt = 1; attempt <= maxAttempts; attempt++) {{
	          var resp = await fetch('/api/discord/attach-bound-thread', {{
	            method: 'POST',
	            headers: {{ 'Content-Type': 'application/json' }},
	            body: JSON.stringify(payload)
	          }});
	          var res = await resp.json();
	          if (res.status === 'pending') {{
	            if (statusEl) statusEl.textContent = (res.message || '等待 Hermes 写回 Discord 帖子链接') + '（' + attempt + '/' + maxAttempts + '）';
	            await discordWait(3000);
	            continue;
	          }}
	          if (resp.ok && res.status === 'success') {{
	            toast('已绑定帖子并发送脱敏附件');
	            if (statusEl) statusEl.textContent = '已绑定并发送: ' + res.thread_url;
	            if (linkEl) {{
	              linkEl.href = res.thread_url;
	              linkEl.style.display = 'inline';
	            }}
	            document.querySelectorAll('input[name=discord_thread_url]').forEach(function(inp) {{
	              inp.value = res.thread_url;
	            }});
	            buttonEl.textContent = '已绑定并发送';
	            buttonEl.disabled = true;
	            return;
	          }}
	          throw new Error(res.message || 'Discord 附件发送失败');
	        }}
	        if (statusEl) statusEl.textContent = '等待超时：Hermes 尚未写回帖子链接，可稍后再点一次继续绑定';
	        toast('等待 Hermes 写回超时', 'warn');
	        buttonEl.textContent = origText;
	        buttonEl.disabled = false;
	      }}

		      async function createDiscordThread(buttonEl) {{
		        var textEl = document.getElementById(buttonEl.dataset.textareaId || 'redacted-output');
		        var mapEl = document.getElementById(buttonEl.dataset.mapTextareaId || 'mapping-json-output');
		        var messageEl = document.getElementById(buttonEl.dataset.messageId || '');
		        var causeEl = document.getElementById(buttonEl.dataset.caseCauseId || '');
		        var statusEl = document.getElementById(buttonEl.dataset.statusId || '');
	        var linkEl = document.getElementById(buttonEl.dataset.linkId || '');
        if (!textEl || !textEl.value) {{
          toast('没有可发送的脱敏内容', 'warn');
          return;
        }}
        if (!mapEl || !mapEl.value) {{
          toast('缺少映射表，无法绑定案件', 'warn');
          return;
        }}
	        var origText = buttonEl.textContent || buttonEl.innerText;
	        buttonEl.disabled = true;
	        buttonEl.textContent = '正在请求 Hermes...';
	        if (statusEl) statusEl.textContent = '';
	        var payload = {{
	          case_root: buttonEl.dataset.caseRoot || '',
	          case_folder: buttonEl.dataset.caseFolder || '',
		          source_dir: buttonEl.dataset.sourceDir || '',
		          case_cause: causeEl ? causeEl.value : '',
		          filename: buttonEl.dataset.filename || 'redacted.txt',
	          content: textEl.value,
	          map_json: mapEl.value,
	          message: messageEl ? messageEl.value : ''
	        }};
	        try {{
	          var resp = await fetch('/api/discord/create-thread', {{
	            method: 'POST',
	            headers: {{ 'Content-Type': 'application/json' }},
		            body: JSON.stringify({{
		              case_folder: payload.case_folder,
		              case_cause: payload.case_cause
		            }})
	          }});
	          var res = await resp.json();
	          if (resp.ok && res.status === 'pending') {{
	            toast('已发送 Hermes 建帖请求');
	            if (statusEl) statusEl.textContent = (res.message || '等待 Hermes 写回 Discord 帖子链接') + (res.request_id ? '：' + res.request_id : '');
	            buttonEl.textContent = '等待 Hermes 回写...';
	            await waitForBoundDiscordThread(buttonEl, payload, statusEl, linkEl, origText);
	          }} else {{
	            toast(res.message || 'Hermes 建帖请求失败', 'warn');
	            if (statusEl) statusEl.textContent = res.message || 'Hermes 建帖请求失败';
	            buttonEl.textContent = origText;
	            buttonEl.disabled = false;
	          }}
	        }} catch (err) {{
	          toast('Hermes 建帖/绑定失败：' + err.message, 'warn');
	          if (statusEl) statusEl.textContent = 'Hermes 建帖/绑定失败：' + err.message;
	          buttonEl.textContent = origText;
	          buttonEl.disabled = false;
	        }}
	      }}
      document.addEventListener('click', function(e) {{
        var btn = e.target && e.target.closest ? e.target.closest('.discord-create-thread-button') : null;
        if (!btn) return;
        createDiscordThread(btn);
      }});

      // 本地直接保存 API 调用
      async function saveToLocalPath(files, buttonEl) {{
        var dirInput = document.getElementById('local-save-dir');
        if (!dirInput) {{
          toast('系统错误：找不到路径输入框', 'warn');
          return;
        }}
        var directory = dirInput.value.trim();
        if (!directory) {{
          toast('请输入或粘贴保存目录路径！', 'warn');
          dirInput.focus();
          return;
        }}
        
        if (buttonEl) {{
          buttonEl.disabled = true;
          var origText = buttonEl.textContent || buttonEl.innerText;
          buttonEl.textContent = '正在保存...';
        }}
        
        try {{
          var resp = await fetch('/api/save-to-local', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{
              directory: directory,
              files: files
            }})
          }});
          var res = await resp.json();
          if (resp.ok && res.status === 'success') {{
            toast('文件已成功保存到本地！');
            localStorage.setItem('last_local_save_dir', res.directory);
            document.querySelectorAll('#local-save-dir').forEach(function(inp) {{
              inp.value = res.directory;
            }});
          }} else {{
            toast(res.message || '保存失败', 'warn');
          }}
        }} catch (err) {{
          console.error(err);
          toast('网络或系统错误：' + err.message, 'warn');
        }} finally {{
          if (buttonEl) {{
            buttonEl.disabled = false;
            buttonEl.textContent = origText;
          }}
        }}
      }}

      // 全局拦截下载链接点击，使用 showSaveFilePicker 选择自定义路径
      document.addEventListener('click', async function(e) {{
        var target = e.target;
        while (target && target.tagName !== 'A') {{
          target = target.parentElement;
        }}
        if (target && target.hasAttribute('download')) {{
          if (target.dataset.noIntercept === 'true') {{
            return;
          }}
          if ('showSaveFilePicker' in window) {{
            e.preventDefault();
            var filename = target.getAttribute('download');
            var href = target.getAttribute('href');
            var contentText = "";
            var mimeType = "text/plain";
            
            if (href.indexOf('data:') === 0) {{
              var commaIdx = href.indexOf(',');
              if (commaIdx >= 0) {{
                var header = href.substring(0, commaIdx);
                var mimeMatch = header.match(/data:([^;]+)/);
                if (mimeMatch) {{
                  mimeType = mimeMatch[1];
                }}
                contentText = decodeURIComponent(href.substring(commaIdx + 1));
              }}
            }} else {{
              try {{
                var resp = await fetch(href);
                contentText = await resp.text();
              }} catch(err) {{
                console.error(err);
                window.location.href = href;
                return;
              }}
            }}
            
            // 规范化 MIME 类型，防止带有 ;charset= 等参数触发浏览器原生异常
            var cleanMimeType = mimeType.split(';')[0].trim();
            if (cleanMimeType !== 'application/json' && cleanMimeType !== 'text/plain') {{
              cleanMimeType = filename.endsWith('.json') ? 'application/json' : 'text/plain';
            }}
            
            try {{
              const options = {{
                suggestedName: filename,
                types: [{{
                  description: cleanMimeType === 'application/json' ? 'JSON 映射表' : '文本文档',
                  accept: {{
                    [cleanMimeType]: [cleanMimeType === 'application/json' ? '.json' : '.txt']
                  }}
                }}]
              }};
              const handle = await window.showSaveFilePicker(options);
              const writable = await handle.createWritable();
              await writable.write(contentText);
              await writable.close();
              toast('保存成功！');
            }} catch (err) {{
              if (err.name !== 'AbortError') {{
                console.error('File System Access API error:', err);
                // 降级为原生下载
                var tempLink = document.createElement('a');
                tempLink.href = href;
                tempLink.download = filename;
                tempLink.dataset.noIntercept = 'true';
                document.body.appendChild(tempLink);
                tempLink.click();
                document.body.removeChild(tempLink);
              }}
            }}
          }}
        }}
      }});
      </script>
    </body>
    </html>"""
