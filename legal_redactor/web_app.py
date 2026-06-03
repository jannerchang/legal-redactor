from __future__ import annotations

import html
import json
import os
import re
import urllib.parse
from dataclasses import dataclass, replace
from io import BytesIO

from .config import PipelineConfig
from .counters import TypeCounters
from .io import is_encrypted_map, load_redaction_map_encrypted, redaction_map_from_json, redaction_map_to_json
from .models import MappingEntry, RedactedDocument, RedactionMap
from .pipeline import RedactionPipeline
from .restore import preview_restore

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


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    from ._samples import load_all_samples
    sample_lookup, sample_blacklist = load_all_samples()
    sample_info = ""

    return _page(
        "本地法律文书脱敏系统",
        sample_info + """
        <section>
          <h2>脱敏</h2>
          <form action="/redact" method="post" enctype="multipart/form-data">
            <label>粘贴文本</label>
            <textarea name="text" id="text-input" rows="12" placeholder="粘贴文书原文，或拖拽 txt/md/docx/pdf 文件到此处"></textarea>
            <label>或上传 txt / md / docx / pdf（可多选）</label>
            <input type="file" name="files" accept=".txt,.md,.docx,.pdf" multiple>
            <div class="row">
              <label>脱敏策略</label>
              <select name="profile">
                <option value="standard" selected>标准：人名+地名+机构+敏感编号</option>
                <option value="minimal">最小：仅人名+地名+身份证+手机号</option>
                <option value="strong">强脱敏：全部含案号+地址+金额+日期</option>
              </select>
              <input type="hidden" name="enable_llm" value="1">
            </div>
            <label style="display:flex; align-items:center; gap:8px; margin-top:12px; margin-bottom:12px; cursor:pointer;">
              <input type="checkbox" name="enable_samples" value="1" checked style="width:auto; margin:0;">
              <span>使用样本库（利用历史黑名单与正样本）</span>
            </label>
            <label>分析模型</label>
            <select name="llm_mode">
              <option value="max-effect" selected>Qwen3 30B (最高准确率)</option>
              <option value="balanced">Qwen2.5 7B (快速)</option>
              <option value="off">关闭 (仅使用正则与启发式规则)</option>
            </select>
            <label>或自定义模型</label>
            <input type="text" name="model" placeholder="如 qwen3:8b / qwen2.5:7b" style="max-width:260px">
            <label>已有映射表（保持替换一致性，选填，支持粘贴JSON或上传文件）</label>
            <textarea name="base_map_json" rows="3" placeholder="粘贴已有映射表 JSON（可选）"></textarea>
            <input type="file" name="base_map_file" accept=".json,.enc">
            <button type="submit" class="btn">一键脱敏</button>
          </form>
        </section>
        <section>
          <h2>还原</h2>
          <form action="/restore/preview" method="post" enctype="multipart/form-data">
            <label>粘贴脱敏后的文本</label>
            <textarea name="text" rows="6" placeholder="粘贴脱敏后的文书"></textarea>
            <label>或上传脱敏文本</label>
            <input type="file" name="file" accept=".txt,.md">
            <label>粘贴或上传映射表（支持加密文件）</label>
            <textarea name="map_json" rows="4" placeholder="粘贴 redaction_map.json"></textarea>
            <input type="file" name="map_file" accept=".json,.enc">
            <label><input type="checkbox" name="restore_all" value="1"> 完整还原（含身份证、手机号等高敏字段）</label>
            <button type="submit" class="btn btn-secondary">预览还原</button>
          </form>
        </section>
        """,
    )

