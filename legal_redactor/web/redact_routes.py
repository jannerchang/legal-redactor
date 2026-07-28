"""HTTP handlers for analyze / redact / apply-map flows."""
from __future__ import annotations

import asyncio
import html
import json
from dataclasses import replace
from typing import Any

from . import deps
from .deps import (
    DEFAULT_MODEL_ID,
    ExcelFormulaLeakError,
    File,
    Form,
    MappingEntry,
    PipelineConfig,
    RecognitionRunStats,
    RedactedDocument,
    RedactionMap,
    Request,
    TypeCounters,
    UploadFile,
    _page,
    redaction_map_from_json,
    redaction_map_to_json,
    render_home_page,
    sort_mapping_entries,
)
from ..cases import CaseError, default_case_root
from .models import InputDocument
from . import status_ops as status_ops
from .documents import (
    _apply_map_to_documents,
    _documents_from_bundle_json,
    _excel_warnings,
    _read_input_documents,
    _read_restore_map_text,
    _render_output_document,
)
from .mapping_ops import (
    _entity_group_is_noise,
    _guess_location_mask,
    _redaction_map_from_rows,
    _renumber_mapping_placeholders,
    _sanitize_redaction_map,
    _simple_mask,
)
from . import workflow as workflow
from .case_location import _is_default_case_root_value, _resolve_case_location
from .redact_render import (
    _render_audit_dashboard,
    _render_batch_redaction_result,
    _render_redaction_result,
    _recognition_stats_from_analysis,
)

# Re-export render helpers so ``web_app`` and tests can import from redact_routes
# or the facade without churn. Prefer ``redact_render`` for new code.
from .redact_render import (  # noqa: F401
    _recognition_reason_label,
    _render_recognition_stats,
)

def index() -> str:
    sample_info = ""
    status_panel = status_ops._render_status_panel(status_ops._status_payload())
    default_root_str = str(default_case_root())
    return render_home_page(
        status_panel,
        sample_info,
        default_root_str,
        status_ops._available_model_options(),
        DEFAULT_MODEL_ID,
    )


async def analyze_page(
    text: str = Form(default=""),
    llm_mode: str = Form(default="max-effect"),
    recognition_mode: str = Form(default="full_document"),
    model: str = Form(default=DEFAULT_MODEL_ID),
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] = File(default=[]),
) -> str:
    try:
        documents = await _read_input_documents(text, file, files)
    except ValueError as exc:
        return _page("上传失败", str(exc))

    profile = "standard"
    try:
        config, warnings = status_ops._pipeline_config_for_model_status(
            profile=profile,
            llm_mode=llm_mode,
            model=model,
            recognition_mode=recognition_mode,
        )
    except deps.RecognitionUnavailableError as exc:
        return _page("识别不可用", workflow._redaction_failure_body(exc))
    pipeline = deps.RedactionPipeline(config=config)

    # 执行语义审计（后台线程，避免阻塞 /health 等轻量请求）
    raw_text = "\n\n".join(doc.text for doc in documents)
    try:
        analysis = await asyncio.to_thread(pipeline.analyze, raw_text)
    except deps.RecognitionUnavailableError as exc:
        return _page("识别失败", workflow._redaction_failure_body(exc))

    analysis.setdefault("warnings", [])
    analysis["warnings"] = [*warnings, *analysis.get("warnings", [])]
    return _render_audit_dashboard(
        analysis=analysis,
        original_documents=documents,
        profile=profile,
        llm_mode=llm_mode if config.enable_llm else "off",
        model=config.llm.model if config.enable_llm else model,
        recognition_mode=config.llm.recognition_mode,
    )


