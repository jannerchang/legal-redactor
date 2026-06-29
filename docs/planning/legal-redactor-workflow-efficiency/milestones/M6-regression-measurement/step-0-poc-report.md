# M6-regression-measurement · regression-measurement · Step 0 · POC Report

> **依据**:[README.md](README.md) + [EXECUTION_PLAN.md](EXECUTION_PLAN.md) §3 Step 0 + [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §6.4
> **状态**:`v1.1 completed · Gate 0b pending`
> **约束**:任一 POC 失败必走 fallback · 不允许悬空
> **版本**:v1.0 · 2026-06-29

---

## 一、POC 范围(5 项 + 防护栏)

| # | POC | 主审签字条件 | 来源 | fallback 优先级(失败时降级用) |
|---|---|---|---|---|
| E-1 | Existing gold eval path | Confirm current CLI/evaluator emits precision, recall, F1, TP, FP, FN from synthetic gold input and that M6 can project it without raw diagnostics. | README D-02 | Keep `evaluation.py` as baseline; if CLI wiring blocks, build a wrapper that calls `evaluate_gold_file()` directly and sanitizes the M6 report projection |
| E-2 | M5 summary aggregation | Confirm M5 `sample_summary` keys are stable and can be aggregated from synthetic payloads. | README D-03 | Accept JSON file export of postMessage payloads; if not stable, define a compatibility adapter |
| E-3 | Newest sample provenance privacy | Confirm newest sample freshness can be checked through metadata and Git audit without printing sample bodies. | README D-04/D-05 | Emit only `sample_file`, mtime, counts, and boolean freshness; if metadata missing, report blocked provenance |
| E-4 | Restore placeholder metric feasibility | Confirm unresolved placeholder count can be computed when redacted text and map evidence exist. | README D-06 | Return `null` unless both redacted text and map are supplied; M7 can enrich later |
| E-5 | Saved-case timing feasibility | Confirm document input to saved case timing can use supplied redaction/case timestamps and safely return `null` when evidence is missing. | README D-07 | Use `redaction_map.created_at`/input timestamp plus case manifest `updated_at`; if timestamps are missing, emit `null` with reason |
| D | Defense · sensitive data boundary | Confirm docs/review material uses synthetic examples only and `samples/` remains ignored. | README D-04 | No fallback; sensitive sample data must not enter docs, artifacts, commits, or PRs |

## 二、POC E-1 · Existing gold eval path

### 目标

- Run a tiny synthetic gold-set evaluation.
- Confirm report fields match M6 `gold` requirements.
- Confirm thresholds can fail deterministically.
- Confirm M6 default report projection omits raw `matched`, `missing`, `extra`,
  `original`, and `masked` diagnostics even though the existing eval report
  remains compatible.

### planned script

```bash
tmpdir=$(mktemp -d)
cat > "$tmpdir/gold.json" <<'JSON'
{"cases":[{"name":"synthetic","text":"原告张三与被告星河建设有限公司签订合同。","expected":[{"type":"person","original":"张三"},{"type":"organization","original":"星河建设有限公司"}]}]}
JSON
.venv/bin/python -m legal_redactor --llm off --eval-gold "$tmpdir/gold.json" --eval-report "$tmpdir/report.json"
```

### 验证标准

- [x] Command exits 0 for synthetic input.
- [x] stdout contains `precision`, `recall`, `f1`, `tp`, `fp`, `fn`.
- [x] JSON report contains `case_count`, `precision`, `recall`, `f1`, `true_positive`, `false_positive`, `false_negative`.
- [x] M6 projected `gold` object contains aggregate metrics and per-case counts only.
- [x] M6 projected `gold` object omits raw `matched`, `missing`, `extra`, `original`, and `masked`.

### 实测结果

- **状态**:`修订 · 非阻塞`
- **证据**:
  - `.ff-state/logs/M6-spec-poc-E1-2026-06-29-151808.log`
  - `.ff-state/logs/M6-spec-poc-E1-threshold-2026-06-29-151824.log`
- **关键输出**:
  - Synthetic eval: `cases=1 precision=1.0000 recall=1.0000 f1=1.0000 tp=2 fp=0 fn=0`.
  - Existing eval report includes raw diagnostic arrays `matched/missing/extra`; M6 projection proof returned `m6_projection_contains_raw_diagnostics=false`.
  - Existing CLI does not support `--fail-under-f1`; the compatible threshold path is `--eval-fail-under-recall` / `--eval-fail-under-precision`.
  - `--eval-fail-under-recall 1.01` returned `exit_status=2`, proving deterministic non-zero threshold exit.

### Fallback 决议(若失败)

- ① Call `evaluate_gold_file()` directly from M6 report builder.
- ② Add compatibility tests for `python -m legal_redactor`.
- ③ Keep build D8 aligned to existing precision/recall threshold flags unless M6 explicitly adds an F1 threshold flag with tests.
- ④ If raw diagnostics cannot be separated from the default M6 report, upthrow before build.

## 三、POC E-2 · M5 summary aggregation

### 目标

- Confirm stable M5 summary key names.
- Confirm synthetic payloads are enough for M6 tests.
- Confirm aggregation does not need raw `samples/_auto.sample.json`.

### planned script

```bash
rg -n "manual_corrections|false_positive_deletes|missing_adds|newest_sample_provenance|regression_suggestions|sample_summary" \
  legal_redactor/web_app.py tests/test_sample_integration.py \
  docs/planning/legal-redactor-workflow-efficiency/milestones/M5-mapping-review-sample-loop
```

### 验证标准

- [x] M5 keys are present in code/tests/docs.
- [x] M6 can use synthetic summary JSON for aggregation tests.
- [x] No POC output includes real sample entries.

### 实测结果

- **状态**:`非阻塞`
- **证据**:`.ff-state/logs/M6-spec-poc-E2-2026-06-29-151848.log`
- **关键输出**:
  - `legal_redactor/web_app.py` defines the stable summary key list.
  - `tests/test_sample_integration.py` asserts `sample_summary` payloads and required keys.
  - Synthetic aggregation produced `manual_corrections=3`, `false_positive_deletes=1`, `missing_adds=2`, `restore_unresolved_placeholders=2`.
  - `raw_sample_entries_read=false`.

### Fallback 决议

- ① Add a compatibility adapter that accepts only documented keys.
- ② Treat missing optional fields as zero/null.
- ③ If a required key is missing, return to Gate 0a and update M6 scope.

## 四、POC E-3 · Newest sample provenance privacy

### 目标

- Confirm `samples/` remains ignored and untracked.
- Confirm newest sample metadata can be checked without reading sample contents
  into docs/review.
- Confirm provenance fields are metadata-only.

### planned script

```bash
git ls-files samples
git check-ignore -v samples/_auto.sample.json
python - <<'PY'
from pathlib import Path
p = Path("samples/_auto.sample.json")
print({"exists": p.exists(), "name": p.name, "mtime_present": p.exists()})
PY
```

### 验证标准

- [x] `git ls-files samples` is empty.
- [x] `samples/_auto.sample.json` is ignored.
- [x] Only file name/existence/mtime metadata is printed.

### 实测结果

- **状态**:`非阻塞`
- **证据**:`.ff-state/logs/M6-spec-poc-E3-2026-06-29-151900.log`
- **关键输出**:
  - `tracked_samples_begin/end` was empty.
  - `.gitignore:9:samples/` ignores `samples/_auto.sample.json`.
  - Metadata probe printed `exists=True`, `name='_auto.sample.json'`, `mtime_present=True`, `content_read=False`.

### Fallback 决议

- ① Report provenance as missing/blocked.
- ② Use M5 `sample_summary.newest_sample_provenance` when available.
- ③ Never paste sample bodies into docs or review artifacts.

## 五、POC E-4 · Restore placeholder metric feasibility

### 目标

- Confirm restore preview path exists.
- Confirm unresolved placeholder count can be computed from redacted text plus map evidence.
- Confirm absent evidence returns `null`.

### planned script

```bash
nl -ba legal_redactor/restore.py | sed -n '1,90p'
```

### 验证标准

- [x] `preview_restore()` or a pure helper can inspect redacted text and map entries.
- [x] Absent restore evidence is represented as `null`.
- [x] M7 remote restore timing remains out of M6 scope.

### 实测结果

- **状态**:`修订 · 非阻塞`
- **证据**:
  - `.ff-state/logs/M6-spec-poc-E4-2026-06-29-151915.log`
  - `.ff-state/logs/M6-spec-poc-E4-rerun-2026-06-29-152017.log`
- **关键输出**:
  - First run exposed the real `MappingEntry` constructor requirement; rerun used full dataclass fields and `RedactionMap.create()`.
  - Synthetic restore preview restored 2 mapped placeholders and left `unresolved_placeholder_count=1`.
  - `absent_evidence_result=None`; no sample content was read.

### Fallback 决议

- ① Implement placeholder count as a pure text/map helper, separate from remote restore.
- ② If Word/docx structure prevents reliable counting, keep text metric only and record docx limitation.
- ③ Defer remote restore timing/status to M7.

## 六、POC E-5 · Saved-case timing feasibility

### 目标

- Confirm M6 can compute document input to saved case timing when both input and
  save timestamps are supplied.
- Confirm missing evidence returns `null` with a reason rather than guessing.
- Confirm Discord-thread-to-restored timing remains M7-owned.

### planned script

```bash
nl -ba legal_redactor/cases.py | sed -n '70,230p'
rg -n "created_at|updated_at|map_created_at|persist_case_redaction|save_manifest" legal_redactor/cases.py legal_redactor/web_app.py tests/test_web_app.py
```

### 验证标准

- [x] Case manifest exposes `created_at` / `updated_at` save evidence.
- [x] Redaction/map input timestamp evidence is available from supplied data or returns missing.
- [x] M6 report field `timing.document_input_to_saved_case_ms` is integer-or-null.
- [x] M7-only `timing.discord_thread_to_restored_ms` is `null`/deferred.

### 实测结果

- **状态**:`非阻塞`
- **证据**:`.ff-state/logs/M6-spec-poc-E5-2026-06-29-152042.log`
- **关键输出**:
  - `CaseManifest` exposes `created_at` / `updated_at`; `save_manifest()` updates `updated_at`.
  - Web form carries `map_created_at` from `redaction_map.created_at`.
  - Synthetic timestamp delta returned `document_input_to_saved_case_ms=3000`.
  - Missing timestamp returned `None` plus `missing_timestamp`; Discord-to-restored remains `None` and M7-owned.

### Fallback 决议

- ① Compute saved-case timing only from explicit timestamps supplied to the report builder.
- ② If no input/save timestamp is available, emit `null` plus `missing_timestamp`.
- ③ Do not infer timing from browser labels or Discord/Hermes state.

## 九、Defense · sensitive sample data boundary

### 目标

- Keep real `samples/_auto.sample.json` data out of FFCS material and Git.
- Use synthetic names only in tests/docs.

### planned script

```bash
git ls-files samples
git check-ignore -v samples/_auto.sample.json redaction_map.json
git status --short -- samples '*.sample.json' '*redaction_map*' || true
```

### 验证标准

- [x] `samples/` is ignored.
- [x] No tracked `samples/_auto.sample.json` exists.
- [x] Review material does not include real sample contents.

### 实测结果

- **状态**:`PASS`
- **证据**:`.ff-state/logs/M6-spec-poc-E3-2026-06-29-151900.log`

### Fallback 决议

- No fallback. Sensitive samples must stay local and out of review/delivery material.

## 十、出口 Gate 0b checklist

- [x] E-1 marked `非阻塞 / 阻塞 / 修订`.
- [x] E-2 marked `非阻塞 / 阻塞 / 修订`.
- [x] E-3 marked `非阻塞 / 阻塞 / 修订`.
- [x] E-4 marked `非阻塞 / 阻塞 / 修订`.
- [x] E-5 marked `非阻塞 / 阻塞 / 修订`.
- [x] Defense boundary marked PASS.
- [x] Blocking items resolved or upthrown.
- [x] Required revisions are reflected in [EXECUTION_PLAN.md](EXECUTION_PLAN.md).
- [ ] Gate 0b review passes with `codex,grok` artifacts and chair signoff.