@app.post("/analyze", response_class=HTMLResponse)
async def analyze_page(
    text: str = Form(default=""),
    profile: str = Form(default="standard"),
    llm_mode: str = Form(default="max-effect"),
    enable_llm: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] = File(default=[]),
) -> str:
    try:
        documents = await _read_input_documents(text, file, files)
    except ValueError as exc:
        return _page("上传失败", str(exc))
        
    config = PipelineConfig.from_llm_mode(llm_mode if enable_llm else "off", profile_name=profile)
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
    profile = form.get("profile", "standard")
    llm_mode = form.get("llm_mode", "max-effect")
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
    profile: str = Form(default="standard"),
    llm_mode: str = Form(default="max-effect"),
    enable_llm: str | None = Form(default=None),
    model: str = Form(default=""),
    enable_samples: str | None = Form(default=None),
    base_map_json: str = Form(default=""),
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

    config = PipelineConfig.from_llm_mode(
        llm_mode if enable_llm else "off",
        profile_name=profile,
        model=model or None,
    )
    config = replace(config, enable_sample_library=bool(enable_samples))
    pipeline = RedactionPipeline(config=config)
    if len(documents) > 1:
        result = pipeline.redact_many([(item.source_file, item.text) for item in documents], base_redaction_map=base_redaction_map)
        return _render_batch_redaction_result("脱敏结果", result.documents, result.redaction_map, result.review_candidates, result.leaks, result.warnings)
    
    result = pipeline.redact(documents[0].text, source_file=documents[0].source_file, base_redaction_map=base_redaction_map)
    return _render_redaction_result("脱敏结果", result.original_text, result.redacted_text, result.redaction_map, result.review_candidates, result.leaks, result.warnings)


@app.post("/redact/apply-map", response_class=HTMLResponse)
async def apply_map_page(
    original_text: str = Form(...),
    map_json: str = Form(...),
    original_bundle_json: str = Form(default=""),
    mode: str = Form(default="standard"),
) -> str:
    try:
        redaction_map = redaction_map_from_json(map_json)
    except Exception as exc:
        return _page("映射表解析失败", f"错误详情: {exc}")

    pipeline = RedactionPipeline(config=PipelineConfig(redaction_profile=RedactionProfile.from_preset(mode)))
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
        return _render_batch_redaction_result("编辑映射后结果", redacted_documents, redaction_map, [], leaks, ["已手动调整映射表。"])
    redacted_text = pipeline.apply_redaction_map(original_text, redaction_map)
    leaks = pipeline.scan_high_risk_leaks(redacted_text)
    return _render_redaction_result("编辑映射后结果", original_text, redacted_text, redaction_map, [], leaks, ["已手动调整映射表。"])


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

    from ._samples import save_sample_auto

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
    for i_str in deleted:
        try:
            i = int(i_str)
            if i < len(map_original):
                orig = map_original[i].strip()
                if orig and orig not in processed:
                    entries.append({"action": "delete", "type": map_type[i] if i < len(map_type) else "other", "original": orig})
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
        return HTMLResponse('<script>parent.postMessage({type:"toast",msg:"无变化，未追加"},"*")</script>')

    try:
        save_sample_auto(entries, source=map_source_file or "web_ui")
    except Exception as exc:
        return HTMLResponse(f'<script>parent.postMessage({{type:"toast",msg:"保存失败:{html.escape(str(exc))}",cls:"warn"}},"*")</script>')

    added = len(entries)
    new_count = sum(1 for e in entries if e["action"] in ("add", "modify"))
    del_count = sum(1 for e in entries if e["action"] == "delete")
    msg = f'已追加 {added} 条 | 匹配 {new_count} | 黑名单 {del_count}'
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
    from ._samples import _auto_sample_path
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
        entries[idx] = e
        data["entries"] = entries
        filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return JSONResponse({"msg": "已保存"})
    return JSONResponse({"msg": "索引无效"}, status_code=400)


