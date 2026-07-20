# M3-startup-status-diagnostics · startup-status-diagnostics · _progress

> **依据**:[README.md](README.md) + [EXECUTION_PLAN.md](EXECUTION_PLAN.md)
> **格式**:状态速览 + Intent Guard + Gate 节 + 硬门槛证据 + Step 日志 + grep 留痕 + 断路记录 + DoD 闭环 + 决策日志
> **版本**:v1.0 · 2026-06-27

---

## §1 · 状态速览

```text
milestone: M3-startup-status-diagnostics
module: startup-status-diagnostics
当前阶段: ✅ Build 完成
当前 Step: Gate 2 PASS
当前批次: closeout complete
时间盒进度: 100% / 5-7 days
最近 commit SHA: not committed
分支: current working tree
HEAD: not recorded
工作区: .gitignore, README.md, docs/deploy/hermes-office-restore.md, legal_redactor/local_config.py, legal_redactor/status.py, legal_redactor/web_app.py, tests/test_status.py, tests/test_web_app.py, docs/planning/legal-redactor-workflow-efficiency/*
待办: restart existing 7860 Web process before using /api/status on that running instance; next milestone /ffcs:spec M4-guided-intake-case-binding
```

## §2 · Intent Guard

### Q1 · feature 简洁度 / 抽象层数?

**答**:M3 adds a small status schema, read-only probe helpers, one JSON endpoint,
and a compact Web UI status surface. It does not introduce a new service,
launcher, model picker, or cloud dependency.

### Q2 · 当前 spec 目标 scope?

**答**:Scope is readiness/status diagnostics for existing Web, MLX, config, case
root, Office API, MCP, and Discord surfaces. It does not implement M4 case
binding improvements, M5 sample workflow changes, M7 restore behavior changes,
or M8 runtime benchmark changes.

### Q3 · "可选 / 推荐项" 分类?

**答**:UI placement, exact helper function names, and timeout values are reversible
implementation choices for the build agent. Live external smokes are optional
because credentials or running services may be absent; tests and mocked probes
are mandatory.

## §3 · Gate 节

### Gate 0a · 五件套规划评审

- **评审输入**:README + EXECUTION_PLAN + HUMAN_TASKS + step-0-poc-report + _progress + milestone-doc-check output
- **评审池**:`codex,grok`
- **状态**:✅ PASS
- **结果**:`codex-r1` PASS + `grok-r1` PASS + chair signoff PASS; `evaluateGateProof` returned `all_pass=true`
- **validation_profile**:`standard`
- **effective_profile**:`standard`
- **profile_source**:`default`
- **结构机检**:`milestone-doc-check` PASS · `files_scanned=5` · `findings=0`
- **artifacts**:
  - `.ff-state/reviews/M3-startup-status-diagnostics-gate0a/artifacts/codex-r1.json`
  - `.ff-state/reviews/M3-startup-status-diagnostics-gate0a/artifacts/grok-r1.json`
  - `.ff-state/reviews/M3-startup-status-diagnostics-gate0a/chair-signoff.json`

### Gate 0b · POC 放行

- **状态**:不适用 unless Step 0 discovers a risky unknown.
- **理由**:M3 is medium complexity and uses read-only local diagnostics; no high-risk
  POC is required before implementation.

### Checkpoint 1 · Step 1 ~ N-1 自验

- Step 1:✅ PASS · `legal_redactor/status.py` + `legal_redactor/local_config.py`
  diagnostics implemented; `tests/test_status.py` covers schema, config states,
  MLX model identity, timeout/unreachable, cache sidecars, case root, fallback,
  and secret filtering.
- Step 2:✅ PASS · `GET /api/status` and first-screen status panel implemented
  in `legal_redactor/web_app.py`; `/health` unchanged.
- Step 3:✅ PASS · README and `docs/deploy/hermes-office-restore.md` updated;
  focused and full pytest suites passed.

### Gate 2 · DoD 闭环

- **状态**:✅ PASS
- **评审池**:`codex,grok`
- **结果**:`codex-r0` found HIGH malformed MLX status crash risk; repaired with
  port range + `/v1/models` payload-shape validation and regression tests.
  `codex-r1` PASS + `grok-r2` PASS + chair signoff PASS;
  `evaluateGateProof` returned `all_pass=true`.
- **artifacts**:
  - `.ff-state/reviews/M3-startup-status-diagnostics-gate2/artifacts/codex-r0.json`
  - `.ff-state/reviews/M3-startup-status-diagnostics-gate2/artifacts/codex-r1.json`
  - `.ff-state/reviews/M3-startup-status-diagnostics-gate2/artifacts/grok-r2.json`
  - `.ff-state/reviews/M3-startup-status-diagnostics-gate2/chair-signoff.json`

