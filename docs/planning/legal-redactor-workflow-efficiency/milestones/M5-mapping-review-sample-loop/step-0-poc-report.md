# M5-mapping-review-sample-loop · mapping-review-sample-loop · Step 0 · POC Report

> **依据**:[README.md](README.md) + [EXECUTION_PLAN.md](EXECUTION_PLAN.md) §3 Step 0 + [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §6.3
> **状态**:`v1.0 executed · Gate 0b PASS`
> **约束**:任一 POC 失败必走 fallback · 不允许悬空
> **版本**:v1.0 · 2026-06-29

---

## 一、POC 范围(3 项 + 防护栏)

| # | POC | 主审签字条件 | 来源 | fallback 优先级(失败时降级用) |
|---|---|---|---|---|
| E-1 | Current mapping metadata flow | Confirm `map_reason`, confidence, source, restore flag, and delete flag are available in render/apply/save paths. | README D-02/D-03 | Rebuild row metadata extraction near render route; if impossible, add a small server-side form DTO helper |
| E-2 | Sample guard and summary feasibility | Confirm `_samples.py` guards and merge behavior can support summary counts without duplicating heuristics. | README D-04/D-05 | Keep guard helpers in `_samples.py`; if missing, add pure helpers before UI work |
| E-3 | Refreshless save feasibility | Confirm current save-sample response can update the page in place without a full reload or navigation. | README D-06 | Use iframe/postMessage or fetch-driven inline summary; if impossible, preserve state in hidden payload and restore on re-render |
| D | Defense · sensitive sample data boundary | Confirm spec/review material uses synthetic examples only and `samples/` remains ignored. | README D-07 | No fallback; sensitive sample data must not enter docs, artifacts, commits, or PRs |

## 二、POC E-1 · Current mapping metadata flow

### 目标

- Confirm the existing apply-edited-map route accepts row metadata needed for M5.
- Confirm save-sample route already consumes `map_reason` and delete flags.
- Identify the smallest helper boundary for row classification.

### 实测脚本

```bash
nl -ba legal_redactor/web_app.py | sed -n '978,1146p'
nl -ba legal_redactor/web_app.py | sed -n '2907,2993p'
```

### 验证标准

- [x] `map_reason` is read during apply-edited-map.
- [x] `map_reason` is read during save-sample and can become sample `reason`.
- [x] Manual row insertion can carry source/confidence/restore metadata or has a clear fallback.

### 实测结果

- 2026-06-29 · `非阻塞`.
- `apply_edited_map_page` reads `map_reason` at `web_app.py:1003` and passes row metadata into `_redaction_map_from_rows` at `web_app.py:1011`.
- `save_sample_page` reads `map_reason` at `web_app.py:1060` and carries reasons into delete/modify/add sample entries at `web_app.py:1101-1128`.
- `currentMappingJson` includes row `reason` from `map_reason` at `web_app.py:2927`; `appendMappingRow` creates `map_reason` and preserves hidden source/confidence/restore fields at `web_app.py:2963` and `web_app.py:2980-2983`.
- 结论:required metadata is already present in render/apply/save paths; build can add a narrow server-side classifier without a route rewrite.

### Fallback 决议(若失败)

- ① Add a local Web form DTO helper and route tests.
- ② Re-render row metadata from the current mapping JSON on save/apply.
- ③ If both fail, upthrow before build with separate UI route proposal.

## 三、POC E-2 · Sample guard and summary feasibility

### 目标

- Confirm short-person delete and one-character province abbreviation guards are centralized enough to reuse.
- Confirm sample merge/update semantics can avoid duplicate effective entries on repeated saves.
- Confirm synthetic tests can cover all sample summary classes without real sample data.

### 实测脚本

```bash
nl -ba legal_redactor/_samples.py | sed -n '225,389p'
nl -ba tests/test_sample_integration.py | sed -n '78,190p'
nl -ba tests/test_sample_integration.py | sed -n '270,522p'
```

### 验证标准

- [x] `_samples.py` exposes or can host guard helpers for risky deletes and lookup eligibility.
- [x] Existing tests cover short person delete suppression and province abbreviation lookup suppression.
- [x] Repeated save behavior can be verified with synthetic sample entries.

### 实测结果

- 2026-06-29 · `非阻塞`.
- `_samples.py` already centralizes risky delete and lookup guards: `is_global_delete_sample_allowed` at `_samples.py:225-232`; `_sample_lookup_allowed` blocks one-character province abbreviations and case-number-like entries at `_samples.py:382-389`.
- Synthetic regression anchors already exist for short-person delete suppression at `tests/test_sample_integration.py:100-141` and `tests/test_sample_integration.py:470-522`.
- Province-abbreviation/trusted-sample behavior has synthetic tests at `tests/test_sample_integration.py:78-98` and `tests/test_sample_integration.py:161-189`.
- Repeated save and sample reason/diff behavior has synthetic coverage at `tests/test_sample_integration.py:270-332` and `tests/test_sample_integration.py:365-467`.
- Focused verification after Gate 0b review: `.venv/bin/python -m pytest tests/test_sample_integration.py` passed `16` tests in `8.93s`.
- 结论:summary counts can reuse current guard semantics; build should extend these helpers/tests instead of duplicating heuristics in the browser.

### Fallback 决议

- ① Move existing private guard logic behind a narrow public helper.
- ② Add tests before UI changes.
- ③ If guard semantics are ambiguous, upthrow with sample-safety options.

## 四、POC E-3 · Refreshless save feasibility

### 目标

- Confirm current result page can receive save-sample result without full navigation.
- Confirm filter/scroll/context state can be preserved in existing page structure.
- Separate mapping result save behavior from `/samples/edit` admin-page reload behavior.

### 实测脚本

```bash
nl -ba legal_redactor/web_app.py | sed -n '1130,1146p'
nl -ba legal_redactor/web_app.py | sed -n '2770,2774p'
nl -ba legal_redactor/web_app.py | sed -n '2820,2823p'
```

### 验证标准

- [x] Redaction result sample-save response can post an in-page message.
- [x] Existing toast/message path does not require full page replacement.
- [x] Any reload found belongs to sample-library admin edit path, not the mapping review result page, or is explicitly remediated.

### 实测结果

- 2026-06-29 · `非阻塞`.
- Result-page `save_sample_page` already returns a `parent.postMessage(...)` response at `web_app.py:1130-1146`, which can carry an inline structured summary without navigating the main page.
- The result page has a window message listener for save feedback at `web_app.py:2773`.
- A reload exists in `saveNewRow` at `web_app.py:2822`, but that belongs to the `/samples/edit` admin sample-library page, not the redaction result mapping-review sample-save path.
- 结论:refreshless result-page sample save is feasible with the existing iframe/postMessage path; build should keep filter/scroll/context state in the current page.

### Fallback 决议

- ① Keep iframe/postMessage save and add structured summary message.
- ② Switch result-page sample save to `fetch` and inline summary update.
- ③ If full reload is unavoidable, serialize and restore current form/filter state before re-render.

## 九、Defense · sensitive sample data boundary

### 目标

- Keep real `samples/_auto.sample.json` data out of FFCS material and Git.
- Use synthetic names only in tests/docs.

### 实测脚本

```bash
git status --short
git ls-files samples
git check-ignore -v -- tests/test_sample_integration.py || true
nl -ba .gitignore | sed -n '1,30p'
```

### 验证标准

- [ ] `samples/` is ignored.
- [ ] No tracked `samples/_auto.sample.json` exists.
- [ ] `tests/test_sample_integration.py` is unignored; Gate 2 T6 later proves it is tracked with `git ls-files --error-unmatch`.
- [ ] Review material does not include real sample contents.

### 实测结果

- 2026-06-29 · PASS · `非阻塞`.
- `.gitignore` keeps `samples/` ignored at line 9 and generated JSON ignored at line 10.
- `git ls-files samples` produced no tracked sample files.
- `tests/test_sample_integration.py` is no longer ignored after the M5 `.gitignore` exception at line 23; Gate 2 T6 will prove it is tracked with `git ls-files --error-unmatch tests/test_sample_integration.py` after implementation.
- Review/spec material uses code paths and synthetic test anchors only; no real `samples/_auto.sample.json` contents are included.

### Fallback 决议

- No fallback. Sensitive samples must stay local and out of review/delivery material.

## 十、出口 Gate 0b checklist

- [x] E-1 marked `非阻塞 / 阻塞 / 修订`.
- [x] E-2 marked `非阻塞 / 阻塞 / 修订`.
- [x] E-3 marked `非阻塞 / 阻塞 / 修订`.
- [x] Defense boundary marked PASS.
- [x] Blocking items resolved or upthrown.
- [x] Required revisions are reflected in [EXECUTION_PLAN.md](EXECUTION_PLAN.md).
- [x] Gate 0b review passes with `codex,grok` artifacts and chair signoff.

### Gate 0b artifacts

- `.ff-state/reviews/M5-mapping-review-sample-loop-gate0b/artifacts/codex-r0.json` · `status=ok` · `verdict=PASS`
- `.ff-state/reviews/M5-mapping-review-sample-loop-gate0b/artifacts/grok-r0.json` · `status=ok` · `verdict=PASS`
- `.ff-state/reviews/M5-mapping-review-sample-loop-gate0b/chair-signoff.json` · `status=ok` · `verdict=PASS` · `decision=pass_defer`
- Machine proof: `all_pass=true` · `peer_all_pass=true` · `failed=[]`