async def redact_confirmed_page(request: Request) -> str:
    """增量脱敏：每轮确认后立即替换，再用已脱敏文本做下一轮分析。

    用户勾选的实体本轮生效，未勾选的不会出现在下一轮。
    每轮替换后的文本会传给 LLM 做二次审计，只展示新发现的实体。
    """
    form = await request.form()
    bundle_json = form.get("bundle_json", "")
    analysis_json = form.get("analysis_json", "{}")
    profile = "standard"
    llm_mode = str(form.get("llm_mode", "max-effect"))
    model = str(form.get("model", DEFAULT_MODEL_ID))
    recognition_mode = str(form.get("recognition_mode", "full_document"))
    round_num = int(form.get("round", "0"))
    previous_map_json = form.get("previous_map_json", "{}")
    previous_deselected_json = form.get("previous_deselected_json", "[]")
    action = form.get("action", "continue")

    docs_data = json.loads(bundle_json)
    is_batch = len(docs_data) > 1

    analysis = json.loads(analysis_json)
    analysis["entity_groups"] = [
        group
        for group in analysis.get("entity_groups", [])
        if isinstance(group, dict) and not _entity_group_is_noise(group)
    ]
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
    pipeline = deps.RedactionPipeline(config=PipelineConfig.mapping_only(profile))
    redaction_map = _sanitize_redaction_map(
        RedactionMap.create(mappings=all_mappings, mode=profile)
    )

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
            recognition_stats=_recognition_stats_from_analysis(analysis),
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
            recognition_stats=_recognition_stats_from_analysis(analysis),
            redaction_map=redaction_map,
            review_candidates=[],
            leaks=leaks,
            warnings=[],
        )

    # 对已脱敏文本做新一轮全文分析；失败时停止，不生成新的结果。
    try:
        config, fallback_warnings = status_ops._pipeline_config_for_model_status(
            profile=profile,
            llm_mode=llm_mode,
            model=model,
            recognition_mode=recognition_mode,
        )
        pipeline2 = deps.RedactionPipeline(config=config)
        new_analysis = await asyncio.to_thread(pipeline2.analyze, redacted_text)
    except deps.RecognitionUnavailableError as exc:
        return _page("识别失败", workflow._redaction_failure_body(exc))
    new_analysis.setdefault("warnings", [])
    new_analysis["warnings"] = [*fallback_warnings, *new_analysis.get("warnings", [])]

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
        location
        for location in new_analysis.get("locations", [])
        if location not in all_confirmed and location not in all_deselected_texts
    ]

    new_analysis["entity_groups"] = new_groups
    new_analysis["locations"] = new_locations

    if new_groups or new_locations:
        return _render_audit_dashboard(
            analysis=new_analysis,
            original_documents=[InputDocument(source_file="", text=redacted_text)],
            profile=profile,
            llm_mode=llm_mode if config.enable_llm else "off",
            model=config.llm.model if config.enable_llm else model,
            recognition_mode=config.llm.recognition_mode,
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
            recognition_stats=_recognition_stats_from_analysis(new_analysis),
            redaction_map=redaction_map,
            review_candidates=[],
            leaks=leaks,
            warnings=[],
        )