## §4 · 硬门槛证据追踪

| 层 | 条目 | 状态 | 证据 |
|---|---|---|---|
| D | D1 Status schema fixed | ✅ | `legal_redactor/status.py:20-41`; `tests/test_status.py:18-31` |
| D | D2 Secret-safe output | ✅ | `legal_redactor/status.py:372-380`; `tests/test_status.py:151-189`; `tests/test_web_app.py:96-120` |
| D | D3 MLX identity contract | ✅ | `legal_redactor/status.py:116-213`; `tests/test_status.py:59-96`; live `/v1/models` included expected model |
| D | D4 Config diagnostics compatible | ✅ | `legal_redactor/local_config.py:10-60`; `tests/test_status.py:34-56` |
| D | D5 Case root contract | ✅ | `legal_redactor/status.py:95-113`; `tests/test_status.py:124-135` |
| D | D6 Fallback semantics | ✅ | `legal_redactor/status.py:238-248`; `tests/test_status.py:127-133`; Web panel labels degraded/skipped states |
| P | P1 Local config probe | ✅ | `legal_redactor/local_config.py:29-60`; missing/invalid/non-object/ready tests passed |
| P | P2 MLX probe | ✅ | `legal_redactor/status.py:116-213`; timeout/http/invalid JSON/invalid payload/unreachable/model mismatch/out-of-range tests passed |
| P | P3 CLI/cache probe | ✅ | `legal_redactor/status.py:216-235`, `legal_redactor/status.py:337-346`; sidecar test confirms read-only |
| P | P4 Office/MCP probe | ✅ | `legal_redactor/status.py:251-290`; secret-present booleans only |
| P | P5 Discord probe | ✅ | `legal_redactor/status.py:293-311`; no outbound Discord call |
| S | S1 Timeout bounded | ✅ | `legal_redactor/status.py:44-50`, `legal_redactor/status.py:163-169`; timeout test passed |
| S | S2 No startup side effects | ✅ | `rg -n "mkdir|write_text|open\\(|urlopen|POST|delete|unlink" legal_redactor/status.py` reviewed; status probes do not spawn/kill/write/send |
| N | N1 External channels passive | ✅ | `legal_redactor/status.py:251-311`; only env/config presence checks |
| C+A | C1 Status endpoint | ✅ | `legal_redactor/web_app.py:52-54`; temp 7861 `/api/status` returned 200 |
| C+A | C2 First-screen panel | ✅ | `legal_redactor/web_app.py:249`, `legal_redactor/web_app.py:325-360`, `legal_redactor/web_app.py:2544-2556`; temp 7861 index showed panel |
| C+A | C3 Health compatibility | ✅ | `legal_redactor/web_app.py:47-49`; `tests/test_web_app.py:68-69`; `/health` smoke returned stable JSON |
| T | T1 Status unit tests | ✅ | `tests/test_status.py` · 9 tests passed in focused suite |
| T | T2 Web status tests | ✅ | `tests/test_web_app.py:68-138`; endpoint/panel/health tests passed |
| T | T3 Config regression tests | ✅ | `tests/test_status.py:34-56`; `tests/test_llm_config.py` included in focused suite |
| T | T4 Service smoke commands | ✅ | `/health`, `/api/status`, `/v1/models`, and temp 7861 index smoke recorded in §6.5 |
| T | T5 Focused suite | ✅ | `.venv/bin/python -m pytest tests/test_status.py tests/test_web_app.py tests/test_llm_config.py` · 37 passed |
| E | E1 Env inventory | ✅ | `docs/deploy/hermes-office-restore.md:80-94`; README status section |
| E | E2 Cache/runbook note | ✅ | `README.md:103-114`; `docs/deploy/hermes-office-restore.md:82-100` |
| E | E3 Restore docs alignment | ✅ | `docs/deploy/hermes-office-restore.md:66-100`; restore behavior unchanged |
| E | E4 Sensitive-data warning | ✅ | `README.md:111-114`; `docs/deploy/hermes-office-restore.md:140-150`; tests assert no token/text leak |

## §5 · Step 执行日志

