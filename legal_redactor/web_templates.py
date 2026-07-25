"""HTML page shell, CSS, and JavaScript for the web UI.

Extracted from web_app.py to separate the rendering template
from HTTP route handlers. All content is auto-escaped via html.escape().
"""

from __future__ import annotations

import html
import json


MAPPING_REVIEW_CATEGORY_LABELS = {
    "low_confidence": "低置信",
    "manual_added": "手工新增",
    "modified": "已修改",
    "delete_candidate": "删除候选",
    "restore_risk": "还原风险",
    "sample_reused": "样本复用",
}

RESTORE_RISK_REASON_LABELS = {
    "delete_candidate": "删除候选会影响后续黑名单和还原复核",
    "empty_mask": "替换为空，无法可靠还原",
    "risky_delete_guard": "短中文人名未写入全局黑名单",
    "lookup_guard": "未进入可复用样本映射",
}


def _page(title: str, body: str) -> str:
    return f"""
    <!doctype html>
    <html lang="zh-CN">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{html.escape(title)}</title>
      <style>
        :root{{color-scheme:light;--bg:#f5f5f7;--surface:rgba(255,255,255,.82);--surface-solid:#fff;--surface-subtle:rgba(0,0,0,.03);--border:rgba(0,0,0,.1);--ink:#1d1d1f;--muted:#86868b;--accent:#0071e3;--accent-hover:#0060c9;--danger:#d70015;--danger-bg:rgba(215,0,21,.08);--success:#248a3d;--warning:#9e6500;--radius:20px;--radius-md:14px;--radius-sm:10px;--shadow:0 18px 50px rgba(0,0,0,.08);--shadow-subtle:0 1px 2px rgba(0,0,0,.05);--focus-ring:0 0 0 4px rgba(0,113,227,.22)}}
        @media(prefers-color-scheme:dark){{:root{{color-scheme:dark;--bg:#000;--surface:rgba(28,28,30,.78);--surface-solid:#1c1c1e;--surface-subtle:rgba(255,255,255,.06);--border:rgba(255,255,255,.15);--ink:#f5f5f7;--muted:#98989d;--accent:#0a84ff;--accent-hover:#3395ff;--danger:#ff453a;--danger-bg:rgba(255,69,58,.14);--success:#30d158;--warning:#ffd60a;--shadow:0 24px 70px rgba(0,0,0,.5);--shadow-subtle:0 1px 2px rgba(0,0,0,.3);--focus-ring:0 0 0 4px rgba(10,132,255,.3)}}}}
        *,*::before,*::after{{box-sizing:border-box}}
        body{{margin:0;min-height:100vh;padding:32px 22px 48px;color:var(--ink);background:var(--bg);font:15px/1.6 -apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}}
        body::before{{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;background:radial-gradient(900px 520px at 12% -8%,rgba(0,113,227,.16),transparent 62%),radial-gradient(760px 520px at 92% 6%,rgba(94,92,230,.12),transparent 58%),radial-gradient(700px 420px at 50% 110%,rgba(48,209,88,.08),transparent 60%)}}
        main{{max-width:1080px;margin:0 auto}}
        h1{{font-size:28px;font-weight:700;letter-spacing:-.03em;margin:0 0 24px}}
        h2{{font-size:17px;font-weight:600;letter-spacing:-.01em;margin:0 0 14px}}
        section,fieldset.case-workflow-fields{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);backdrop-filter:blur(26px) saturate(1.7);-webkit-backdrop-filter:blur(26px) saturate(1.7);padding:24px;margin:0 0 18px}}
        fieldset.case-workflow-fields{{padding:20px 22px;margin-top:18px}}
        fieldset.case-workflow-fields legend{{padding:0 6px;font-size:14px;font-weight:600}}
        label{{display:block;font-size:13px;font-weight:500;color:var(--muted);margin:14px 0 5px}}
        label.inline{{display:inline;font-size:13px;color:var(--ink);margin:0}}
        .checkbox-label{{display:flex;align-items:center;gap:9px;margin:12px 0;color:var(--ink);font-size:14px;cursor:pointer}}
        .checkbox-label input[type=checkbox]{{width:18px;height:18px;margin:0;accent-color:var(--accent)}}
        textarea,input[type=text],input[type=url],select{{border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 12px;background:var(--surface-subtle);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC",sans-serif;transition:border-color .18s,box-shadow .18s}}
        textarea{{width:100%;font:13px/1.65 "SF Mono","Menlo",monospace;resize:vertical}}
        textarea:focus,input[type=text]:focus,input[type=url]:focus,select:focus{{outline:none;border-color:var(--accent);box-shadow:var(--focus-ring)}}
        textarea[readonly]{{background:var(--surface-subtle);cursor:default}}
        select{{appearance:none;-webkit-appearance:none;min-width:min(360px,100%);padding-right:36px;background-image:linear-gradient(45deg,transparent 50%,var(--muted) 50%),linear-gradient(135deg,var(--muted) 50%,transparent 50%);background-position:calc(100% - 18px) calc(50% + 1px),calc(100% - 13px) calc(50% + 1px);background-size:5px 5px,5px 5px;background-repeat:no-repeat}}
        input[type=file]{{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap;border:0}}
        .upload-picker{{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}}
        .file-pill{{display:inline-flex;margin:8px 0}}
        .file-pill span{{display:inline-flex;align-items:center;border:1px solid var(--border);border-radius:999px;padding:7px 14px;background:var(--surface-subtle);color:var(--ink);font-size:13px;cursor:pointer;transition:border-color .18s,background .18s}}
        .file-pill:hover span{{border-color:var(--accent)}}
        .btn,.downloads a,nav a{{display:inline-flex;align-items:center;justify-content:center;gap:6px;border:1px solid transparent;border-radius:999px;padding:9px 20px;font-size:14px;font-weight:600;background:var(--accent);color:#fff;text-decoration:none;cursor:pointer;box-shadow:var(--shadow-subtle);transition:background .18s,transform .18s,box-shadow .18s}}
        .btn:hover,.downloads a:hover,nav a:hover{{background:var(--accent-hover)}}
        .btn:active,.downloads a:active,nav a:active{{transform:scale(.97)}}
        .btn:focus-visible,.downloads a:focus-visible,nav a:focus-visible{{outline:none;box-shadow:var(--focus-ring)}}
        .btn-primary{{box-shadow:0 10px 28px rgba(0,113,227,.24)}}
        .btn-secondary{{background:var(--surface-subtle);border-color:var(--border);color:var(--ink)}}
        .btn-secondary:hover{{background:rgba(0,113,227,.1);border-color:var(--accent);color:var(--accent)}}
        .btn-sm{{padding:6px 14px;font-size:13px}}
        .debug-link{{font-size:13px;color:var(--muted);text-decoration:none;border-radius:8px;padding:7px 4px}}
        .debug-link:hover{{color:var(--accent);text-decoration:underline}}
        details.advanced-options{{margin:16px 0;border:1px solid var(--border);border-radius:var(--radius-md);background:var(--surface-subtle);padding:0}}
        details.advanced-options summary{{cursor:pointer;list-style:none;padding:12px 16px;font-size:14px;font-weight:600}}
        details.advanced-options summary::-webkit-details-marker{{display:none}}
        details.advanced-options summary::after{{content:"⌄";float:right;color:var(--muted);transition:transform .18s}}
        details.advanced-options[open] summary::after{{transform:rotate(180deg)}}
        details.advanced-options summary:focus-visible{{outline:none;box-shadow:var(--focus-ring);border-radius:var(--radius-md)}}
        details.advanced-options>*:not(summary){{margin-left:16px;margin-right:16px}}
        details.advanced-options label:first-of-type{{margin-top:2px}}
        details.advanced-options .file-pill{{margin-bottom:16px}}
        table{{width:100%;border-collapse:collapse;font-size:12px}}
        th{{text-align:left;font-weight:600;color:var(--muted);padding:9px 8px;border-bottom:1px solid var(--border);font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
        td{{padding:9px 8px;border-bottom:1px solid var(--border)}}
        td textarea{{min-width:180px;padding:7px 9px;font-size:12px;resize:vertical}}
        td input[name=map_type]{{width:110px;padding:6px 8px;font-size:12px}}
        .grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
        .row{{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin:10px 0}}
        .row label{{margin:0}}
        .downloads{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 16px}}
        .hint{{color:var(--muted);font-size:12px}}
        .hidden-raw{{display:none}}
        .warning{{border-color:var(--danger)}}
        .notice{{background:var(--danger-bg)}}
        .status-panel{{padding:20px}}
        .status-head{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px}}
        .status-head h2{{margin:0}}
        .status-head a{{font-size:13px;color:var(--accent);text-decoration:none}}
        .status-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}
        .status-item{{display:grid;grid-template-columns:auto 1fr;gap:3px 10px;align-items:center;border:1px solid var(--border);border-radius:var(--radius-md);padding:11px 12px;background:var(--surface-subtle);min-width:0}}
        .status-item strong{{font-size:13px;font-weight:600;min-width:0}}
        .status-item span:not(.status-pill),.status-item small{{grid-column:1 / -1;font-size:12px;color:var(--muted);min-width:0;overflow-wrap:anywhere}}
        .status-pill{{display:inline-flex;align-items:center;justify-content:center;min-width:42px;border-radius:999px;padding:3px 8px;font-size:11px;font-weight:600;background:var(--surface-subtle);color:var(--ink)}}
        .status-ready{{background:rgba(48,209,88,.16);color:var(--success)}}
        .status-degraded,.status-skipped{{background:rgba(255,214,10,.18);color:var(--warning)}}
        .status-missing{{background:var(--surface-subtle);color:var(--muted)}}
        .status-error{{background:var(--danger-bg);color:var(--danger)}}
        .case-workflow-panel{{border-left:4px solid var(--accent);background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);backdrop-filter:blur(26px) saturate(1.7);-webkit-backdrop-filter:blur(26px) saturate(1.7);padding:18px 20px;margin-bottom:18px}}
        .workflow-head{{display:flex;align-items:center;gap:10px;margin-bottom:12px}}
        .workflow-head strong{{font-size:14px}}
        .workflow-pill{{display:inline-flex;align-items:center;justify-content:center;border-radius:999px;padding:3px 10px;font-size:12px;font-weight:700;background:var(--surface-subtle);color:var(--ink);white-space:nowrap}}
        .workflow-not_saved{{background:var(--surface-subtle);color:var(--muted)}}
        .workflow-saved_local,.workflow-bound_thread{{background:rgba(48,209,88,.16);color:var(--success)}}
        .workflow-sent_discord{{background:rgba(0,113,227,.14);color:var(--accent)}}
        .workflow-waiting_hermes{{background:rgba(255,214,10,.18);color:var(--warning)}}
        .workflow-attach_failed{{background:var(--danger-bg);color:var(--danger)}}
        .workflow-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px 16px;font-size:13px}}
        .workflow-grid span{{min-width:0;overflow-wrap:anywhere}}
        .workflow-grid b{{display:block;color:var(--muted);font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;margin-bottom:2px}}
        .workflow-grid a{{color:var(--accent);text-decoration:none}}
        mark{{background:var(--danger-bg);color:var(--danger);padding:1px 3px;border-radius:3px}}
        .highlight-box{{background:var(--surface-subtle);border:1px solid var(--border);border-radius:var(--radius-md);padding:12px 14px;font:13px/1.65 "SF Mono","Menlo",monospace;white-space:pre-wrap;word-wrap:break-word;overflow:auto;max-height:480px;user-select:text}}
        .highlight-box mark{{padding:1px 4px;border-radius:4px;cursor:help;border-bottom:2px solid transparent}}
        .original-highlight mark{{background:rgba(255,214,10,.24);color:var(--warning);border-bottom-color:var(--warning)}}
        .redacted-highlight mark{{background:rgba(48,209,88,.2);color:var(--success);border-bottom-color:var(--success)}}
        nav{{margin-bottom:16px}}
        nav a{{background:var(--surface-subtle);border-color:var(--border);color:var(--ink)}}
        nav a:hover{{background:rgba(0,113,227,.1);color:var(--accent)}}
        .toast{{position:fixed;top:20px;right:20px;z-index:9999;background:rgba(28,28,30,.9);color:#fff;padding:11px 20px;border-radius:999px;border:1px solid rgba(255,255,255,.16);box-shadow:0 12px 36px rgba(0,0,0,.24);backdrop-filter:blur(20px) saturate(1.6);-webkit-backdrop-filter:blur(20px) saturate(1.6);opacity:0;transform:translateY(-8px) scale(.98);transition:opacity .2s,transform .2s;font-size:13px;font-weight:600}}
        .toast.show{{opacity:1;transform:translateY(0) scale(1)}}
        .toast.warn{{background:rgba(215,0,21,.92)}}
        .mapping-toolbar{{border:1px solid var(--border);border-radius:var(--radius-md);background:var(--surface-subtle);padding:12px 14px;margin:12px 0}}
        .mapping-toolbar-head{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px}}
        .mapping-filter-row{{display:flex;gap:6px;flex-wrap:wrap}}
        .mapping-filter{{border:1px solid var(--border);border-radius:999px;background:var(--surface-solid);color:var(--ink);font-size:12px;padding:6px 11px;cursor:pointer;transition:background .18s,border-color .18s}}
        .mapping-filter span{{color:var(--muted);margin-left:3px}}
        .mapping-filter.active{{background:var(--accent);border-color:var(--accent);color:#fff}}
        .mapping-filter.active span{{color:#fff}}
        .row-tags{{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px}}
        .row-badge{{display:inline-flex;border:1px solid var(--border);border-radius:999px;background:var(--surface-subtle);color:var(--ink);font-size:11px;line-height:1;padding:4px 7px;white-space:nowrap}}
        .row-badge-restore_risk,.row-badge-delete_candidate{{border-color:var(--danger);background:var(--danger-bg);color:var(--danger)}}
        .sample-summary-panel{{border:1px solid var(--border);border-left:4px solid var(--accent);border-radius:var(--radius-md);background:var(--surface-solid);padding:12px 14px;margin:12px 0}}
        .sample-summary-panel[hidden]{{display:none}}
        .sample-summary-content{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px;margin-top:8px;font-size:12px}}
        .sample-summary-content span{{display:block;background:var(--surface-subtle);border:1px solid var(--border);border-radius:var(--radius-sm);padding:7px 9px}}
        .selection-menu{{position:absolute;z-index:10000;display:none;align-items:center;gap:4px;background:var(--surface);border:1px solid var(--border);border-radius:999px;box-shadow:var(--shadow);backdrop-filter:blur(26px) saturate(1.7);-webkit-backdrop-filter:blur(26px) saturate(1.7);padding:5px}}
        .selection-menu button{{border:0;border-radius:999px;padding:7px 12px;background:transparent;color:var(--ink);font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap}}
        .selection-menu button:hover{{background:var(--accent);color:#fff}}
        #text-input.dragover{{border-color:var(--accent);border-width:2px;background:rgba(0,113,227,.06)}}
        .redact-submit-row{{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-top:18px}}
        .redact-progress{{display:flex;align-items:center;gap:10px;flex:1;min-width:240px}}
        .redact-progress-track{{flex:1;max-width:220px;height:6px;border-radius:999px;background:var(--surface-subtle);overflow:hidden}}
        .redact-progress-fill{{height:100%;width:38%;border-radius:999px;background:linear-gradient(90deg,var(--accent),#5e5ce6);animation:redact-progress-slide 1.4s ease-in-out infinite}}
        @keyframes redact-progress-slide{{0%{{transform:translateX(-120%)}}100%{{transform:translateX(320%)}}}}
        .redact-progress-text{{font-size:13px;color:var(--ink);white-space:nowrap}}
        .redact-elapsed{{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}}
        .upload-file-list{{margin:12px 0 14px;border:1px solid var(--border);border-radius:var(--radius-md);background:var(--surface-subtle);padding:12px 14px}}
        .upload-file-list[hidden]{{display:none}}
        .upload-file-list-head{{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px;font-size:12px;color:var(--muted)}}
        .upload-file-list-items{{display:flex;flex-direction:column;gap:5px;max-height:180px;overflow:auto}}
        .upload-file-item{{display:flex;align-items:flex-start;gap:8px;margin:0;font-size:12px;color:var(--ink);font-weight:400;cursor:pointer}}
        .upload-file-item input{{width:auto;margin:2px 0 0;flex:0 0 auto;accent-color:var(--accent)}}
        .upload-file-item span{{min-width:0;overflow-wrap:anywhere}}
        .btn:disabled{{opacity:.65;cursor:wait;transform:none}}
        @media(prefers-reduced-motion:reduce){{*,*::before,*::after{{animation-duration:.01ms !important;animation-iteration-count:1 !important;transition-duration:.01ms !important}}}}
        @media(max-width:768px){{body{{padding:20px 14px 36px}}section,fieldset.case-workflow-fields{{padding:18px}}.grid{{grid-template-columns:1fr}}h1{{font-size:24px}}}}
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
      var mappingCategoryLabels={json.dumps(MAPPING_REVIEW_CATEGORY_LABELS, ensure_ascii=False)};
      var mappingCategoryOrder={json.dumps(list(MAPPING_REVIEW_CATEGORY_LABELS), ensure_ascii=False)};
      var restoreRiskReasonLabels={json.dumps(RESTORE_RISK_REASON_LABELS, ensure_ascii=False)};
      function renderSampleSummary(summary){{var panel=document.getElementById('sample-summary-panel');var content=document.getElementById('sample-summary-content');if(!panel||!content||!summary)return;var rows=[
        ['可复用映射',summary.lookup_entries?summary.lookup_entries.length:0],
        ['删除黑名单候选',summary.delete_blacklist_candidates?summary.delete_blacklist_candidates.length:0],
        ['已保护跳过',summary.suppressed_risky_entries?summary.suppressed_risky_entries.length:0],
        ['人工校正总数',summary.manual_corrections||0],
        ['误识别删除',summary.false_positive_deletes||0],
        ['漏识别新增',summary.missing_adds||0]
      ];content.innerHTML=rows.map(function(item){{return '<span><b>'+item[0]+'</b>: '+item[1]+'</span>';}}).join('');panel.hidden=false;}}
      function mappingRowValue(row,name){{var el=row.querySelector('[name="'+name+'"]');if(!el)return '';if(el.type==='checkbox')return el.checked?el.value:'';return el.value||'';}}
      function readCurrentMappingJson(){{var form=document.getElementById('mapping-edit-form');var mapEl=document.getElementById('mapping-json-output');if(!mapEl)return'{{}}';if(!form)return mapEl.value||'{{}}';var base={{}};try{{base=JSON.parse(mapEl.value||'{{}}');}}catch(_err){{base={{}};}}var mappings=[];form.querySelectorAll('tbody tr').forEach(function(row){{var deleted=row.querySelector('input[name="row_delete"]');if(deleted&&deleted.checked)return;var original=mappingRowValue(row,'map_original').trim();var masked=mappingRowValue(row,'map_masked').trim();if(!original||!masked)return;var confidence=parseFloat(mappingRowValue(row,'map_confidence')||'1.0');var doNotMerge=[];try{{doNotMerge=JSON.parse(mappingRowValue(row,'map_do_not_merge')||'[]');}}catch(_err){{doNotMerge=[];}}if(!Array.isArray(doNotMerge))doNotMerge=[];mappings.push({{type:mappingRowValue(row,'map_type').trim()||'manual',original:original,masked:masked,role:mappingRowValue(row,'map_role').trim()||null,source:mappingRowValue(row,'map_source').trim()||'manual',confidence:isNaN(confidence)?1.0:confidence,restore_by_default:mappingRowValue(row,'map_restore_by_default')!=='0',reason:mappingRowValue(row,'map_reason').trim()||null,entity_id:mappingRowValue(row,'map_entity_id').trim()||null,do_not_merge:doNotMerge,restore_original:mappingRowValue(row,'map_restore_original').trim()||null}});}});base.mappings=mappings;return JSON.stringify(base);}}
      function replacementSignatureFromMapJson(mapJson){{var parsed={{}};try{{parsed=JSON.parse(mapJson||'{{}}');}}catch(_err){{parsed={{}};}}return JSON.stringify((parsed.mappings||[]).map(function(item){{return [String((item&&item.original)||'').trim(),String((item&&item.masked)||'').trim()];}}).filter(function(pair){{return pair[0]&&pair[1];}}));}}
      function hasUnappliedMappingReplacementEdits(){{var mapEl=document.getElementById('mapping-json-output');if(!mapEl)return false;return replacementSignatureFromMapJson(mapEl.value||'{{}}')!==replacementSignatureFromMapJson(readCurrentMappingJson());}}
      function ensureAppliedMappingForText(){{if(!hasUnappliedMappingReplacementEdits())return true;toast('映射表替换关系已修改，请先点「应用表格修改」重新生成脱敏文本', 'warn');return false;}}
      function prepareCurrentMapDownload(link){{if(!link)return true;link.href='data:application/json;charset=utf-8,'+encodeURIComponent(readCurrentMappingJson());return true;}}
      function restoreRiskReasonsForRow(row){{var reasons=[];var deleted=!!row.querySelector('input[name="row_delete"]:checked');var masked=mappingRowValue(row,'map_masked').trim();if(deleted)reasons.push({{reason_code:'delete_candidate',message:restoreRiskReasonLabels.delete_candidate}});if(!masked)reasons.push({{reason_code:'empty_mask',message:restoreRiskReasonLabels.empty_mask}});return reasons;}}
      function mappingOriginalIndex(){{var mapEl=document.getElementById('mapping-json-output');var parsed={{}};try{{parsed=JSON.parse(mapEl?mapEl.value||'{{}}':'{{}}');}}catch(_err){{parsed={{}};}}var index={{}};(parsed.mappings||[]).forEach(function(item){{if(item&&item.original)index[item.original]=item;}});return index;}}
      function mappingReviewCandidateIndex(){{var el=document.getElementById('mapping-review-candidates');var values=[];try{{values=JSON.parse(el?el.value||'[]':'[]');}}catch(_err){{values=[];}}var index={{}};(Array.isArray(values)?values:[]).forEach(function(text){{if(text)index[String(text)]=true;}});return index;}}
      function classifyMappingRow(row,originalIndex,reviewCandidateIndex){{var original=mappingRowValue(row,'map_original').trim();var masked=mappingRowValue(row,'map_masked').trim();if(!original&&!masked)return [];var source=mappingRowValue(row,'map_source').trim().toLowerCase();var confidence=parseFloat(mappingRowValue(row,'map_confidence')||'1');var deleted=!!row.querySelector('input[name="row_delete"]:checked');var baseline=originalIndex[original];var cats=[];if((!isNaN(confidence)&&confidence<0.85)||reviewCandidateIndex[original])cats.push('low_confidence');if(source.indexOf('manual')===0||source.indexOf('user')===0||source.indexOf('selection')===0||(!baseline&&['rule','regex','llm'].indexOf(source)<0))cats.push('manual_added');if(baseline&&baseline.masked&&baseline.masked!==masked)cats.push('modified');if(deleted)cats.push('delete_candidate');if(restoreRiskReasonsForRow(row).length)cats.push('restore_risk');if(source.indexOf('sample')>=0)cats.push('sample_reused');return mappingCategoryOrder.filter(function(name){{return cats.indexOf(name)>=0;}});}}
      function renderMappingRowBadges(row,cats){{var cell=row.querySelector('td:last-child');if(!cell)return;var tags=cell.querySelector('.row-tags');if(!cats.length){{if(tags)tags.remove();return;}}if(!tags){{tags=document.createElement('div');tags.className='row-tags';cell.insertBefore(tags,cell.querySelector('input[type="hidden"]')||null);}}tags.innerHTML='';var restoreReasons=restoreRiskReasonsForRow(row);cats.forEach(function(category){{var badge=document.createElement('span');badge.className='row-badge row-badge-'+category;badge.textContent=mappingCategoryLabels[category]||category;if(category==='restore_risk'&&restoreReasons.length){{badge.dataset.restoreRiskCodes=restoreReasons.map(function(item){{return item.reason_code;}}).join(',');badge.title=restoreReasons.map(function(item){{return item.message;}}).join('；');}}tags.appendChild(badge);}});}}
      function updateMappingReviewState(form){{form=form||document.getElementById('mapping-edit-form');if(!form)return;var originalIndex=mappingOriginalIndex();var reviewCandidateIndex=mappingReviewCandidateIndex();var counts={{}};mappingCategoryOrder.forEach(function(name){{counts[name]=0;}});var total=0;form.querySelectorAll('[data-map-row]').forEach(function(row){{var cats=classifyMappingRow(row,originalIndex,reviewCandidateIndex);row.dataset.categories=cats.join(' ');renderMappingRowBadges(row,cats);if(mappingRowValue(row,'map_original').trim()&&mappingRowValue(row,'map_masked').trim())total+=1;cats.forEach(function(name){{counts[name]=(counts[name]||0)+1;}});}});document.querySelectorAll('[data-map-filter]').forEach(function(btn){{var category=btn.dataset.mapFilter||'all';var span=btn.querySelector('span');if(span)span.textContent=category==='all'?String(total):String(counts[category]||0);}});}}
      function activeMappingFilter(){{var active=document.querySelector('[data-map-filter].active');return active?active.dataset.mapFilter||'all':'all';}}
      function filterMappingRows(category){{updateMappingReviewState();document.querySelectorAll('[data-map-row]').forEach(function(row){{var cats=(row.getAttribute('data-categories')||'').split(/\\s+/).filter(Boolean);row.style.display=(!category||category==='all'||cats.length===0||cats.indexOf(category)>=0)?'':'none';}});document.querySelectorAll('[data-map-filter]').forEach(function(btn){{btn.classList.toggle('active',(btn.dataset.mapFilter||'all')===(category||'all'));}});}}
      document.addEventListener('DOMContentLoaded',function(){{if(document.getElementById('mapping-edit-form'))filterMappingRows('all');}});
      function shouldApplyAutoPrefill(currentValue,lastAutoValue){{var current=(currentValue||'').trim();return !current||current===(lastAutoValue||'');}}
      window.addEventListener('message',function(e){{if(!e.data)return;if(e.data.type==='toast')toast(e.data.msg,e.data.cls==='warn'?'warn':'');if(e.data.type==='sample_summary'){{renderSampleSummary(e.data.summary);toast(e.data.msg,e.data.cls==='warn'?'warn':'');}}}});
      document.addEventListener('click',function(e){{var btn=e.target&&e.target.closest?e.target.closest('[data-map-filter]'):null;if(!btn)return;filterMappingRows(btn.dataset.mapFilter||'all');}});
      document.addEventListener('input',function(e){{var form=e.target&&e.target.closest?e.target.closest('#mapping-edit-form'):null;if(!form)return;filterMappingRows(activeMappingFilter());}});
      document.addEventListener('change',function(e){{var form=e.target&&e.target.closest?e.target.closest('#mapping-edit-form'):null;if(!form)return;filterMappingRows(activeMappingFilter());}});
      (function(){{var ta=document.getElementById('text-input');if(!ta)return;ta.addEventListener('dragover',function(e){{e.preventDefault();ta.classList.add('dragover');}});ta.addEventListener('dragleave',function(){{ta.classList.remove('dragover');}});ta.addEventListener('drop',function(e){{e.preventDefault();ta.classList.remove('dragover');var f=e.dataTransfer.files[0];if(!f)return;if(['txt','md'].indexOf(f.name.split('.').pop().toLowerCase())<0){{toast('不支持 .'+f.name.split('.').pop(),'warn');return;}}var r=new FileReader();r.onload=function(){{ta.value=r.result;toast('已加载: '+f.name);}};r.readAsText(f,'UTF-8');}});}})();
      (function(){{
        var form=document.getElementById('redact-form');
        if(!form)return;
        var uploadSelection={{source:null,items:[]}};
        var stages=[
          {{sec:0,msg:'上传并读取文书…'}},
          {{sec:6,msg:'LLM 语义识别中…'}},
          {{sec:40,msg:'生成映射表并脱敏…'}},
          {{sec:120,msg:'长文书仍在处理，请稍候…'}}
        ];
        function formatElapsed(sec){{
          var mm=Math.floor(sec/60);
          var ss=sec%60;
          return mm+':'+(ss<10?'0':'')+ss;
        }}
        function stageMessage(sec){{
          var msg=stages[0].msg;
          for(var i=stages.length-1;i>=0;i--){{if(sec>=stages[i].sec){{msg=stages[i].msg;break;}}}}
          return msg;
        }}
        function uploadSuffix(name){{var i=String(name||'').lastIndexOf('.');return i>=0?String(name).slice(i).toLowerCase():'.txt';}}
        function isSupportedUpload(name){{return ['.txt','.md','.doc','.docx','.pdf','.xlsx','.xlsm'].indexOf(uploadSuffix(name))>=0&&String(name||'').split('/').pop().indexOf('._')!==0;}}
        function fileList(input){{return Array.prototype.slice.call((input&&input.files)||[]);}}
        function selectedUploadItems(){{return uploadSelection.items.filter(function(item){{return item&&item.checked&&item.file;}});}}
        function syncRelativePaths(){{
          var relativeInput=document.getElementById('upload-relative-paths-input');
          if(!relativeInput)return;
          if(uploadSelection.source!=='directory'){{
            relativeInput.value='';
            return;
          }}
          var paths=selectedUploadItems().map(function(item){{return item.path||item.name||'';}}).filter(Boolean);
          relativeInput.value=JSON.stringify(paths);
        }}
        function updateUploadSummary(){{
          var summary=document.getElementById('upload-file-list-summary');
          if(!summary)return;
          var total=uploadSelection.items.length;
          var checked=selectedUploadItems().length;
          summary.textContent=total?'已选 '+checked+' / '+total+' 个支持文件':'已选 0 个支持文件';
        }}
        function renderUploadFileList(){{
          var list=document.getElementById('upload-file-list');
          var itemsEl=document.getElementById('upload-file-list-items');
          if(!list||!itemsEl)return;
          itemsEl.innerHTML='';
          if(!uploadSelection.items.length){{
            list.hidden=true;
            updateUploadSummary();
            syncRelativePaths();
            return;
          }}
          list.hidden=false;
          uploadSelection.items.forEach(function(item,idx){{
            var row=document.createElement('label');
            row.className='upload-file-item';
            var cb=document.createElement('input');
            cb.type='checkbox';
            cb.className='upload-file-check';
            cb.dataset.index=String(idx);
            cb.checked=!!item.checked;
            cb.addEventListener('change',function(){{
              uploadSelection.items[idx].checked=!!cb.checked;
              updateUploadSummary();
              syncRelativePaths();
            }});
            var span=document.createElement('span');
            span.textContent=item.path||item.name||('文件 '+(idx+1));
            row.appendChild(cb);
            row.appendChild(span);
            itemsEl.appendChild(row);
          }});
          updateUploadSummary();
          syncRelativePaths();
        }}
        function clearOtherUploadSource(isDirectory){{
          if(isDirectory){{
            var plainInput=document.getElementById('source-files');
            if(plainInput)plainInput.value='';
          }}else{{
            var dirInput=document.getElementById('source-directory-files');
            if(dirInput)dirInput.value='';
          }}
        }}
        function buildRedactFormData(formEl){{
          syncRelativePaths();
          var fd=new FormData();
          Array.prototype.forEach.call(formEl.elements,function(el){{
            if(!el||!el.name||el.disabled)return;
            if(el.classList&&el.classList.contains('upload-file-check'))return;
            if(el.type==='file'){{
              if(el.id==='source-files'||el.id==='source-directory-files')return;
              Array.prototype.forEach.call(el.files||[],function(file){{fd.append(el.name,file,file.name);}});
              return;
            }}
            if((el.type==='checkbox'||el.type==='radio')&&!el.checked)return;
            if(el.tagName==='SELECT'&&el.multiple){{
              Array.prototype.forEach.call(el.selectedOptions||[],function(opt){{fd.append(el.name,opt.value);}});
              return;
            }}
            fd.append(el.name,el.value);
          }});
          var fieldName=uploadSelection.source==='directory'?'case_folder_files':'files';
          selectedUploadItems().forEach(function(item){{
            fd.append(fieldName,item.file,item.file.name||item.name||'document.txt');
          }});
          return fd;
        }}
        async function suggestCaseFromSelection(isDirectory){{
          var selected=selectedUploadItems();
          var paths=selected.map(function(item){{return item.path||item.name||'';}}).filter(Boolean);
          var names=selected.map(function(item){{return item.name||'';}}).filter(Boolean);
          if(!names.length)return;
          try{{
            var currentSourceDir=(document.getElementById('upload-source-dir-input')||{{value:''}}).value||'';
            var currentThread=(document.getElementById('discord-thread-url-input')||{{value:''}}).value||'';
            var rootInput=document.getElementById('case-root-input');
            var rootAuto=rootInput?(rootInput.dataset.autoValue||''):'';
            var rootValue=rootInput?(rootInput.value||''):'';
            var currentRoot=shouldApplyAutoPrefill(rootValue,rootAuto)?'':rootValue;
            var resp=await fetch('/api/suggest-case-location',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{filenames:names,relative_paths:isDirectory?paths:[],source_dir:currentSourceDir,discord_thread_url:currentThread,case_root:currentRoot}})}});
            var data=await resp.json();
            if(data.status==='ok'){{
              var root=document.getElementById('case-root-input');
              var folder=document.getElementById('case-folder-input');
              var sourceDir=document.getElementById('upload-source-dir-input');
              var discordUrl=document.getElementById('discord-thread-url-input');
              if(root){{
                if(shouldApplyAutoPrefill(root.value||'',root.dataset.autoValue||'')){{
                  root.value=data.case_root||'';
                  root.dataset.autoValue=data.case_root||'';
                }}
              }}
              if(folder){{
                if(shouldApplyAutoPrefill(folder.value||'',folder.dataset.autoValue||'')){{
                  folder.value=data.case_folder||'';
                  folder.dataset.autoValue=data.case_folder||'';
                }}
              }}
              if(sourceDir&&data.matched_dir)sourceDir.value=data.matched_dir||'';
              if(discordUrl&&!discordUrl.value.trim()&&data.discord_thread_url)discordUrl.value=data.discord_thread_url;
              toast(data.discord_thread_url?'已识别原案件目录和 Discord 链接: '+data.case_folder:'已识别原案件目录: '+data.case_folder);
            }}else if(data.status==='conflict'){{
              toast(data.conflict_message||'案件目录或 Discord 链接存在冲突，请手动确认','warn');
            }}else if(data.status==='ambiguous'){{
              toast('匹配到多个原案件目录，请手动填写原文件所在目录','warn');
            }}else if(data.status==='not_found'){{
              toast('未找到对应的原案件目录，不会自动写入其他案件目录','warn');
            }}
          }}catch(err){{
            console.debug(err);
            toast('案件目录自动识别失败','warn');
          }}
        }}
        function setUploadFromInput(input,isDirectory){{
          var all=fileList(input);
          var supported=all.filter(function(f){{
            var path=f.webkitRelativePath||f.name||'';
            return path&&isSupportedUpload(path);
          }});
          clearOtherUploadSource(isDirectory);
          uploadSelection.source=supported.length?(isDirectory?'directory':'files'):null;
          uploadSelection.items=supported.map(function(f){{
            return {{
              file:f,
              name:f.name||'',
              path:f.webkitRelativePath||f.name||'',
              checked:true
            }};
          }});
          renderUploadFileList();
          if(!supported.length){{
            if(isDirectory&&all.length)toast('案件文件夹中没有可处理的 txt/md/doc/docx/pdf/xlsx/xlsm 文书','warn');
            return;
          }}
          suggestCaseFromSelection(isDirectory);
        }}
        form.addEventListener('submit',function(e){{
          e.preventDefault();
          var btn=document.getElementById('redact-submit-btn');
          var prog=document.getElementById('redact-progress');
          var text=document.getElementById('redact-progress-text');
          var elapsed=document.getElementById('redact-elapsed');
          if(!btn||btn.disabled)return;
          var textArea=document.getElementById('text-input');
          var hasText=!!(textArea&&String(textArea.value||'').trim());
          if(!hasText&&!selectedUploadItems().length){{
            toast('请先粘贴文本或勾选要上传的文件','warn');
            return;
          }}
          btn.disabled=true;
          btn.textContent='脱敏中…';
          if(prog)prog.hidden=false;
          var started=Date.now();
          var tick=setInterval(function(){{
            var sec=Math.floor((Date.now()-started)/1000);
            if(elapsed)elapsed.textContent='已用时 '+formatElapsed(sec);
            if(text)text.textContent=stageMessage(sec);
          }},500);
          function runRedact(){{
            fetch('/redact',{{method:'POST',body:buildRedactFormData(form)}})
            .then(function(resp){{return resp.text().then(function(body){{return {{ok:resp.ok,body:body}};}});}})
            .then(function(res){{
              clearInterval(tick);
              if(!res.ok)throw new Error('服务器返回错误');
              document.open();
              document.write(res.body);
              document.close();
            }})
            .catch(function(err){{
              clearInterval(tick);
              btn.disabled=false;
              btn.textContent='一键脱敏';
              if(prog)prog.hidden=true;
              toast('脱敏失败：'+(err&&err.message?err.message:'网络中断'),'warn');
            }});
          }}
          function checkModelStatus(){{
            return fetch('/api/model-status').then(function(resp){{return resp.json();}}).catch(function(){{return {{state:'missing'}};}});
          }}
          if(text)text.textContent='检查本地模型 API…';
          checkModelStatus().then(function(status){{
            if(status.state!=='ready'&&status.state!=='skipped')toast('本地模型 API 未就绪，将使用纯规则模式','warn');
            if(text)text.textContent='上传并读取文书…';
            runRedact();
          }});
        }});
        document.querySelectorAll('[data-upload-target]').forEach(function(button){{
          button.addEventListener('click',function(){{
            var target=document.getElementById(button.dataset.uploadTarget||'');
            if(target)target.click();
          }});
        }});
        var fileInput=document.getElementById('source-files');
        if(fileInput)fileInput.addEventListener('change',function(){{setUploadFromInput(fileInput,false);}});
        var dirInput=document.getElementById('source-directory-files');
        if(dirInput)dirInput.addEventListener('change',function(){{setUploadFromInput(dirInput,true);}});
      }})();
      function addBlankRow(btn){{var tb=btn.parentElement.querySelector('tbody');if(!tb)return;var rows=tb.querySelectorAll('tr');var last=rows[rows.length-1];var c=last.cloneNode(true);var n=rows.length;c.dataset.mapRow=String(n);c.dataset.categories='';c.querySelectorAll('input,textarea').forEach(function(e){{if(e.name==='row_delete')e.value=n;if(e.name==='map_type')e.value='manual';if(e.name==='map_original'||e.name==='map_original_before'||e.name==='map_masked'||e.name==='map_role'||e.name==='map_reason'||e.name==='map_entity_id'||e.name==='map_restore_original')e.value='';if(e.name==='map_do_not_merge')e.value='[]';if(e.name==='map_source')e.value='manual';if(e.name==='map_confidence')e.value='1.0';if(e.name==='map_restore_by_default')e.value='1';e.checked=false;}});tb.appendChild(c);filterMappingRows(activeMappingFilter());}}
      function saveRow(idx,btn){{var row=btn.closest('tr');var orig=row.querySelector('[name^=orig_]').value;var masked=row.querySelector('[name^=masked_]').value;var reasonEl=row.querySelector('[name^=reason_]');var reason=reasonEl?reasonEl.value:'';fetch('/samples/update/'+idx,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{original:orig,masked:masked,reason:reason}})}}).then(function(r){{return r.json();}}).then(function(d){{toast(d.msg);}});}}
	      function saveNewRow(total,btn){{var act=document.getElementById('new-action').value;var orig=document.getElementById('new-orig').value;var masked=document.getElementById('new-masked').value;var reasonEl=document.getElementById('new-reason');var reason=reasonEl?reasonEl.value:'';if(!orig||(act!=='delete'&&!masked)){{toast(act==='delete'?'请填写原文':'请填写原文和替换为','warn');return;}}fetch('/samples/add',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{action:act,original:orig,masked:masked,reason:reason}})}}).then(function(r){{return r.json();}}).then(function(d){{toast(d.msg);setTimeout(function(){{location.reload();}},1000);}});}}

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
	                  map_json:currentMappingJson(form,mapEl)
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
	              appendMappingRow(form,data.entry);
	              toast('已加入映射表：'+data.entry.original+' → '+data.entry.masked);
	              hideMenu();
	            }}catch(err){{
	              toast('添加映射失败：'+err.message,'warn');
	              hideMenu();
	            }}
	          }});
	        }}
	        function rowValue(row,name){{return mappingRowValue(row,name);}}
	        function currentMappingJson(form,mapEl){{return readCurrentMappingJson();}}
	        function appendHidden(parent,name,value){{
	          var input=document.createElement('input');
	          input.type='hidden';
	          input.name=name;
	          input.value=value==null?'':String(value);
	          parent.appendChild(input);
	        }}
	        function appendTextCell(row,name,value,rows,placeholder){{
	          var cell=document.createElement('td');
	          var input=rows?document.createElement('textarea'):document.createElement('input');
	          input.name=name;
	          if(rows)input.rows=rows;
	          if(placeholder)input.placeholder=placeholder;
	          input.value=value==null?'':String(value);
	          cell.appendChild(input);
	          row.appendChild(cell);
	        }}
		        function renumberMappingRows(tbody){{
		          tbody.querySelectorAll('tr').forEach(function(row,index){{
		            row.dataset.mapRow=String(index);
		            var del=row.querySelector('input[name="row_delete"]');
		            if(del)del.value=String(index);
		          }});
		        }}
	        function appendMappingRow(form,entry){{
		          var tbody=form.querySelector('tbody');
		          if(!tbody)return;
		          var tr=document.createElement('tr');
		          tr.dataset.categories='manual_added';
	          appendTextCell(tr,'map_type',entry.type||'manual',0,'person/org');
	          appendTextCell(tr,'map_original',entry.original||'',2,'新增要替换的原文');
	          appendTextCell(tr,'map_masked',entry.masked||'',2,'替换为');
	          appendTextCell(tr,'map_reason','',2,'为什么新增这条');
	          var sourceCell=document.createElement('td');
	          sourceCell.textContent=entry.source||'manual_selection';
	          tr.appendChild(sourceCell);
	          var confidence=entry.confidence==null?1.0:entry.confidence;
	          var confidenceCell=document.createElement('td');
	          confidenceCell.textContent=Number(confidence).toFixed(2);
	          tr.appendChild(confidenceCell);
	          var actionCell=document.createElement('td');
	          var label=document.createElement('label');
	          label.className='inline';
	          var checkbox=document.createElement('input');
	          checkbox.type='checkbox';
	          checkbox.name='row_delete';
	          label.appendChild(checkbox);
	          label.appendChild(document.createTextNode(' 删除'));
	          actionCell.appendChild(label);
	          appendHidden(actionCell,'map_role',entry.role||'');
	          appendHidden(actionCell,'map_source',entry.source||'manual_selection');
	          appendHidden(actionCell,'map_confidence',confidence);
	          appendHidden(actionCell,'map_restore_by_default',entry.restore_by_default===false?'0':'1');
	          tr.appendChild(actionCell);
	          var rows=tbody.querySelectorAll('tr');
	          var last=rows[rows.length-1];
	          if(last&&!rowValue(last,'map_original').trim()&&!rowValue(last,'map_masked').trim()){{
	            tbody.insertBefore(tr,last);
		          }}else{{
		            tbody.appendChild(tr);
		          }}
		          renumberMappingRows(tbody);
		          filterMappingRows(activeMappingFilter());
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

	      async function attachBoundDiscordThread(buttonEl, payload, statusEl, linkEl) {{
	        var resp = await fetch('/api/discord/attach-bound-thread', {{
	          method: 'POST',
	          headers: {{ 'Content-Type': 'application/json' }},
	          body: JSON.stringify(payload)
	        }});
	        var res = await resp.json();
	        if (res.status === 'pending') {{
	          return {{attached:false, message:res.message || '等待 Hermes 写回 Discord 帖子链接'}};
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
	          buttonEl.dataset.boundThreadUrl = res.thread_url || '';
	          buttonEl.textContent = '再次发送脱敏附件';
	          buttonEl.disabled = false;
	          return {{attached:true, thread_url:res.thread_url}};
	        }}
	        throw new Error(res.message || 'Discord 附件发送失败');
	      }}

	      async function waitForBoundDiscordThread(buttonEl, payload, statusEl, linkEl, origText) {{
	        var maxAttempts = 200;
	        for (var attempt = 1; attempt <= maxAttempts; attempt++) {{
	          var bound = await attachBoundDiscordThread(buttonEl, payload, statusEl, linkEl);
	          if (!bound.attached) {{
	            if (statusEl) statusEl.textContent = bound.message + '（' + attempt + '/' + maxAttempts + '）';
	            await discordWait(3000);
	            continue;
	          }}
	          return;
	        }}
	        if (statusEl) statusEl.textContent = '等待超时：Hermes 尚未写回帖子链接，可稍后再点一次继续绑定';
	        toast('等待 Hermes 写回超时', 'warn');
	        buttonEl.textContent = '继续检查并发送附件';
	        buttonEl.disabled = false;
	      }}

		      async function createDiscordThread(buttonEl) {{
		        var textEl = document.getElementById(buttonEl.dataset.textareaId || 'redacted-output');
		        var messageEl = document.getElementById(buttonEl.dataset.messageId || '');
		        var causeEl = document.getElementById(buttonEl.dataset.caseCauseId || '');
		        var statusEl = document.getElementById(buttonEl.dataset.statusId || '');
	        var linkEl = document.getElementById(buttonEl.dataset.linkId || '');
        if (!textEl || !textEl.value) {{
          toast('没有可发送的脱敏内容', 'warn');
          return;
        }}
        if (!ensureAppliedMappingForText()) return;
        var mapJson = readCurrentMappingJson();
        var parsedMap = {{}};
        try {{parsedMap = JSON.parse(mapJson || '{{}}');}} catch (_err) {{parsedMap = {{}};}}
        if (!parsedMap.mappings || !parsedMap.mappings.length) {{
          toast('缺少映射表，无法绑定案件', 'warn');
          return;
        }}
	        var origText = buttonEl.textContent || buttonEl.innerText;
	        buttonEl.disabled = true;
	        buttonEl.textContent = '正在检查绑定...';
	        if (statusEl) statusEl.textContent = '正在检查是否已绑定 Discord 帖子...';
	        var payload = {{
	          case_root: buttonEl.dataset.caseRoot || '',
	          case_folder: buttonEl.dataset.caseFolder || '',
		          source_dir: buttonEl.dataset.sourceDir || '',
		          case_cause: causeEl ? causeEl.value : '',
		          filename: buttonEl.dataset.filename || 'redacted.txt',
	          content: textEl.value,
	          map_json: mapJson,
	          message: messageEl ? messageEl.value : ''
	        }};
	        try {{
	          var bound = await attachBoundDiscordThread(buttonEl, payload, statusEl, linkEl);
	          if (bound.attached) {{
	            return;
	          }}
	          buttonEl.textContent = '正在请求 Hermes...';
	          var resp = await fetch('/api/discord/create-thread', {{
	            method: 'POST',
	            headers: {{ 'Content-Type': 'application/json' }},
		            body: JSON.stringify({{
		              case_folder: payload.case_folder,
		              case_cause: payload.case_cause,
		              case_root: payload.case_root,
		              source_dir: payload.source_dir
		            }})
	          }});
	          var res = await resp.json();
	          if (resp.ok && res.status === 'bound') {{
	            if (statusEl) statusEl.textContent = res.message || '案件已绑定 Discord 帖子，正在发送附件...';
	            if (linkEl && res.thread_url) {{
	              linkEl.href = res.thread_url;
	              linkEl.style.display = 'inline';
	            }}
	            document.querySelectorAll('input[name=discord_thread_url]').forEach(function(inp) {{
	              inp.value = res.thread_url || '';
	            }});
	            await attachBoundDiscordThread(buttonEl, payload, statusEl, linkEl);
	            return;
	          }}
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
              await writable.write(new Blob([contentText], {{type: cleanMimeType + ';charset=utf-8'}}));
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

# ── Renderers extracted from web_app.py (data prep stays in web_app) ──

def _status_label(state: str) -> str:
    return {
        "ready": "就绪",
        "degraded": "降级",
        "missing": "缺失",
        "error": "错误",
        "skipped": "跳过",
    }.get(state, state)


def render_status_panel(payload: dict) -> str:
    components = payload.get("components", [])
    rows = []
    for item in components:
        state = str(item.get("state", "missing"))
        rows.append(
            '<div class="status-item">'
            f'<span class="status-pill status-{html.escape(state)}">{html.escape(_status_label(state))}</span>'
            f'<strong>{html.escape(str(item.get("label", "")))}</strong>'
            f'<span>{html.escape(str(item.get("message", "")))}</span>'
            f'<small>{html.escape(str(item.get("action", "")))}</small>'
            '</div>'
        )
    return f"""
        <section class="status-panel" aria-label="系统状态">
          <div class="status-head">
            <h2>系统状态</h2>
            <a href="/api/status" data-no-intercept="true">JSON</a>
          </div>
          <div class="status-grid">{''.join(rows)}</div>
        </section>
        """


def render_home_page(
    status_panel,
    sample_info,
    hanlp_attr,
    default_root_str,
    model_options,
    default_model_id,
):
    available_models = [
        item
        for item in model_options
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    model_options_html = "".join(
        f'<option value="{html.escape(str(item["id"]), quote=True)}"'
        f'{" selected" if item["id"] == default_model_id else ""}>'
        f'{html.escape(str(item.get("label") or item["id"]))}</option>'
        for item in available_models
    )
    if not model_options_html:
        model_options_html = '<option value="" selected>暂无可用模型（将使用纯规则）</option>'
    model_hint = (
        f"本地模型 API 当前提供 {len(available_models)} 个模型；每次处理都可重新选择。"
        if available_models
        else "本地模型 API 当前没有可用模型，提交会明确降级为纯规则模式。"
    )
    return _page(
        "本地法律文书脱敏系统",
        status_panel + sample_info + f"""
        <section>
          <h2>脱敏</h2>
          <form id="redact-form" action="/redact" method="post" enctype="multipart/form-data">
            <label>文书内容</label>
              <textarea name="text" id="text-input" rows="12" placeholder="粘贴文书原文，或拖拽 txt/md/doc/docx/pdf/xlsx/xlsm 文件到此处"></textarea>
            <div class="upload-picker">
              <input type="file" id="source-files" name="files" accept=".txt,.md,.doc,.docx,.pdf,.xlsx,.xlsm" multiple>
              <input type="file" id="source-directory-files" name="case_folder_files" accept=".txt,.md,.doc,.docx,.pdf,.xlsx,.xlsm" webkitdirectory directory multiple>
              <button type="button" class="btn btn-secondary btn-sm" data-upload-target="source-files">选择文件</button>
              <button type="button" class="btn btn-secondary btn-sm" data-upload-target="source-directory-files">选择案件文件夹</button>
            </div>
            <input type="hidden" id="upload-relative-paths-input" name="upload_relative_paths" value="">
            <div id="upload-file-list" class="upload-file-list" hidden>
              <div class="upload-file-list-head">
                <span id="upload-file-list-summary">已选 0 个支持文件</span>
              </div>
              <div id="upload-file-list-items" class="upload-file-list-items"></div>
            </div>
            <p class="hint">识别模式默认使用整篇文书双轮补漏；统一标准脱敏：人名、地名、机构名称及敏感编号按同一套规则处理。{html.escape(model_hint)}</p>
            <input type="hidden" name="recognition_mode" value="full_document">
            <input type="hidden" name="llm_mode" value="max-effect">
            <details class="advanced-options">
              <summary>高级选项</summary>
              <label for="model-choice">识别模型</label>
              <select id="model-choice" name="model">
                {model_options_html}
              </select>
              <p class="hint">整篇文书双轮识别是默认路径；单篇最多 120000 字符，超限或首轮失败时自动回退逐句窗口。切换模型会重载本地 MLX worker，仅影响本次文书。</p>
              <label class="checkbox-label">
                <input type="checkbox" name="enable_hanlp" value="1" {hanlp_attr}>
                <span>启用 HanLP 本地候选识别（占用更多内存）</span>
              </label>
              <label>HanLP 模型</label>
              <input type="text" name="hanlp_model" value="MSRA_NER_ELECTRA_SMALL_ZH">
              <label>已有映射表（保持替换一致性）</label>
              <textarea name="base_map_json" rows="3" placeholder="粘贴已有映射表 JSON（可选）"></textarea>
              <label class="file-pill">
                <input type="file" name="base_map_file" accept=".json,.enc">
                <span>选择映射表文件</span>
              </label>
            </details>
            <fieldset class="case-workflow-fields">
              <legend>案件工作流（选填）</legend>
              <label>案件文件夹名</label>
              <input type="text" id="case-folder-input" name="case_folder" placeholder="自动识别；仅在无法识别时填写">
              <label>Discord 帖子链接</label>
              <input type="url" id="discord-thread-url-input" name="discord_thread_url" placeholder="可留空，脱敏完成后可请求 Hermes 新建并回写 Discord 链接">
              <label>案件库根目录</label>
              <input type="text" id="case-root-input" name="case_root" value="{html.escape(default_root_str)}" data-auto-value="{html.escape(default_root_str, quote=True)}">
              <label>原文件所在目录</label>
              <input type="text" id="upload-source-dir-input" name="upload_source_dir" value="" placeholder="目录上传会自动绑定原案件目录；选择文件时可手动填写">
              <p class="hint">选择“案件文件夹”上传时，系统用目录相对路径优先识别已有原案件目录，并把 manifest、脱敏结果、映射表和还原信息写回该原目录；不会另建默认案件目录。识别失败时才需要填写案件文件夹名和原文件所在目录。若未填写 Discord 链接，结果页仍可请求 Hermes 建帖。</p>
            </fieldset>
            <div class="redact-submit-row">
              <button type="submit" class="btn btn-primary" id="redact-submit-btn">一键脱敏</button>
              <div id="redact-progress" class="redact-progress" hidden>
                <div class="redact-progress-track" aria-hidden="true"><div class="redact-progress-fill"></div></div>
                <span id="redact-progress-text" class="redact-progress-text">准备中…</span>
                <span id="redact-elapsed" class="redact-elapsed">已用时 0:00</span>
              </div>
            </div>
          </form>
        </section>
        <section>
          <h2>还原</h2>
          <form action="/restore/preview" method="post" enctype="multipart/form-data">
            <label>粘贴脱敏后的文本</label>
            <textarea name="text" rows="6" placeholder="粘贴脱敏后的文书"></textarea>
            <label>脱敏文本 / Word</label>
            <label class="file-pill">
              <input type="file" name="file" accept=".txt,.md,.docx">
              <span>选择脱敏文本 / Word</span>
            </label>
            <label class="checkbox-label">
              <input type="checkbox" name="restore_docx_format" value="1" checked>
              <span>如果上传的是 Word，输出保留格式的 .docx</span>
            </label>
            <label>映射表（支持加密文件）</label>
            <textarea name="map_json" rows="4" placeholder="粘贴 redaction_map.json"></textarea>
            <label class="file-pill">
              <input type="file" name="map_file" accept=".json,.enc">
              <span>选择映射表文件</span>
            </label>
            <p class="hint">映射表中的全部条目将一次性还原。</p>
            <button type="submit" class="btn btn-secondary">全部还原</button>
          </form>
        </section>


        """,
    )


def render_redaction_result_page(
    title,
    redacted_filename,
    redacted_url,
    map_url,
    debug_url,
    workflow_panel,
    default_dir,
    redacted_filename_json,
    save_dir,
    discord_create_section,
    discord_section,
    leaks_html,
    warnings_html,
    recognition_summary,
    original_highlight,
    redacted_text,
    redacted_highlight,
    mapping_review_toolbar,
    sample_summary_panel,
    original_text,
    map_json,
    review_candidate_texts_json,
    debug_json,
    discord_thread_url,
    case_root,
    case_folder,
    source_dir,
    redaction_map,
    mapping_edit_rows,
    review_html,
    bundle_json="",
):
    return _page(
        title,
        f"""
        <nav><a href="/">返回首页</a></nav>
        <div class="downloads">
          <a download="{html.escape(redacted_filename)}" href="{redacted_url}" class="btn" data-no-intercept="true">{'下载脱敏 Excel' if redacted_filename.lower().endswith('.xlsx') else '下载脱敏文本'}</a>
          <a download="redaction_map.json" href="{map_url}" class="btn btn-secondary" onclick="prepareCurrentMapDownload(this)">下载 redaction_map</a>
          <a href="{debug_url}" download="debug_trace.json" class="debug-link">诊断文件</a>
          <button type="button" class="btn btn-secondary btn-sm" onclick="var t=document.getElementById('redacted-output');if(t)navigator.clipboard.writeText(t.value).then(function(){{toast('已复制')}})">复制脱敏文本</button>
        </div>
        {recognition_summary}

        {workflow_panel}

        {discord_create_section}
        {discord_section}

        {f'<section class="warning"><h2>高危泄漏</h2><ul>{leaks_html}</ul></section>' if leaks_html else ''}
        {f'<section class="notice"><h2>运行提示</h2><ul>{warnings_html}</ul></section>' if warnings_html else ''}
        <section class="grid">
          <div>
            <h2>原文预览 <span class="hint">（高亮部分 = 已替换）</span></h2>
            <div class="highlight-box original-highlight selection-add-source">{original_highlight}</div>
          </div>
          <div>
            <h2>脱敏文</h2>
            <textarea id="redacted-output" class="hidden-raw">{html.escape(redacted_text)}</textarea>
            <div class="highlight-box redacted-highlight">{redacted_highlight}</div>
          </div>
        </section>
        <section>
          <h2>确认将替换的具体文字</h2>
          <p class="hint">修改表格中的原文或替换词后点「应用表格修改」即可重新脱敏。</p>
          {mapping_review_toolbar}
          {sample_summary_panel}
          <form id="mapping-edit-form" action="/redact/apply-edited-map" method="post">
            <textarea name="original_text" class="hidden-raw">{html.escape(original_text)}</textarea>
            <textarea name="original_bundle_json" class="hidden-raw">{html.escape(bundle_json)}</textarea>
            <textarea id="mapping-json-output" name="original_mapping_json" class="hidden-raw">{html.escape(map_json)}</textarea>
            <textarea id="mapping-review-candidates" class="hidden-raw">{html.escape(review_candidate_texts_json)}</textarea>
            <textarea id="debug-trace-output" class="hidden-raw">{html.escape(debug_json)}</textarea>
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
              <thead><tr><th>类型</th><th>原文（精确匹配）</th><th>替换为</th><th>修改理由</th><th>来源</th><th>置信度</th><th>操作</th></tr></thead>
              <tbody>{mapping_edit_rows}</tbody>
            </table>
            <button type="button" class="btn btn-secondary btn-sm" onclick="addBlankRow(this)" style="margin-bottom:12px">＋ 新增一行</button>
            <label style="display:flex; align-items:center; gap:8px; margin:0 0 12px 0; cursor:pointer;">
              <input type="checkbox" name="remap_placeholders" value="1" style="width:auto; margin:0;">
              <span>应用时按当前映射重新排列占位符</span>
            </label>
            <button type="submit" class="btn">应用表格修改/删除</button>
            <button type="submit" formaction="/redact/save-sample" formtarget="save-iframe" class="btn btn-secondary" style="margin-left:8px">保存为样本</button>
          </form>
        </section>
        {'<section><h2>需人工复核</h2><table><thead><tr><th>类型</th><th>文本</th><th>来源</th><th>置信度</th><th>原因</th></tr></thead><tbody>' + review_html + '</tbody></table></section>' if review_html else ''}
        """,
    )


def render_batch_redaction_result_page(
    title,
    combined_filename,
    redacted_url,
    map_url,
    debug_url,
    combined_redacted,
    workflow_panel,
    default_dir,
    combined_filename_json,
    save_dir,
    individual_files_json,
    discord_create_section,
    discord_section,
    leaks_html,
    warnings_html,
    recognition_summary,
    doc_sections,
    mapping_review_toolbar,
    sample_summary_panel,
    bundle_json,
    map_json,
    review_candidate_texts_json,
    debug_json,
    discord_thread_url,
    case_root,
    case_folder,
    source_dir,
    redaction_map,
    mapping_edit_rows,
):
    return _page(
        title,
        f"""
        <nav><a href="/">返回首页</a></nav>
        <div class="downloads">
          <a download="{combined_filename}" href="{redacted_url}" class="btn">下载合并脱敏文本</a>
          <a download="redaction_map.json" href="{map_url}" class="btn btn-secondary" onclick="prepareCurrentMapDownload(this)">下载统一映射表</a>
          <a href="{debug_url}" download="debug_trace.json" class="debug-link">诊断文件</a>
          <button type="button" class="btn btn-secondary btn-sm" onclick="var t=document.getElementById('redacted-output');if(t)navigator.clipboard.writeText(t.value).then(function(){{toast('已复制')}})">复制合并文本</button>
        </div>
        {recognition_summary}

        <textarea id="redacted-output" class="hidden-raw">{html.escape(combined_redacted)}</textarea>

        {workflow_panel}

        {discord_create_section}
        {discord_section}

        {f'<section class="warning"><h2>高危泄漏</h2><ul>{leaks_html}</ul></section>' if leaks_html else ''}
        {f'<section class="notice"><h2>运行提示</h2><ul>{warnings_html}</ul></section>' if warnings_html else ''}
        <section><h2>分文件结果</h2>{doc_sections}</section>
        <section>
          <h2>确认将替换的具体文字</h2>
          {mapping_review_toolbar}
          {sample_summary_panel}
          <form id="mapping-edit-form" action="/redact/apply-edited-map" method="post">
            <textarea name="original_text" class="hidden-raw"></textarea>
            <textarea name="original_bundle_json" class="hidden-raw">{html.escape(bundle_json)}</textarea>
            <textarea id="mapping-json-output" name="original_mapping_json" class="hidden-raw">{html.escape(map_json)}</textarea>
            <textarea id="mapping-review-candidates" class="hidden-raw">{html.escape(review_candidate_texts_json)}</textarea>
            <textarea id="debug-trace-output" class="hidden-raw">{html.escape(debug_json)}</textarea>
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
              <thead><tr><th>类型</th><th>原文</th><th>替换为</th><th>修改理由</th><th>来源</th><th>置信度</th><th>操作</th></tr></thead>
              <tbody>{mapping_edit_rows}</tbody>
            </table>
            <button type="button" class="btn btn-secondary btn-sm" onclick="addBlankRow(this)" style="margin-bottom:12px">＋ 新增一行</button>
            <label style="display:flex; align-items:center; gap:8px; margin:0 0 12px 0; cursor:pointer;">
              <input type="checkbox" name="remap_placeholders" value="1" style="width:auto; margin:0;">
              <span>应用时按当前映射重新排列占位符</span>
            </label>
            <button type="submit" class="btn">应用表格修改/删除到全部文书</button>
            <button type="submit" formaction="/redact/save-sample" formtarget="save-iframe" class="btn btn-secondary" style="margin-left:8px">保存为样本</button>
          </form>
        </section>
        """,
    )
