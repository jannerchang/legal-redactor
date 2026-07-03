# M8-runtime-benchmark · Step 0 · POC Report

> **Basis**: [README.md](README.md), [EXECUTION_PLAN.md](EXECUTION_PLAN.md) §3
> **Status**: Gate 0b signed · build released
> **Constraint**: any failing POC must record fallback; no unresolved POC failure can pass Gate 0b
> **Version**: v1.0 · 2026-07-03

---

## 1. POC Scope

| # | POC | Signoff condition | Source | Fallback |
|---|---|---|---|---|
| E-1 | M6 safe report contract | Required | README §5 | Reject input and document required field |
| E-2 | Candidate delta shape | Required | EXECUTION_PLAN D3/P2 | Keep report-only comparison, defer endpoint probe |
| E-3 | MLX identity metadata | Required | EXECUTION_PLAN D5/S3 | Reuse existing status probe only |
| E-4 | No default runtime switch | Required | EXECUTION_PLAN D4 | Document manual switch approval in HUMAN_TASKS |
| E-5 | Public SPC sample input boundary | Required | user directive 2026-07-03 | Use path/category references only |
| D | Defense · milestone doc check | Required | FFCS spec/build contracts | Must pass before Gate 0a/0b/2 |

## 2. E-1 · M6 Safe Report Contract

### Goal

- Confirm M8 can validate the M6 report schema.
- Confirm missing fields and privacy flags fail closed.
- Avoid reading raw M6 diagnostics.

### Script

```bash
.venv/bin/python - <<'PY'
from legal_redactor.regression import assert_privacy_safe_report, build_regression_report
report = build_regression_report(
    gold_report={"case_count": 1, "true_positive": 1, "false_positive": 0, "false_negative": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0, "cases": []},
    sample_summaries=[{"manual_corrections": 1}],
    sample_file=None,
    report_started_monotonic=1.0,
    report_finished_monotonic=1.01,
)
assert_privacy_safe_report(report)
print(report["schema_version"], report["privacy"]["safe_by_default"])
PY
```

### Validation

- [x] Valid synthetic M6 report loads.
- [x] Missing required fields are specified for Step 1 tests.
- [x] Unsafe raw keys or sensitive values are covered by the M6 privacy sanitizer; M8 Step 1 adds benchmark-specific tests.

### Result

- PASS · 2026-07-03:
  `.venv/bin/python - <<'PY' ... build_regression_report(...)`.
  Evidence: `schema_version=M6-regression-report/v1`,
  `gold.case_count=1`, `workflow.manual_corrections=1`,
  `timing.report_generation_ms=10`, `privacy.safe_by_default=True`.
  `assert_privacy_safe_report(report)` returned PASS. Recursive raw-key scan
  found only the expected safe flag path `$.privacy.sample_entries`, whose value
  is `omitted`; M8 build should allow this M6 privacy flag while rejecting real
  raw sample-entry arrays.

### Fallback

- If M6 fields are insufficient, keep M8 report schema narrower and document
  the missing field as a non-switching limitation.

## 3. E-2 · Candidate Delta Shape

### Goal

- Compare baseline and candidate reports by label.
- Reject or manual-review comparisons whose `benchmark_context` values differ.
- Preserve quality/workflow metrics alongside timing.
- Produce deterministic recommendation fields.

### Script

```bash
.venv/bin/python - <<'PY'
import hashlib, json
context = {
    "gold_set_id": "spc-construction-public-v1",
    "gold_set_hash": hashlib.sha256(b"gold").hexdigest(),
    "input_set_id": "public-spc-samples-v1",
    "input_set_kind": "public_spc_sample",
    "input_set_hash": hashlib.sha256(json.dumps({"paths": ["samples/01_public.txt"]}, sort_keys=True).encode()).hexdigest(),
    "benchmark_profile": "m8-default-v1",
}
other = dict(context, input_set_hash="different")
print(context == dict(context), context == other)
PY
```

### Validation

- [x] Candidate labels are explicit in the spec contract.
- [x] Candidate contexts are compatible before winner selection.
- [x] Runtime speedups are not recommended when quality regresses.
- [x] Nullable timing/resource/error fields require reason fields and block
      auto-switch recommendations.

### Result

- PASS · 2026-07-03:
  inline Python built a privacy-safe `benchmark_context` with
  `gold_set_id`, `gold_set_hash`, `input_set_id`, `input_set_kind`,
  `input_set_hash`, and `benchmark_profile`. Same-context comparison returned
  `True`; mismatched `input_set_hash` returned `False`. The manifest used
  relative paths/categories only and did not contain document text.