| Step | 起 commit | 止 commit | 交付规模 | 关键事件 |
|---|---|---|---|---|
| Spec | not committed | not committed | five spec docs | Created five-file spec set |
| Gate 0a repair | not committed | not committed | docs-only | Applied codex LOW finding: recorded doc-check PASS in step-0-poc-report |
| Gate 0a closeout | not committed | not committed | docs-only | Gate proof `all_pass=true`; next `/ffcs:build M3-startup-status-diagnostics` |
| Step 1 · probes | not committed | not committed | code + tests | Added `status.py` and diagnostic config helper while preserving `load_json_config` safe default |
| Step 2 · Web | not committed | not committed | Web API/UI + tests | Added `/api/status`, compact first-screen status panel, and `/health` regression test |
| Step 3 · docs/tests | not committed | not committed | docs + validation | README/deploy docs updated; focused pytest, full pytest, py_compile, diff-check passed |
| Step 4 · smoke/material | not committed | not committed | read-only smoke | MLX `/v1/models` ready; existing 7860 needs Web restart for new route; temp 7861 verified `/api/status` and panel |
| Gate 2 repair | not committed | not committed | code + tests | Fixed codex HIGH: out-of-range MLX port and malformed `/v1/models` payload now return diagnostic errors instead of crashing |
| Gate 2 closeout | not committed | not committed | review + docs | `codex-r1` PASS, `grok-r2` PASS, chair PASS, `all_pass=true`; full pytest rerun passed |

## §6 · grep 留痕

### 6.1 · Env names and runtime knobs

- **命令**:`rg -n "LEGAL_REDACTOR_(SKIP_MLX|MLX_PORT|MLX_HOST|API_CONFIG|MCP_CONFIG|API_URL|API_TOKEN|DISCORD_BOT_TOKEN|DISCORD_COMMAND_CHANNEL_ID)|HF_HOME|HF_HUB_DISABLE_XET|COPYFILE_DISABLE" start.sh scripts/start_mlx9b_server.sh legal_redactor/*.py`
- **实测时间**:2026-06-27 18:35 CST

| # | 名称 | 文档分类 | 权威分类 | 权威源行号 | 动作 |
|---|---|---|---|---|---|
| 1 | `LEGAL_REDACTOR_SKIP_MLX` | env | MLX startup toggle | `start.sh:34` | 保留 |
| 2 | `LEGAL_REDACTOR_MLX_HOST` | env | MLX host | `scripts/start_mlx9b_server.sh:5` | 保留 |
| 3 | `LEGAL_REDACTOR_MLX_PORT` | env | MLX port | `scripts/start_mlx9b_server.sh:6` | 保留 |
| 4 | `HF_HOME` | env | local model cache root | `scripts/start_mlx9b_server.sh:8` | 保留 |
| 5 | `HF_HUB_DISABLE_XET` | env | Hugging Face transfer behavior | `scripts/start_mlx9b_server.sh:13` | 保留 |
| 6 | `COPYFILE_DISABLE` | env | macOS sidecar mitigation | `scripts/start_mlx9b_server.sh:14` | 保留 |
| 7 | `LEGAL_REDACTOR_API_CONFIG` | env | Office/API/Discord config file | `remote_api.py:44`, `web_app.py:1724` | 保留 |
| 8 | `LEGAL_REDACTOR_MCP_CONFIG` | env | MCP config file | `mcp_adapter.py:44` | 保留 |
| 9 | `LEGAL_REDACTOR_API_URL` | env | MCP Office API URL | `mcp_adapter.py:45` | 保留 |
| 10 | `LEGAL_REDACTOR_API_TOKEN` | env | Office API bearer token | `remote_api.py:51`, `mcp_adapter.py:47` | 保留 but never echo value |
| 11 | `LEGAL_REDACTOR_DISCORD_BOT_TOKEN` | env | Discord token | `web_app.py:1725` | 保留 but never echo value |
| 12 | `LEGAL_REDACTOR_DISCORD_COMMAND_CHANNEL_ID` | env | Discord command channel | `web_app.py:1779` | 保留 |

### 6.2 · Web/API statuses and routes

- **命令**:`rg -n "@app\\.(get|post)\\(\"/(health|api/discord|api/suggest-case-location)|status\\\": \\\"(ok|success|error|pending|not_found|ambiguous|no_filename)\\\"" legal_redactor/web_app.py legal_redactor/remote_api.py`
- **实测时间**:2026-06-27 18:35 CST

| # | 名称 | 文档分类 | 权威分类 | 权威源行号 | 动作 |
|---|---|---|---|---|---|
| 1 | `/health` Web | route | liveness | `web_app.py:46` | 保持稳定 |
| 2 | `/health` Office API | route | liveness | `remote_api.py:58` | 保持稳定 |
| 3 | `/api/suggest-case-location` | route | existing case suggestion API | `web_app.py:92` | 不改语义 |
| 4 | `/api/discord/send-redacted` | route | existing Discord send API | `web_app.py:100` | 不由 status 调用 |
| 5 | `/api/discord/create-thread` | route | existing Discord create request API | `web_app.py:122` | 不由 status 调用 |
| 6 | `/api/discord/attach-bound-thread` | route | existing attach API | `web_app.py:152` | 不由 status 调用 |
| 7 | `ok`, `success`, `error`, `pending`, `not_found`, `ambiguous`, `no_filename` | statuses | existing response statuses | `web_app.py:48-201`, `web_app.py:1878-1900` | Status endpoint should not break existing meanings |