async def redact_page(
    request: Request,
    text: str = Form(default=""),
    llm_mode: str = Form(default="max-effect"),
    recognition_mode: str = Form(default="full_document"),
    model: str = Form(default=DEFAULT_MODEL_ID),
    # enable_samples kept out of the form: samples never affect runtime redaction.
    base_map_json: str = Form(default=""),
    case_folder: str = Form(default=""),
    discord_thread_url: str = Form(default=""),
    case_root: str = Form(default=""),
    upload_source_dir: str = Form(default=""),
    upload_relative_paths: str = Form(default=""),
    base_map_file: UploadFile | None = File(default=None),
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] = File(default=[]),
    case_folder_files: list[UploadFile] = File(default=[]),
) -> str:
    form_invalid = workflow._reject_forged_workflow_form_data(await request.form())
    if form_invalid is not None:
        return form_invalid

    try:
        documents = await _read_input_documents(text, file, files, case_folder_files)
    except ValueError as exc:
        return _page("上传失败", str(exc))

    base_redaction_map = None
    if base_map_json.strip() or (base_map_file and base_map_file.filename):
        try:
            map_text = await _read_restore_map_text(base_map_json, base_map_file)
            base_redaction_map = redaction_map_from_json(map_text)
        except Exception as exc:
            return _page("已有映射表解析失败", f"解析错误: {exc}")

    try:
        config, fallback_warnings = status_ops._pipeline_config_for_model_status(
            profile="standard",
            llm_mode=llm_mode,
            model=model,
            recognition_mode=recognition_mode,
        )
    except deps.RecognitionUnavailableError as exc:
        return _page("脱敏失败", workflow._redaction_failure_body(exc))
    pipeline = deps.RedactionPipeline(config=config)
    source_files = [item.source_file for item in documents]
    inferred_case_location = _resolve_case_location(upload_source_dir, source_files, upload_relative_paths)
    inferred_source_dir = str(inferred_case_location.get("matched_dir") or "")
    manual_case_root = "" if _is_default_case_root_value(case_root) else case_root.strip()
    effective_case_folder = case_folder.strip() or str(inferred_case_location.get("case_folder") or "")
    effective_case_root = manual_case_root or str(inferred_case_location.get("case_root") or "") or case_root.strip()
    effective_discord_thread_url = discord_thread_url.strip() or str(inferred_case_location.get("discord_thread_url") or "")
    try:
        if len(documents) > 1:
            result = await asyncio.to_thread(
                pipeline.redact_many,
                [(item.source_file, item.text) for item in documents],
                base_redaction_map=base_redaction_map,
            )
        else:
            result = await asyncio.to_thread(
                pipeline.redact,
                documents[0].text,
                source_file=documents[0].source_file,
                base_redaction_map=base_redaction_map,
            )
    except Exception as exc:
        return _page("脱敏失败", workflow._redaction_failure_body(exc))
    result = replace(result, redaction_map=_sanitize_redaction_map(result.redaction_map))
    try:
        if len(documents) > 1:
            augmented_documents = [
                _render_output_document(source, document, result.redaction_map, pipeline)
                for source, document in zip(documents, result.documents)
            ]
            result = replace(
                result,
                documents=augmented_documents,
                warnings=[*result.warnings, *_excel_warnings(documents)],
            )
        else:
            warnings = [*fallback_warnings, *result.warnings, *_excel_warnings(documents)]
    except ExcelFormulaLeakError as exc:
        locations = "".join(f"<li>{html.escape(location)}</li>" for location in exc.locations)
        return _page("Excel 源格式输出失败", f"<p>公式包含待替换内容，已阻止导出。</p><ul>{locations}</ul>")
    except ValueError as exc:
        return _page("Excel 源格式输出失败", html.escape(str(exc)))
    warnings = [*fallback_warnings, *result.warnings] if len(documents) > 1 else warnings
    if len(documents) > 1:
        try:
            workflow._persist_optional_case_redaction(
                effective_case_root,
                effective_case_folder,
                effective_discord_thread_url,
                result.documents,
                result.redaction_map,
                source_dir=inferred_source_dir,
            )
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
            recognition_stats=result.recognition_stats,
            source_documents=documents,
        )
    try:
        redacted_doc = _render_output_document(
            documents[0],
            RedactedDocument(
                source_file=documents[0].source_file,
                original_text=result.original_text,
                redacted_text=result.redacted_text,
                leaks=result.leaks,
            ),
            result.redaction_map,
            pipeline,
        )
    except ExcelFormulaLeakError as exc:
        locations = "".join(f"<li>{html.escape(location)}</li>" for location in exc.locations)
        return _page("Excel 源格式输出失败", f"<p>公式包含待替换内容，已阻止导出。</p><ul>{locations}</ul>")
    except ValueError as exc:
        return _page("Excel 源格式输出失败", html.escape(str(exc)))
    try:
        workflow._persist_optional_case_redaction(
            effective_case_root,
            effective_case_folder,
            effective_discord_thread_url,
            [redacted_doc],
            result.redaction_map,
            source_dir=inferred_source_dir,
        )
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
        document=redacted_doc,
        source_document=documents[0],
        case_root=effective_case_root,
        case_folder=effective_case_folder,
        source_dir=inferred_source_dir,
        recognition_stats=result.recognition_stats,
    )