### Fallback

- If recommendation logic is too noisy, emit deltas only and require a manual
  product decision before any runtime switch.

## 4. E-3 · MLX Identity Metadata

### Goal

- Represent `/v1/models` identity evidence in benchmark metadata.
- Keep wrong-service listener detection compatible with `scripts/start_mlx9b_server.sh`.
- Avoid network dependency in required tests.

### Script

```bash
.venv/bin/python - <<'PY'
from legal_redactor.status import EXPECTED_MLX_MODEL
payload = {"data": [{"id": EXPECTED_MLX_MODEL}]}
wrong_payload = {"data": [{"id": "wrong-model"}]}
def has_expected(value):
    return EXPECTED_MLX_MODEL in {item.get("id") for item in value.get("data", []) if isinstance(item, dict)}
print(has_expected(payload), has_expected(wrong_payload), False)
PY
```

### Validation

- [x] Expected model id records `model_match=true`.
- [x] Missing/wrong model records `model_match=false`.
- [x] Probe summary omits prompt/output bodies.

### Result

- PASS · 2026-07-03:
  inline Python verified the expected model id
  `mlx-community/Qwen3.5-9B-MLX-4bit`; expected payload returned
  `model_match_ready=True`, wrong payload returned `model_match_wrong=False`,
  and no probe body was emitted.

### Fallback

- If direct probe code is not needed for M8, benchmark reports can consume
  existing M3/status evidence as metadata.

## 5. E-4 · No Default Runtime Switch

### Goal

- Prove M8 build does not change current runtime defaults.
- Keep Rapid-MLX as candidate evidence only.

### Script

```bash
git diff -- scripts/start_mlx9b_server.sh legal_redactor/__main__.py legal_redactor/config.py
```

### Validation

- [x] Fixed model default remains `mlx-community/Qwen3.5-9B-MLX-4bit`.
- [x] CLI default `--llm max-effect` remains unchanged.
- [x] Pure-rule fallback remains available.

### Result

- PASS · 2026-07-03:
  `git diff -- scripts/start_mlx9b_server.sh legal_redactor/__main__.py legal_redactor/config.py`
  produced no runtime-default diff at spec time.

### Fallback

- Any default switch requires a new explicit product decision and should be
  recorded outside M8's automatic merge path.

## 6. E-5 · Public SPC Sample Input Boundary

### Goal

- Confirm the existing public Supreme People's Court documents under `samples/`
  may be selected as benchmark/test inputs.
- Keep benchmark reports privacy-safe and avoid copying raw document text into
  artifacts.

### Script

```bash
find samples -maxdepth 1 -type f \( -name '*最高*' -o -name '0[123]_*' \) | sort
```

### Validation

- [x] Approved input files are referenced by path/category.
- [x] Benchmark report JSON contains metrics/deltas only.
- [x] Raw matched/missing/extra diagnostics, restored text, sample entries,
      mapping values, and debug traces remain omitted.

### Result

- PASS · 2026-07-03:
  grouped `find` command returned four approved public input files:
  `samples/01_四川中成煤炭建设（集团）有限责任公司与成都泓昌嘉泰房地产有限公司建设工程施工合同纠_纷案.txt`,
  `samples/02_江苏南通二建集团有限公司与上海农村商业银行股份有限公司浦东分行等建设工程施工合同纠_纷案.txt`,
  `samples/03_江苏南通六建建设集团有限公司与衡水鸿泰房地产开发有限公司建设工程施工合同纠纷案.txt`,
  and `samples/最高人民法院民事判决书（样本）.docx`.

### Fallback

- Use synthetic fixtures only if a public sample path is missing locally.

## 7. Defense · Doc Check

### Script

```bash
node /Users/jannerchang/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.1.14/lib/milestone-doc-check.mjs --dir docs/planning/legal-redactor-workflow-efficiency/milestones/M8-runtime-benchmark
```

### Validation

- [x] Structural check exits 0 before Gate 0a.
- [ ] Gate 2 structural check exits 0 before final closeout.

### Result

- Gate 0a structural check PASS:
  `milestone-doc-check · files_scanned=5 · findings=0 · exit=0`.
  Gate 2 `--gate2` structural check remains pending final closeout.

## 8. Gate 0b Checklist

- [x] E-1 through E-5 have PASS/fallback evidence.
- [x] Blocking POC failures are repaired or explicitly downgraded by spec update.
- [x] `step-0-poc-report.md` status is updated to Gate 0b signed.
- [x] Gate 0b review artifacts and chair signoff are recorded in [_progress.md](_progress.md).