### 6.3 · MCP and Office error/tool names

- **命令**:`rg -n "missing_api_url|missing_api_token|office_api_error|office_unreachable|restore_judgment_from_thread|get_case_status_by_thread|bind_discord_thread_to_case|tools/list|initialize" legal_redactor/mcp_adapter.py legal_redactor/remote_api.py tests/test_mcp_adapter.py tests/test_remote_api.py`
- **实测时间**:2026-06-27 18:35 CST

| # | 名称 | 文档分类 | 权威分类 | 权威源行号 | 动作 |
|---|---|---|---|---|---|
| 1 | `missing_api_url` | error code | MCP config missing URL | `mcp_adapter.py:49` | Reuse in status details |
| 2 | `missing_api_token` | error code | MCP config missing token | `mcp_adapter.py:51` | Reuse in status details |
| 3 | `office_api_error` | error code | Office API HTTP error | `mcp_adapter.py:65` | Reuse if live probe added |
| 4 | `office_unreachable` | error code | Office API network error | `mcp_adapter.py:67` | Reuse if live probe added |
| 5 | `restore_judgment_from_thread` | tool | MCP restore tool | `mcp_adapter.py:92` | Report availability only |
| 6 | `get_case_status_by_thread` | tool | MCP status tool | `mcp_adapter.py:101` | Report availability only |
| 7 | `bind_discord_thread_to_case` | tool | MCP bind tool | `mcp_adapter.py:107` | Report availability only |
| 8 | `initialize`, `tools/list` | JSON-RPC methods | MCP protocol surface | `mcp_adapter.py:130`, `mcp_adapter.py:138` | M7 live smoke; M3 config only |

### 6.4 · MLX model and wrong-port evidence

- **命令**:`rg -n "Qwen3.5-9B-MLX-4bit|/v1/models|端口 .*已被占用|mlx_lm.server|LEGAL_REDACTOR_MLX_PORT|HF_HOME" scripts/start_mlx9b_server.sh README.md tests/test_llm_config.py`
- **实测时间**:2026-06-27 18:35 CST

| # | 名称 | 文档分类 | 权威分类 | 权威源行号 | 动作 |
|---|---|---|---|---|---|
| 1 | `LEGAL_REDACTOR_MLX_PORT` | env | default 18080 | `scripts/start_mlx9b_server.sh:6` | 保留 |
| 2 | `mlx-community/Qwen3.5-9B-MLX-4bit` | model id | fixed expected model | `scripts/start_mlx9b_server.sh:7`, `tests/test_llm_config.py:17` | 保留 |
| 3 | `HF_HOME` | env | local cache root | `scripts/start_mlx9b_server.sh:8` | 保留 |
| 4 | `/v1/models` | route | model identity probe | `scripts/start_mlx9b_server.sh:30` | Reuse |
| 5 | wrong-port occupant message | error text | occupied port not target model | `scripts/start_mlx9b_server.sh:88-89` | Preserve distinction |
| 6 | `mlx_lm.server` | CLI | required local server | `scripts/start_mlx9b_server.sh:93-99` | Probe without spawning |

### 6.5 · Build validation evidence

- **focused pytest**:
  `.venv/bin/python -m pytest tests/test_status.py tests/test_web_app.py tests/test_llm_config.py`
  → `37 passed in 0.25s`
- **full pytest**:
  `.venv/bin/python -m pytest`
  → `140 passed, 5 subtests passed in 69.90s`
- **new-code static check**:
  `.venv/bin/python -m ruff check legal_redactor/status.py legal_redactor/local_config.py tests/test_status.py`
  → `All checks passed!`
- **whole Web ruff note**:
  `.venv/bin/python -m ruff check legal_redactor/status.py legal_redactor/local_config.py legal_redactor/web_app.py tests/test_status.py tests/test_web_app.py`
  → failed on pre-existing `legal_redactor/web_app.py` lint debt outside M3 scope
  (`F401`, `E741`, `F821 RedactionProfile`, `F841`, `E701`, `F541`).
- **syntax/diff hygiene**:
  `.venv/bin/python -m py_compile legal_redactor/local_config.py legal_redactor/status.py legal_redactor/web_app.py`
  → pass; `git diff --check` → pass.
