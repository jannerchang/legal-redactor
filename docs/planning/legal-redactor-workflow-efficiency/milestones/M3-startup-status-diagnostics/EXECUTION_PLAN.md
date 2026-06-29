# M3-startup-status-diagnostics · startup-status-diagnostics · 执行计划

> **依据**:[README.md](README.md), [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §6.1
> **格式**:七层硬门槛 + 决策表 + Step 顺序 + 时间盒 + 跨模块签字 + 服务端权威重算 + 文档维护扫
> **schema 引用**:/Users/jannerchang/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.0.111/templates/gate.schema.md
> **更新节奏**:Step 进 / 出时同步本文件 + [_progress.md](_progress.md)
> **版本**:v1.0 · 2026-06-27

---

## §1 · 七层硬门槛

| id | title | description | evidence_required | pass_condition | block_severity | typical_count |
|---|---|---|---|---|---|---:|
| D1 | Status schema fixed | Define a stable status item shape with `id`, `label`, `state`, `message`, `action`, and optional `details`. | code_path_read, unit_test_count | Tests prove every probe emits only allowed states and fields. | BLOCKER | 1 |
| D2 | Secret-safe output | Status output never includes API tokens, Discord bot tokens, redaction maps, originals, samples, or restored full text. | unit_test_count, grep_stdout | Tests inject fake secrets and assert they do not appear in JSON or HTML. | BLOCKER | 1 |
| D3 | MLX identity contract | MLX ready state requires `/v1/models` to include `mlx-community/Qwen3.5-9B-MLX-4bit`. | unit_test_count, code_path_read | Model mismatch and wrong-port occupant produce degraded/error states, not ready. | BLOCKER | 1 |
| D4 | Config diagnostics compatible | Existing `load_json_config` behavior remains safe-default `{}` while a diagnostic API reports missing/invalid/non-object config. | unit_test_count, code_path_read | Existing callers keep passing and new tests distinguish missing vs invalid JSON. | HIGH | 1 |
| D5 | Case root contract | Case root readiness checks existence/writability of the resolved local case root without creating user data during status read. | unit_test_count | Tests cover missing, read-only or unwritable, and ready directories. | HIGH | 1 |
| D6 | Fallback semantics | Pure-rule fallback state is shown when MLX is skipped/unavailable and is not presented as equivalent to LLM-supported recognition. | code_path_read, integration_test_count | UI/JSON distinguishes ready/degraded/skipped and includes user-facing action. | HIGH | 1 |
| P1 | Local config probe | Add a pure helper that resolves config source path and returns missing/invalid/non-object/ready without side effects. | unit_test_count | Helper uses explicit path/env input in tests and does not read unrelated globals. | BLOCKER | 1 |
| P2 | MLX probe | Add a bounded HTTP probe for host/port/model id plus optional socket/wrong-port classification. | unit_test_count | Probe returns ready, unreachable, model_mismatch, invalid_json, http_error, or timeout. | BLOCKER | 1 |
| P3 | CLI/cache probe | Add non-spawning checks for `mlx_lm.server`, `HF_HOME`, expected model cache path, and AppleDouble sidecar warning. | unit_test_count | Probe reports action items without deleting or modifying cache files. | HIGH | 1 |
| P4 | Office/MCP probe | Add pure readiness checks for Office API config and MCP config without requiring live credentials. | unit_test_count | Missing `api_url` or `api_token` is visible as missing config, not exception. | HIGH | 1 |
| P5 | Discord probe | Add readiness checks for Discord bot token and command channel id without sending messages. | unit_test_count | Optional Discord config is missing/degraded until explicitly configured. | MEDIUM | 1 |
| S1 | Timeout bounded | All network probes use short timeouts and status failure cannot block redaction request handling. | unit_test_count | Tests mock timeout and confirm JSON/HTML still returns promptly. | BLOCKER | 1 |
| S2 | No startup side effects | Status read does not start MLX, kill listeners, clean cache, send Discord messages, or write case files. | grep_stdout, unit_test_count | Tests and grep show probes are read-only. | BLOCKER | 1 |
| N1 | External channels passive | Discord and Hermes/MCP status checks are passive readiness reports only. | code_path_read, unit_test_count | No outbound Discord API call or MCP tool call is made from a status read. | HIGH | 1 |
| C1 | Status endpoint | Add a machine-readable Web endpoint such as `GET /api/status`. | integration_test_count | Endpoint returns `status: ok` plus component array and no secret values. | BLOCKER | 1 |
| C2 | First-screen panel | Add a compact Web UI status panel/band with ready/degraded/missing/error labels and next actions. | code_path_read, integration_test_count | Initial page includes component status text without hiding existing intake workflow. | HIGH | 1 |
| C3 | Health compatibility | Keep existing `GET /health` behavior stable for lightweight liveness. | integration_test_count | Existing `/health` tests or smoke still receive current liveness shape. | MEDIUM | 1 |
| T1 | Status unit tests | Add focused tests for probe classifiers and secret redaction. | unit_test_count | `.venv/bin/python -m pytest tests/test_status.py` passes. | BLOCKER | 1 |
| T2 | Web status tests | Extend Web tests for `/api/status` and visible status panel. | integration_test_count | `.venv/bin/python -m pytest tests/test_web_app.py` passes. | BLOCKER | 1 |
| T3 | Config regression tests | Cover missing/invalid/non-object config diagnostics and legacy safe defaults. | unit_test_count | `.venv/bin/python -m pytest tests/test_llm_config.py tests/test_status.py` passes or relevant config tests pass. | HIGH | 1 |
| T4 | Service smoke commands | Record manual smoke commands for Web and MLX health. | doc_anchor | Build closeout lists `GET /health` and `GET /v1/models` evidence or reason skipped. | MEDIUM | 1 |
| T5 | Focused suite | Run the focused M3 suite before Gate 2. | unit_test_count, integration_test_count | Focused suite passes or failures are documented with blocker/fallback. | BLOCKER | 1 |
| E1 | Env inventory | Document env names used by M3: Web, MLX, Office API, MCP, Discord. | doc_anchor, grep_stdout | Docs and progress cite actual code line evidence for env names. | HIGH | 1 |
| E2 | Cache/runbook note | Document local HF cache, expected model id, and wrong-port remediation. | doc_anchor | Operator note explains `HF_HOME`, `/v1/models`, and port occupant distinction. | HIGH | 1 |
| E3 | Restore docs alignment | Update restore/deploy docs only for readiness/status meanings, not restore behavior. | doc_anchor | Docs distinguish M3 readiness from M7 restore workflow work. | MEDIUM | 1 |
| E4 | Sensitive-data warning | Add or preserve warning that status does not expose maps/originals/restored text/tokens. | doc_anchor | Status docs and tests both cover the boundary. | BLOCKER | 1 |

## §2 · 决策表

| # | 决策 | 影响范围 | 来源 | 状态 |
|---|---|---|---|---|
| D-01 | Keep `./start.sh` as manual entrypoint. | Step 2 UI and docs | README D-01 | 锁 |
| D-02 | Keep expected MLX model `mlx-community/Qwen3.5-9B-MLX-4bit`. | Step 1 MLX probe | README D-02 | 锁 |
| D-03 | Never expose secret values or sensitive legal content in status. | All steps | README D-03 | 锁 |
| D-04 | Preserve `load_json_config` safe-default behavior and add diagnostic path. | Step 1 config probe | README D-04 | 锁 |
| D-05 | M3 reports Office/MCP readiness only; restore behavior stays for M7. | Step 1 Office/MCP probe | README D-05 | 锁 |
| D-06 | Show pure-rule fallback as degraded, not equivalent. | Step 2 UI | README D-06 | 锁 |

### §2 附录 · 决策详情

| # | rationale | signoff_version | evidence_link |
|---|---|---|
| D-01 | Existing project path already uses `start.sh`; M3 should reduce choices, not add another launcher. | v1.0 | [README.md](README.md) §四 |
| D-02 | Current startup script and tests pin the Qwen3.5 9B MLX model; runtime experiments are M8. | v1.0 | `scripts/start_mlx9b_server.sh`, `tests/test_llm_config.py` |
| D-03 | Status surfaces sit near tokens and case data; exposing only readiness is enough for operations. | v1.0 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §8 |
| D-04 | Current callers rely on missing/invalid config collapsing to `{}`; changing that globally risks Discord/API regressions. | v1.0 | `legal_redactor/local_config.py` |
| D-05 | Existing Office API and MCP already implement restore actions; M3 should not expand that blast radius. | v1.0 | `legal_redactor/remote_api.py`, `legal_redactor/mcp_adapter.py` |
| D-06 | Pure-rule mode is useful operationally but lower recognition support must be visible. | v1.0 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §5 |

## §3 · Step 顺序

### Step 0 · POC + 防护栏

**时间盒**:`0.5 day`

1. Run `milestone-doc-check.mjs --dir` before Gate 0a.
2. Verify the existing Web and MLX health surfaces that M3 will build on.
3. Record fallback design for live Office/API/MCP/Discord checks when credentials
   are absent.

### Step 1 · status schema + probes

**时间盒**:`2 days`

- Add `legal_redactor/status.py`.
- Add diagnostic config read helper in `legal_redactor/local_config.py`.
- Implement MLX, CLI/cache, case root, Office API config, MCP config, and
  Discord config probes.
- Keep probes side-effect free and timeout bounded.

**Checkpoint 1**:

- `tests/test_status.py` covers all probe states.
- Existing config callers still pass tests.

### Step 2 · Web endpoint + first-screen panel

**时间盒**:`2 days`

- Add `GET /api/status`.
- Add a compact status panel on the Web UI first screen.
- Keep `GET /health` stable.
- Do not block `/redact` if diagnostics fail.

**Checkpoint 2**:

- `tests/test_web_app.py` covers endpoint shape and rendered status panel.
- Secret test proves token values are absent from JSON/HTML.

### Step 3 · tests + docs

**时间盒**:`1.5 days`

- Update restore/deploy docs only for readiness/status meanings and smoke
  commands.
- Run focused tests:

```bash
.venv/bin/python -m pytest tests/test_status.py tests/test_web_app.py tests/test_llm_config.py
```

### Step 4 · self-review + Gate 2

**时间盒**:`1 day`

- Run focused suite and service smoke where available.
- Run FFCS review for build scope with effective `codex + grok` policy.
- Update `_progress.md` DoD and handoff.

## §4 · 时间盒细分

| Step | 估时 | 起止 commit | 备注 |
|---|---|---|---|
| Step 0 · POC + 防护栏 | 0.5 day | TBD | Structural check + current health surface confirmation |
| Step 1 · status schema + probes | 2 days | TBD | Pure helpers first |
| Step 2 · Web endpoint + panel | 2 days | TBD | UI/API integration |
| Step 3 · tests + docs | 1.5 days | TBD | Focused pytest and docs |
| Step 4 · self-review + Gate 2 | 1 day | TBD | Review proof and handoff |
| **总计** | **5-7 days** | | |

## §5 · 跨模块签字规则

| 跨模块变更 | 影响下游 | D-XX 决策 | owner_signoffs | 测试覆盖 |
|---|---|---|---|---|
| New `/api/status` endpoint | M4, M5, M7, M8 may reuse readiness data | D-03, D-05 | project-local owner accepted by this spec | `tests/test_web_app.py` |
| Diagnostic config helper | Existing API/MCP/Discord callers | D-04 | project-local owner accepted by this spec | `tests/test_status.py` plus existing caller tests |

No external owner or credential signoff is required for Gate 0a. Live Office,
MCP, and Discord credentials are not required until M7 or service smoke.

## §6 · 服务端权威重算

This milestone includes status/policy-like words but no externally trusted
HTTP/RPC decision is accepted from a client. Server-side status is computed from
local raw facts: process/config presence, path existence, HTTP probes, and
explicit env/config values.

- D1 and D2 require server-created status schema and secret-safe output.
- S2 requires read-only status computation with no client-provided ready state.
- C1 returns computed status only; clients cannot submit component states.

## §7 · 文档维护扫

- [x] `_progress.md` updated with Gate 0a, Gate 2, validation profile, and effective profile.
- [x] README and execution plan remain linked from upstream split docs.
- [x] Implementation tail item recorded for M4: restart the existing 7860 Web process before using `/api/status` on that running instance.
- [x] Restore/deploy docs updated only for readiness/status meanings; restore behavior remains M7 scope.
- [x] `.gitignore` remains protective for pid/log/runtime files and sensitive sample/case output while unignoring M3 regression tests.

## §8 · 出口 checklist

- [x] `legal_redactor/status.py` and local config diagnostic helper implemented.
- [x] `/api/status` and first-screen status panel implemented.
- [x] `GET /health` remains stable.
- [x] Focused pytest suite passes.
- [x] Web/MLX smoke evidence recorded or skipped with reason.
- [x] Review artifacts for build Gate 2 pass under effective policy.
- [x] [_progress.md](_progress.md) DoD closed before handoff.