async def apply_map_page(
    original_text: str = Form(...),
    map_json: str = Form(...),
    original_bundle_json: str = Form(default=""),
) -> str:
    try:
        redaction_map = _sanitize_redaction_map(redaction_map_from_json(map_json))
    except Exception as exc:
        return _page("映射表解析失败", f"错误详情: {exc}")
    pipeline = deps.RedactionPipeline(config=PipelineConfig.mapping_only())
    if original_bundle_json.strip():
        try:
            documents = _documents_from_bundle_json(original_bundle_json)
            redacted_documents = _apply_map_to_documents(pipeline, documents, redaction_map)
            augmented = [_render_output_document(source, document, redaction_map, pipeline) for source, document in zip(documents, redacted_documents)]
        except ExcelFormulaLeakError as exc:
            locations = "".join(f"<li>{html.escape(location)}</li>" for location in exc.locations)
            return _page("Excel 源格式输出失败", f"<p>公式包含待替换内容，已阻止导出。</p><ul>{locations}</ul>")
        except ValueError as exc:
            return _page("Excel 源文件状态无效，请重新上传", html.escape(str(exc)))
        leaks = [lk for document in augmented for lk in document.leaks]
        return _render_batch_redaction_result("应用映射表结果", augmented, redaction_map, [], leaks, ["已重新应用您上传/修改后的映射表。"], source_documents=documents)
    redacted_text = pipeline.apply_redaction_map(original_text, redaction_map)
    leaks = pipeline.scan_high_risk_leaks(redacted_text)
    return _render_redaction_result("应用映射表结果", original_text, redacted_text, redaction_map, [], leaks, ["已重新应用您上传/修改后的映射表。"])


async def apply_edited_map_page(request: Request) -> str:
    form = await request.form()
    form_invalid = workflow._reject_forged_workflow_form_data(form)
    if form_invalid is not None:
        return form_invalid

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
    map_reason = form.getlist("map_reason")
    map_restore_by_default = form.getlist("map_restore_by_default")
    map_entity_id = form.getlist("map_entity_id")
    map_do_not_merge = form.getlist("map_do_not_merge")
    map_restore_original = form.getlist("map_restore_original")
    row_delete = form.getlist("row_delete")
    remap_placeholders = str(form.get("remap_placeholders", "")).strip() == "1"

    redaction_map = _sanitize_redaction_map(
        _redaction_map_from_rows(
            version=map_version, created_at=map_created_at, mode=map_mode,
            source_file=map_source_file, map_type=map_type, map_original=map_original,
            map_masked=map_masked, map_role=map_role, map_source=map_source,
            map_confidence=map_confidence, map_reason=map_reason,
            map_restore_by_default=map_restore_by_default,
            map_entity_id=map_entity_id, map_do_not_merge=map_do_not_merge,
            map_restore_original=map_restore_original, row_delete=row_delete,
        )
    )
    warnings = ["已手动调整映射表。"]
    if remap_placeholders:
        redaction_map = replace(
            redaction_map,
            mappings=sort_mapping_entries(_renumber_mapping_placeholders(redaction_map.mappings)),
        )
        warnings.append("已按当前保留的映射重新排列占位符。")
    pipeline = deps.RedactionPipeline(config=PipelineConfig.mapping_only())
    try:
        documents = _documents_from_bundle_json(original_bundle_json)
    except ValueError as exc:
        return _page("Excel 源文件状态无效，请重新上传", html.escape(str(exc)))
    if documents:
        try:
            redacted_documents = _apply_map_to_documents(pipeline, documents, redaction_map)
            augmented = [_render_output_document(source, document, redaction_map, pipeline) for source, document in zip(documents, redacted_documents)]
        except ExcelFormulaLeakError as exc:
            locations = "".join(f"<li>{html.escape(location)}</li>" for location in exc.locations)
            return _page("Excel 源格式输出失败", f"<p>公式包含待替换内容，已阻止导出。</p><ul>{locations}</ul>")
        except ValueError as exc:
            return _page("Excel 源文件状态无效，请重新上传", html.escape(str(exc)))
        leaks = [lk for document in augmented for lk in document.leaks]
        return _render_batch_redaction_result("编辑映射后结果", augmented, redaction_map, [], leaks, warnings, save_dir=save_dir, discord_thread_url=discord_thread_url, case_root=case_root, case_folder=case_folder, source_dir=source_dir, source_documents=documents)
    redacted_text = pipeline.apply_redaction_map(original_text, redaction_map)
    leaks = pipeline.scan_high_risk_leaks(redacted_text)
    return _render_redaction_result("编辑映射后结果", original_text, redacted_text, redaction_map, [], leaks, warnings, save_dir=save_dir, discord_thread_url=discord_thread_url, case_root=case_root, case_folder=case_folder, source_dir=source_dir)