- **Gate 2 doc-check**:
  `node /Users/example/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.0.111/lib/milestone-doc-check.mjs --dir docs/planning/legal-redactor-workflow-efficiency/milestones/M3-startup-status-diagnostics --gate2`
  → `OK · 0 findings`.
- **pre-push checklist dry-run**:
  `node /Users/example/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.0.111/lib/pre-push-checklist.mjs --project-root /Users/example/legal-redactor --dry-run`
  → `severity=pass`; fixture check skipped/pass due `git ls-files ... ENOBUFS`; no GitHub push/PR in this run.
- **read-only smoke**:
  - existing `http://127.0.0.1:7860/health` → `{"status":"ok","bind_host":"127.0.0.1","network":"offline"}`
  - existing `http://127.0.0.1:7860/api/status` → `{"detail":"Not Found"}` because the running 7860 process predates M3 and needs restart
  - `http://127.0.0.1:18080/v1/models` → includes `mlx-community/Qwen3.5-9B-MLX-4bit`
  - temporary `uvicorn legal_redactor.web_app:app --host 127.0.0.1 --port 7861`:
    `/health` 200, `/api/status` 200, `/` contains `系统状态`, `MLX 本地模型`,
    `Office 还原 API`, `Hermes MCP 配置`, `Discord 指令通道`, and `一键脱敏`; temp process stopped.

## §7 · 断路事件记录

| # | 时间戳 | 类型 | 上下文 | 尝试路径 | 诊断入口 |
|---|---|---|---|---|---|
| 1 | 2026-06-27T18:35:00+08:00 | none | Spec drafting | No blocker | Not needed |
| 2 | 2026-06-27T19:05:00+08:00 | non-blocking lint debt | Whole-file ruff on `web_app.py` reports pre-existing errors unrelated to M3 | Scoped new-code ruff + py_compile + pytest used for M3 validation | Future cleanup outside M3 |
| 3 | 2026-06-27T19:15:00+08:00 | review finding | `codex-r0` HIGH found malformed MLX status crash risk | Added port range validation, `/v1/models` payload shape validation, and regression tests | `codex-r1` PASS |
| 4 | 2026-06-27T19:17:00+08:00 | reviewer transport retry | `grok-r0/r1` exhausted max turns and runner classified as auth_fail | Raised local Grok reviewer `--max-turns` from 30 to 100 and retried compact prompt | `grok-r2` PASS |

## §8 · DoD 闭环条目

- [x] All M3 deliverables implemented.
- [x] POC/live smoke results recorded or skipped with reason.
- [x] Hard gate evidence filled for D/P/S/N/C+A/T/E rows.
- [x] `milestone-doc-check.mjs --gate2` passes.
- [x] Focused pytest suite passes.
- [x] Gate 2 review passes with real artifacts.
- [x] Handoff points to the next milestone or follow-up.

## §9 · SessionEnd 快照

No hook snapshot for this spec run.

## §10 · 决策日志

| # | 时间 | 决策 | 触发 | 影响 |
|---|---|---|---|---|
| 1 | 2026-06-27 | Use standard validation profile | `local-config.mjs profile` returned default `standard` | No profile upshift/downshift |
| 2 | 2026-06-27 | Treat M3 as medium complexity | Local status endpoint plus UI plus tests; no high-risk data migration | HUMAN_TASKS included; POST_GA not required |
| 3 | 2026-06-27 | Use `codex + grok` Gate 0a policy | Local FFCS config and previous split proof | Review artifacts required for both reviewers |
| 4 | 2026-06-27 | Gate 0a PASS | `codex-r1`, `grok-r1`, chair signoff, `all_pass=true` | Spec can proceed to build |
| 5 | 2026-06-27 | Keep existing 7860 process untouched during smoke | Running process predates M3 code and returns `/api/status` 404 | Verified new route on temp 7861; user should restart Web to load M3 |
| 6 | 2026-06-27 | Unignore only M3 test files | `.gitignore` ignored all `tests/` files, but M3 requires tracked tests | `.gitignore` now allows `tests/test_status.py` and `tests/test_web_app.py` while keeping other local tests ignored |
| 7 | 2026-06-27 | Accept and repair codex Gate 2 HIGH | `probe_mlx_server` could crash on non-object `/v1/models` JSON or out-of-range port | Added diagnostic error states and tests; no new product decision required |
| 8 | 2026-06-27 | Gate 2 PASS | codex-r1 PASS + grok-r2 PASS + chair signoff PASS + `all_pass=true` | Build can hand off to M4 spec |
