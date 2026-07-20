# M3-startup-status-diagnostics · startup-status-diagnostics · Step 0 · POC Report

> **依据**:[README.md](README.md) + [EXECUTION_PLAN.md](EXECUTION_PLAN.md) §3
> **状态**:`v1.0 POC design`
> **约束**:M3 is medium complexity; Gate 0b is not required unless Step 0 discovers a risky design unknown.
> **版本**:v1.0 · 2026-06-27

---

## 一、POC 范围

| # | POC | 主审签字条件 | 来源 | fallback 优先级 |
|---|---|---|---|---|
| 1 | Current Web health surface | Optional live smoke | `web_app.py` | If service is not running, use TestClient/unit test |
| 2 | Current MLX model health contract | Optional live smoke | `scripts/start_mlx9b_server.sh` | If MLX is not running, validate classifier with mocked HTTP |
| 3 | Config diagnostic distinction | Required design check | `local_config.py` | Preserve legacy `{}` behavior and add diagnostic helper |
| D | Defense · milestone doc check | Required before Gate 0a | FFCS spec rule | No fallback; must be zero findings |

## 二、POC 1 · Current Web health surface

### 目标

- Confirm existing lightweight Web liveness stays stable.
- Avoid turning `/health` into a heavy readiness endpoint.

### 实测脚本

```bash
curl -s http://127.0.0.1:7860/health
```

### 验证标准

- [ ] If Web is running, response includes `status`.
- [ ] If Web is not running, build still proceeds with TestClient tests.

### 实测结果

- Status: non-blocking design check, live smoke deferred to build if service is not running.

### Fallback 决议

- Use FastAPI TestClient or direct function tests when the local server is not
  running.

## 三、POC 2 · Current MLX model health contract

### 目标

- Confirm M3 probes follow the same expected model identity as the startup script.
- Preserve wrong-port occupant distinction.

### 实测脚本

```bash
curl -s http://127.0.0.1:18080/v1/models
```

### 验证标准

- [ ] Ready requires `mlx-community/Qwen3.5-9B-MLX-4bit`.
- [ ] Model mismatch or invalid JSON is degraded/error, not ready.
- [ ] Missing `mlx_lm.server` is reported as missing CLI.

### 实测结果

- Status: design check captured in hard gates D3, P2, P3.

### Fallback 决议

- If live MLX is unavailable, implement mocked HTTP/socket tests and record live
  smoke as skipped with reason.

## 四、POC 3 · Config diagnostic distinction

### 目标

- Confirm missing config, invalid JSON, and non-object JSON can be reported to
  the user without breaking existing safe defaults.

### 实测脚本

```bash
.venv/bin/python -m pytest tests/test_status.py
```

### 验证标准

- [ ] Missing config returns diagnostic state `missing`.
- [ ] Invalid JSON returns diagnostic state `invalid_json`.
- [ ] Existing `load_json_config` still returns `{}` for invalid/missing config.

### 实测结果

- Status: to be executed during build after tests are added.

### Fallback 决议

- If broader config refactor proves risky, keep `local_config.py` unchanged and
  put diagnostics in `legal_redactor/status.py` with read-only helper functions.

## 五、Defense · milestone-doc-check

### 目标

- Verify five-file structure before Gate 0a review.

### 实测脚本

```bash
node /Users/example/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.0.111/lib/milestone-doc-check.mjs --dir docs/planning/legal-redactor-workflow-efficiency/milestones/M3-startup-status-diagnostics
```

### 验证标准

- [ ] Exit code 0.
- [ ] `findings=0`.

### 实测结果

- 2026-06-27 · PASS · `files_scanned=5` · `findings=0`.

### Fallback 决议

- No fallback. Fix structure before review.

## 六、出口 Gate 0b checklist

Gate 0b is not planned for M3 at spec time. If build discovers a risky unknown,
return to this file, record a blocking POC, and run Gate 0b before implementation
continues.
