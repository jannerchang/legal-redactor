# M4-guided-intake-case-binding · guided-intake-case-binding · Step 0 · POC Report

> **依据**:[README.md](README.md) + [EXECUTION_PLAN.md](EXECUTION_PLAN.md) §3
> **状态**:`v1.0 POC design`
> **约束**:M4 is medium complexity; Gate 0b is not required unless Step 0 discovers a risky design unknown.
> **版本**:v1.0 · 2026-06-29

---

## 一、POC 范围

| # | POC | 主审签字条件 | 来源 | fallback 优先级 |
|---|---|---|---|---|
| 1 | Current case suggestion surface | Optional live/file smoke | `web_app.py` | Use temp directories and unit tests |
| 2 | Manifest conflict behavior | Required design check | `cases.py` | Unit tests with temp manifests |
| D | Defense · milestone doc check | Required before Gate 0a | FFCS spec rule | No fallback; must be zero findings |

## 二、POC 1 · Current case suggestion surface

### 目标

- Confirm M4 extends the existing `/api/suggest-case-location` path rather than
  adding a second case-intake endpoint.
- Confirm filenames/source folder can be tested with temp case directories.

### 实测脚本

```bash
.venv/bin/python -m pytest tests/test_web_app.py -k suggest_case_location
```

### 验证标准

- [x] Existing strong filename match returns `status=ok`.
- [x] Existing batch match prefers the directory with more matched filenames.
- [x] Build can add evidence/conflict fields without requiring live browser state.

### 实测结果

- Status: implemented and validated.
- Evidence: `tests/test_web_app.py` includes uploaded filename suggestion,
  batch match preference, suggest API forged-field rejection, evidence shape,
  and conflict warnings; focused/full pytest passed.

### Fallback 决议

- Use temp directory tests when local case folders are absent or sensitive.

## 三、POC 2 · Manifest conflict behavior

### 目标

- Confirm existing manifest code already rejects a different thread id and can
  become the M4 conflict boundary.
- Confirm duplicate thread detection under a root is already covered and can be
  extended for suggestion warnings.

### 实测脚本

```bash
.venv/bin/python -m pytest tests/test_cases.py
```

### 验证标准

- [x] Different thread id for an existing manifest raises an explicit case error.
- [x] Duplicate thread id under the same root raises an explicit duplicate error.
- [x] Build can expose these as safe conflict states without overwriting files.

### 实测结果

- Status: implemented and validated.
- Evidence: `tests/test_cases.py` covers manifest thread mismatch,
  duplicate-thread conflict, safe manifest summary, and suggestion conflict
  responses; `tests/test_web_app.py` covers HTTP forged-field rejection and
  no-silent-overwrite behavior through attach/create paths.

### Fallback 决议

- If current `create_or_update_manifest` behavior is too narrow for UI
  warnings, add a pure preflight helper and keep the existing write path strict.

## 四、Defense · milestone-doc-check

### 目标

- Verify five-file structure before Gate 0a review.

### 实测脚本

```bash
node /Users/example/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.0.111/lib/milestone-doc-check.mjs --dir docs/planning/legal-redactor-workflow-efficiency/milestones/M4-guided-intake-case-binding
```

### 验证标准

- [x] Exit code 0.
- [x] `findings=0`.

### 实测结果

- 2026-06-29 · PASS · `files_scanned=5` · `findings=0`.

### Fallback 决议

- No fallback. Fix structure before review.

## 五、出口 Gate 0b checklist

Gate 0b is not planned for M4 at spec time. If build discovers a risky unknown,
return to this file, record a blocking POC, and run Gate 0b before
implementation continues.