@app.post("/samples/add")
async def add_sample_entry(request: Request) -> JSONResponse:
    from ._samples import _auto_sample_path
    body = await request.json()
    action = body.get("action", "add")
    orig = body.get("original", "").strip()
    masked = body.get("masked", "").strip()
    if not orig:
        return JSONResponse({"msg": "原文不能为空"}, status_code=400)
    filepath = _auto_sample_path()
    data = {}
    if filepath.exists():
        data = json.loads(filepath.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    if action == "delete":
        entries.append({"action": "delete", "type": "manual", "original": orig})
    else:
        entries.append({"action": "add", "type": "manual", "original": orig, "masked": masked})
    data["entries"] = entries
    data["total"] = len(entries)
    filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return JSONResponse({"msg": f"已添加 {len(entries)} 条"})


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
    restore_all: str | None = Form(default=None),
) -> str:
    try:
        redacted_text = text.strip()
        if file and file.filename:
            data = await file.read()
            redacted_text = _decode_text_bytes(data, file.filename)
        map_text = await _read_restore_map_text(map_json, map_file)

        if not map_text or not redacted_text:
            return _page("参数缺失", '<nav><a href="/">返回</a></nav><section class="warning"><p>请粘贴脱敏文本和映射表。</p></section>')

        redaction_map = redaction_map_from_json(map_text)
        preview = preview_restore(redacted_text, redaction_map, restore_all=bool(restore_all))
    except Exception as exc:
        return _page("还原错误", f'<nav><a href="/">返回</a></nav><section class="warning"><p>{html.escape(str(exc))}</p></section>')

    default_dir = os.path.expanduser("~/Desktop")
    restored_url = _data_download("restored.txt", "text/plain", preview.restored_text)
    restored_rows = "".join(
        f"<tr><td>{html.escape(i.type)}</td><td>{html.escape(i.masked)}</td><td>{html.escape(i.original)}</td></tr>"
        for i in preview.restored_entries
    )
    skipped_rows = "".join(
        f"<tr><td>{html.escape(i.type)}</td><td>{html.escape(i.masked)}</td><td>{html.escape(i.original)}</td></tr>"
        for i in preview.skipped_entries
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
          <h2>已跳过（高敏字段）</h2><table><thead><tr><th>类型</th><th>占位符</th><th>原文</th></tr></thead><tbody>{skipped_rows}</tbody></table>
          <details><summary>差异预览</summary><pre>{html.escape(preview.diff)}</pre></details>
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
) -> str:
    default_dir = os.path.expanduser("~/Desktop")
    map_json = redaction_map_to_json(redaction_map)
    leaks_html = "".join(f"<li><strong>{html.escape(lk.type)}</strong>: <mark>{html.escape(lk.text)}</mark></li>" for lk in leaks)
    warnings_html = "".join(f"<li>{html.escape(w)}</li>" for w in warnings)
    redacted_url = _data_download("redacted.txt", "text/plain", redacted_text)
    map_url = _data_download("redaction_map.json", "application/json", map_json)
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
          <a download="redacted.txt" href="{redacted_url}" class="btn">下载脱敏文本</a>
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
              <button type="button" class="btn btn-sm" onclick="saveToLocalPath([{{filename: 'redacted.txt', content: document.getElementById('redacted-output').value}}], this)">保存脱敏文本</button>
              <button type="button" class="btn btn-secondary btn-sm" onclick="saveToLocalPath([{{filename: 'redaction_map.json', content: document.getElementById('mapping-json-output').value}}], this)">保存映射表</button>
              <button type="button" class="btn btn-sm" style="background: #e18c12; border-color: #e18c12; color: #fff;" onclick="saveToLocalPath([{{filename: 'redacted.txt', content: document.getElementById('redacted-output').value}}, {{filename: 'redaction_map.json', content: document.getElementById('mapping-json-output').value}}], this)">一键保存全部</button>
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
        
        {f'<section class="warning"><h2>高危泄漏</h2><ul>{leaks_html}</ul></section>' if leaks_html else ''}
        {f'<section class="notice"><h2>运行提示</h2><ul>{warnings_html}</ul></section>' if warnings_html else ''}
        <section class="grid">
          <div>
            <h2>原文预览 <span class="hint">（高亮部分 = 已替换）</span></h2>
            <div class="highlight-box original-highlight">{_highlight_replaced_text(original_text, redaction_map.mappings)}</div>
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
          <form action="/redact/apply-edited-map" method="post">
            <textarea name="original_text" class="hidden-raw">{html.escape(original_text)}</textarea>
            <textarea name="original_bundle_json" class="hidden-raw"></textarea>
            <textarea id="mapping-json-output" name="original_mapping_json" class="hidden-raw">{html.escape(map_json)}</textarea>
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
) -> str:
    default_dir = os.path.expanduser("~/Desktop")
    
    # 构建各个独立文件的脱敏文本列表供 JS 使用
    individual_files = []
    for d in documents:
        base, ext = os.path.splitext(d.source_file)
        if not ext:
            ext = ".txt"
        out_name = f"{base}_redacted{ext}"
        individual_files.append({"filename": out_name, "content": d.redacted_text})
    individual_files_json = json.dumps(individual_files, ensure_ascii=False)
    
    map_json = redaction_map_to_json(redaction_map)
    bundle_json = _documents_bundle_json(documents)
    combined_redacted = "\n\n".join(d.redacted_text for d in documents)
    leaks_html = "".join(f"<li><strong>{html.escape(lk.type)}</strong>: <mark>{html.escape(lk.text)}</mark></li>" for lk in leaks)
    warnings_html = "".join(f"<li>{html.escape(w)}</li>" for w in warnings)
    map_url = _data_download("redaction_map.json", "application/json", map_json)
    redacted_url = _data_download("batch_redacted.txt", "text/plain", combined_redacted)
    doc_sections = "".join(
        f'<article class="doc-result">'
        f'<h3>{html.escape(d.source_file)}</h3>'
        f'<h4>原文高亮</h4><div class="highlight-box original-highlight">{_highlight_replaced_text(d.original_text, redaction_map.mappings)}</div>'
        f'<h4>脱敏文</h4><div class="highlight-box redacted-highlight">{_highlight_replaced_text(d.redacted_text, redaction_map.mappings, reverse=True)}</div>'
        f'</article>'
        for d in documents
    )
    return _page(
        title,
        f"""
        <nav><a href="/">返回首页</a></nav>
        <div class="downloads">
          <a download="batch_redacted.txt" href="{redacted_url}" class="btn">下载合并脱敏文本</a>
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
              <button type="button" class="btn btn-sm" onclick="saveToLocalPath([{{filename: 'batch_redacted.txt', content: document.getElementById('redacted-output').value}}], this)">保存合并文本</button>
              <button type="button" class="btn btn-secondary btn-sm" onclick="saveToLocalPath([{{filename: 'redaction_map.json', content: document.getElementById('mapping-json-output').value}}], this)">保存统一映射表</button>
              <button type="button" class="btn btn-sm" style="background: #e18c12; border-color: #e18c12; color: #fff;" onclick="saveToLocalPath([{{filename: 'batch_redacted.txt', content: document.getElementById('redacted-output').value}}, {{filename: 'redaction_map.json', content: document.getElementById('mapping-json-output').value}}].concat(_individualRedactedFiles), this)">一键保存全部</button>
            </div>
          </div>
          <script>
            var _individualRedactedFiles = {individual_files_json};
            (function(){{
              var savedDir = localStorage.getItem('last_local_save_dir');
              if (savedDir) {{
                var inp = document.getElementById('local-save-dir');
                if (inp) inp.value = savedDir;
              }}
            }})();
          </script>
        </section>
        
        {f'<section class="warning"><h2>高危泄漏</h2><ul>{leaks_html}</ul></section>' if leaks_html else ''}
        {f'<section class="notice"><h2>运行提示</h2><ul>{warnings_html}</ul></section>' if warnings_html else ''}
        <section><h2>分文件结果</h2>{doc_sections}</section>
        <section>
          <h2>确认将替换的具体文字</h2>
          <form action="/redact/apply-edited-map" method="post">
            <textarea name="original_text" class="hidden-raw"></textarea>
            <textarea name="original_bundle_json" class="hidden-raw">{html.escape(bundle_json)}</textarea>
            <textarea id="mapping-json-output" name="original_mapping_json" class="hidden-raw">{html.escape(map_json)}</textarea>
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
        content = await _read_upload_text(item)
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
    suffix = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ".txt"
    if suffix in (".txt", ".md"):
        return _decode_text_bytes(data, file.filename)
    if suffix == ".docx":
        from docx import Document
        doc = Document(BytesIO(data))
        return "\n".join([p.text for p in doc.paragraphs])
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("读取 pdf 需要安装 pypdf：pip install pypdf") from exc
        reader = PdfReader(BytesIO(data))
        text = []
        for page in reader.pages:
            text.append(page.extract_text() or "")
        return "\n".join(text)
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


def _form_list_value(values: list[str], index: int) -> str:
    if index >= len(values): return ""
    return values[index]


def _data_download(filename: str, mime: str, content: str) -> str:
    return f"data:{mime};charset=utf-8,{urllib.parse.quote(content)}"


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
        input[type=text],select{{border:1px solid var(--border);border-radius:var(--radius-sm);padding:7px 10px;font-size:13px;background:var(--bg)}}
        input[type=text]:focus,select:focus{{outline:none;border-color:var(--accent)}}
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
        #text-input.dragover{{border-color:var(--accent);border-width:2px;background:rgba(26,122,109,.03)}}
        @media(max-width:768px){{body{{padding:14px}}section{{padding:18px}}.grid{{grid-template-columns:1fr}}}}
      </style>
    </head>
    <body>
      <iframe name="save-iframe" style="display:none"></iframe>
      <div id="toast" class="toast"></div>
      <main>
        <h1>{html.escape(title)}</h1>
        {body}
      </main>
      <script>
      var _tt;function toast(m,c){{var e=document.getElementById('toast');if(!e)return;e.textContent=m;e.className='toast '+(c||'');clearTimeout(_tt);requestAnimationFrame(function(){{e.classList.add('show');}});_tt=setTimeout(function(){{e.classList.remove('show');}},2500);}}
      window.addEventListener('message',function(e){{if(e.data&&e.data.type==='toast')toast(e.data.msg,e.data.cls==='warn'?'warn':'');}});
      (function(){{var ta=document.getElementById('text-input');if(!ta)return;ta.addEventListener('dragover',function(e){{e.preventDefault();ta.classList.add('dragover');}});ta.addEventListener('dragleave',function(){{ta.classList.remove('dragover');}});ta.addEventListener('drop',function(e){{e.preventDefault();ta.classList.remove('dragover');var f=e.dataTransfer.files[0];if(!f)return;if(['txt','md'].indexOf(f.name.split('.').pop().toLowerCase())<0){{toast('不支持 .'+f.name.split('.').pop(),'warn');return;}}var r=new FileReader();r.onload=function(){{ta.value=r.result;toast('已加载: '+f.name);}};r.readAsText(f,'UTF-8');}});}})();
      function addBlankRow(btn){{var tb=btn.parentElement.querySelector('tbody');if(!tb)return;var rows=tb.querySelectorAll('tr');var last=rows[rows.length-1];var c=last.cloneNode(true);var n=rows.length;c.querySelectorAll('input,textarea').forEach(function(e){{if(e.name==='row_delete')e.value=n;if(e.name==='map_type')e.value='manual';if(e.name==='map_original'||e.name==='map_masked'||e.name==='map_role')e.value='';if(e.name==='map_source')e.value='manual';if(e.name==='map_confidence')e.value='1.0';if(e.name==='map_restore_by_default')e.value='1';e.checked=false;}});tb.appendChild(c);}}
      function saveRow(idx,btn){{var row=btn.closest('tr');var orig=row.querySelector('[name^=orig_]').value;var masked=row.querySelector('[name^=masked_]').value;fetch('/samples/update/'+idx,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{original:orig,masked:masked}})}}).then(function(r){{return r.json();}}).then(function(d){{toast(d.msg);}});}}
      function saveNewRow(total,btn){{var act=document.getElementById('new-action').value;var orig=document.getElementById('new-orig').value;var masked=document.getElementById('new-masked').value;if(!orig||!masked){{toast('请填写原文和替换为','warn');return;}}fetch('/samples/add',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{action:act,original:orig,masked:masked}})}}).then(function(r){{return r.json();}}).then(function(d){{toast(d.msg);setTimeout(function(){{location.reload();}},1000);}});}}

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

