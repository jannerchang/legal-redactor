---
domain: legal-redactor-workflow-efficiency
created: 2026-06-27
command: ffcs:need
status: split
---

# legal-redactor workflow efficiency readiness

## 1. Readiness Summary

The project is ready for planning and milestone split. The local FFCS reviewer
policy has been adjusted to require `codex` and `grok`; Grok custom CLI transport
has passed a real `review-runner.mjs run` smoke test. The old blocker where the
policy required unavailable `claude` no longer reflects the current local
configuration.

Product implementation can proceed after split/spec because the main code
surfaces already exist and the first improvements are local, reversible, and
testable. External credentials and physical machine checks are only needed for
Discord/Hermes restore milestones.

## 2. Decisions Needed

| Decision | Recommended default | Needed before |
|---|---|---|
| Office Mac authority | Keep Office Mac as source of truth for maps, originals, manifests, restored output | any restore workflow change |
| First milestone priority | Start with local startup/status/config diagnostics | implementation split |
| Discord/Hermes priority | Treat as second wave after local status is visible | remote restore hardening |
| Runtime optimization | Benchmark Rapid-MLX or alternatives only as optional A/B, not default | runtime milestone |
| Worktree/branch | Not required for this docs-only need; create a branch/worktree before broad implementation if the main checkout must stay stable | build/spec stage |
| Reviewer lanes | Use current local `codex + grok` policy only after artifacts exist for the specific review task | formal review setup |
| Sensitive sample handling | Keep samples local and verify push safety before any GitHub delivery | sample milestone and delivery |

## 3. Physical and Credential Preparation

| Item | Current expectation | Owner | Evidence needed |
|---|---|---|---|
| Office Mac case root | local/private case folder remains authority | user/agent | existing path and write permission |
| Home Mac Hermes | MCP adapter runs on Home Mac when restore is needed | user/agent | Hermes MCP config and `tools/list` smoke |
| Tailscale/private network | Office API bound to localhost or private IP only | user/agent | API URL and `GET /health` over private route |
| Office API token | local JSON or env var, never committed | user/agent | `Authorization: Bearer ...` smoke |
| Discord bot token | optional, only for thread creation/send redacted attachment | user/agent | local config and channel/thread API smoke |
| Discord command channel id | needed for Hermes thread creation request | user/agent | configured channel id and successful message send |
| Recent samples | newest confirmed local sample source | agent | `samples recent-errors` provenance check |
| Gold set | small local gold set for regression | user/agent | JSON path and baseline report |
| MLX model cache | `~/.cache/huggingface` on local disk | agent | `/v1/models` expected model id |
| Launch persistence | optional launchctl/Desktop launcher state | agent | service name, logs, restart command |

## 4. Config Readiness

Current config surfaces:

- Web and MLX startup:
  - `./start.sh`
  - `scripts/start_mlx9b_server.sh`
  - `LEGAL_REDACTOR_SKIP_MLX`
  - `LEGAL_REDACTOR_MLX_PORT`
  - `HF_HOME`
- Office API:
  - `LEGAL_REDACTOR_API_CONFIG`
  - `~/.config/legal-redactor/api.local.json`
  - `LEGAL_REDACTOR_API_TOKEN`
- Home MCP:
  - `LEGAL_REDACTOR_MCP_CONFIG`
  - `~/.config/legal-redactor/mcp.local.json`
  - `LEGAL_REDACTOR_API_URL`
  - `LEGAL_REDACTOR_API_TOKEN`
- Discord:
  - `discord_bot_token`
  - `discord_command_channel_id`

Readiness gaps:

- `legal_redactor/local_config.py` silently returns `{}` for missing or invalid
  JSON. That is safe for runtime but weak for diagnostics.
- The user-facing workflow does not yet show a single status page covering all
  config surfaces.
- `.claude/ffcs.local.md` still says `flow.launcher: claude-cli`, which is
  confusing in a Codex-hosted workflow. This should be cleaned up during FFCS
  config hardening, not mixed into product behavior.

## 5. Validation Plan

### 5.1 Docs and Planning Validation

- Read back `REQUIREMENTS.md` and `READINESS.md`.
- Count lines and module/workstream count.
- Do not create or mutate `.ff-state/manifest.json` during need.

### 5.2 Product Regression Validation

Use this focused suite for implementation milestones:

```bash
.venv/bin/python -m pytest \
  tests/test_web_app.py \
  tests/test_cases.py \
  tests/test_remote_api.py \
  tests/test_mcp_adapter.py \
  tests/test_sample_integration.py \
  tests/test_pipeline.py \
  tests/test_llm_config.py
```

Use full pytest before delivery when touching shared pipeline behavior:

```bash
.venv/bin/python -m pytest
```

### 5.3 Service Smoke Validation

- Web:
  - `GET http://127.0.0.1:7860/health`
- MLX:
  - `GET http://127.0.0.1:18080/v1/models`
  - expected id: `mlx-community/Qwen3.5-9B-MLX-4bit`
- Office API:
  - `GET /health`
  - authorized status lookup by known Discord thread id
- MCP:
  - JSON-RPC `initialize`
  - JSON-RPC `tools/list`
  - status tool against a known or intentionally missing thread id
- Discord:
  - create-thread request posts to command channel;
  - redacted attachment send posts only redacted text/file.

### 5.4 Sample and Accuracy Validation

- Verify newest sample provenance before changing rules.
- Run recent-error inspection before rule changes.
- Run targeted tests for risky sample behavior:
  - short person delete does not become broad blacklist;
  - one-character province abbreviation is not promoted unsafely;
  - trusted organization/location samples are reused narrowly;
  - mapping fragments inside trusted samples do not break full-entity masks.
- Run gold-set eval before and after recognition/rule changes.

## 6. FFCS Review Readiness

Current observed reviewer executables:

- `codex`: available.
- `agy`: available.
- `grok`: available.
- `claude`: not available.
- `opencode`: not available.

Current FFCS local review policy requires:

- `must_collect=[codex,grok]`
- `must_pass=[codex,grok]`
- `timeout_skippable=[claude,deepseek,glm]`

`grok` is configured as a custom CLI reviewer and has passed a real runner smoke
test at:

```text
.ff-state/reviews/grok-custom-cli-smoke-20260627180802/artifacts/grok-r0.json
```

Allowed next step:

- Produce split/spec artifacts and run the specific task review with `codex` and
  `grok` before claiming a Gate PASS.

Not allowed:

- Treat this main Codex analysis as peer review evidence.
- Label AGY, Grok, or OpenCode output as Claude, DeepSeek, or GLM artifacts.
- Claim Gate PASS without the required `.ff-state/reviews/.../artifacts/*.json`
  and chair signoff.

Future reviewer setup options:

- Install and authenticate `claude` CLI if the current `codex + claude` policy
  should remain.
- If write-mode `/ffcs:sync` is run, confirm that website Grok config includes
  the local hardening (`--no-plan --max-turns 8`) or re-apply the local override.
- Treat AGY as advisory until a valid artifact writer and policy mapping exist.

## 7. Suggested Milestone Split

Recommended next command:

```text
/ffcs:split legal-redactor-workflow-efficiency
```

Suggested split:

| Milestone | Purpose | External prep |
|---|---|---|
| M3-startup-status-diagnostics | One status path for Web, MLX, config, Office API, MCP, Discord | none |
| M4-guided-intake-case-binding | Fewer manual fields and clearer archive/thread states | sample case folders |
| M5-mapping-review-sample-loop | Faster map review and safer sample learning | recent samples |
| M6-regression-measurement | Gold/recent-sample dashboard and workflow metrics | gold set |
| M7-discord-hermes-restore-status | Restore readiness, status, and privacy hardening | Office/Home/Discord credentials |
| M8-runtime-benchmark | Optional Rapid-MLX or runtime A/B benchmark | benchmark documents |

## 8. Initial Acceptance Criteria

Before the first build milestone starts:

- Requirement and readiness docs exist under
  `docs/planning/legal-redactor-workflow-efficiency/`.
- Split docs exist under
  `docs/planning/legal-redactor-workflow-efficiency/milestones/`.
- Next command is recorded as `/ffcs:spec M3-startup-status-diagnostics`.
- No milestone manifest is created by need/split commands.
- Review/Gate status is reported only from real reviewer artifacts and chair
  signoff.

Before product delivery later:

- Focused pytest suite passes.
- Browser smoke verifies actual Web workflow.
- Service smoke verifies MLX/Web/API/MCP as applicable.
- Sensitive sample/map/original files are checked before any push.
