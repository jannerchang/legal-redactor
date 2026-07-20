# M9-rapid-mlx-live-benchmark · rapid-mlx-live-benchmark · execution plan

> **Basis**: [README.md](README.md), [../M8-runtime-benchmark/README.md](../M8-runtime-benchmark/README.md), [../../REQUIREMENTS.md](../../REQUIREMENTS.md)
> **Schema reference**: `/Users/example/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.1.14/templates/gate.schema.md`
> **Update rhythm**: synchronize this file and [_progress.md](_progress.md) at each step/gate
> **Version**: v1.0 · 2026-07-06

---

## §1 · Hard Gates

| id | title | description | evidence_required | pass_condition | block_severity | typical_count |
|---|---|---|---|---|---|---:|
| D1 | Live endpoints explicit | Compare named endpoint candidates only; baseline and Rapid-MLX cannot be conflated. | unit_test_count, integration_test_count | Report has separate labels/runtime kinds/base URL labels and records unavailability distinctly. | BLOCKER | 1 |
| D2 | M8 accuracy boundary | Accuracy and workflow regressions come from privacy-safe M8/M6 aggregate reports. | unit_test_count, doc_anchor | Raw eval diagnostics are never read or emitted by M9. | BLOCKER | 1 |
| D3 | Model identity gate | Each endpoint must expose the expected Qwen model or carry a non-comparable reason. | unit_test_count, live_probe_stdout | Wrong/missing model blocks automatic winner selection. | BLOCKER | 1 |
| D4 | Synthetic prompts only | Live speed probes use synthetic prompts and store only prompt profile metadata. | unit_test_count, grep_stdout | Report contains no prompt body, completion text, document text, samples, tokens, or mappings. | BLOCKER | 1 |
| D5 | No default switch | M9 does not modify runtime defaults or model choice. | diff_readback, grep_stdout | Diff against `start.sh`, `scripts/start_mlx9b_server.sh`, and config defaults is empty or unrelated. | BLOCKER | 1 |
| D6 | Comparable context | Speed recommendation requires matching M8 `benchmark_context` and quality non-regression. | unit_test_count | Context mismatch or quality regression returns manual/no-switch recommendation. | BLOCKER | 1 |
| D7 | Public sample boundary | Public SPC samples may be used by path/category metadata only. | grep_stdout, doc_anchor | Reports/docs contain only relative path/category/hash metadata and aggregate metrics. | HIGH | 1 |
| D8 | Missing Rapid-MLX fails closed | Missing CLI, startup failure, timeout, or HTTP error produces insufficient evidence, not PASS. | unit_test_count, integration_test_count | Candidate unavailability blocks auto recommendation and preserves error count/reason. | HIGH | 1 |
| P1 | Endpoint probe pure wrapper | Add testable helpers for `/v1/models` and `/v1/chat/completions` probing. | unit_test_count | Mocked HTTP fixtures produce model/timing/error summaries. | BLOCKER | 1 |
| P2 | Live report builder | Build M9 report from endpoint observations plus optional M8 report. | unit_test_count | Builder returns deterministic comparison and recommendation. | BLOCKER | 1 |
| P3 | Privacy sanitizer extended | Reuse M8 sanitizer and add M9 raw prompt/completion protections. | unit_test_count | Unsafe keys/absolute paths/Chinese raw text are rejected recursively. | BLOCKER | 1 |
| P4 | Runtime command metadata | Record launcher command metadata as labels only, not raw shell logs or absolute paths. | unit_test_count | Report stores `runtime_config_id` and `endpoint_label`, not command lines with paths. | HIGH | 1 |
| S1 | CLI live benchmark | Provide a local CLI path for endpoint probing and report generation. | integration_test_count | Synthetic mocked CLI invocation exits 0 and writes M9 JSON. | BLOCKER | 1 |
| S2 | Live error handling | Bad JSON, HTTP timeout, wrong model, and unavailable candidate fail without traceback. | integration_test_count | CLI exits or reports insufficient evidence deterministically with no partial unsafe output. | HIGH | 1 |
| S3 | Existing M8 command preserved | Existing `--runtime-benchmark-report` behavior remains compatible. | unit_test_count | Current M8 tests still pass. | BLOCKER | 1 |
| S4 | No external emission | M9 benchmark writes local JSON only and does not notify Discord/Hermes/webhooks. | grep_stdout | Scoped grep finds no notification transport in benchmark code path. | BLOCKER | 1 |
| N1 | No notification surface | Live benchmark has no subscriber/callback. | grep_stdout | No webhook/Telegram/Hermes/Discord calls in M9 code path. | BLOCKER | 1 |
| CA1 | JSON artifact | Persist a machine-readable M9 live benchmark report. | integration_test_count | JSON includes schema, endpoints, runtime comparison, quality comparison, recommendation, privacy. | BLOCKER | 1 |
| CA2 | Concise CLI summary | Print only labels, model status, timing deltas, and recommendation. | integration_test_count | Stdout omits full JSON, prompt bodies, response content, raw docs, and paths. | MEDIUM | 1 |
| CA3 | Operator docs | README documents baseline/candidate commands and interpretation. | doc_anchor | Operator can rerun baseline/Rapid-MLX comparison and understand insufficient-evidence output. | MEDIUM | 1 |
| T1 | RED-first tests | Add failing tests for M9 live report/probe behavior before implementation. | unit_test_count | RED failure output is recorded in `_progress.md`. | BLOCKER | 1 |
| T2 | Focused tests | Run `tests/test_runtime_benchmark.py` after implementation. | unit_test_count | Focused tests pass. | BLOCKER | 1 |
| T3 | Regression compatibility | Run M8/M6 regression benchmark tests together. | unit_test_count | `tests/test_runtime_benchmark.py tests/test_regression.py` pass. | BLOCKER | 1 |
| T4 | Full suite | Run full pytest before Gate 2 unless environment blocks. | unit_test_count | Full suite passes or environment failure is classified with focused evidence. | HIGH | 1 |
| E1 | Planning closeout | `_progress.md` records Gate artifacts, live evidence, and DoD closeout. | doc_anchor | Status moves to complete before first PR push. | BLOCKER | 1 |
| E2 | Runtime docs | README records M9 commands and no-default-switch caveat. | doc_anchor | Docs include both live and report-only commands. | MEDIUM | 1 |
| E3 | Sensitive artifact audit | Generated reports/logs/raw responses are not tracked. | grep_stdout | `git status`/`git ls-files` audit confirms no sensitive artifacts are staged. | BLOCKER | 1 |

## §V · Visual Acceptance Layer

| Field | Value |
|---|---|
| `design_confidence` | `0` |
| `design_autonomy` | `auto` |
| `freedom_level` | `L0` |
| `mutability` | `frozen` |
| `visual_evidence` | `not_required` |
| `visual_capability_status` | `skipped_with_ack` |
| `visual_skip_reason` | `non-visual runtime benchmark; no UI/game/motion/brand delivery` |

## §2 · Decisions

| # | Decision | Impact | Source | Status |
|---|---|---|---|---|
| M9.D-01 | Live evidence before recommendation | Report and final recommendation | README D-01 | locked |
| M9.D-02 | Use M8/M6 accuracy boundary | Quality comparison | README D-02 | locked |
| M9.D-03 | Synthetic endpoint prompts only | Probe privacy | README D-03 | locked |
| M9.D-04 | Same model identity required | Comparability | README D-04 | locked |
| M9.D-05 | No default runtime switch | Delivery scope | README D-05 | locked |
| M9.D-06 | Missing Rapid-MLX is evidence | Error handling | README D-06 | locked |
| M9.D-07 | Public SPC metadata only | Input boundary | README D-07 | locked |

### §2 Appendix · Decision Details

| # | rationale | signoff_version | evidence_link |
|---|---|---|
| M9.D-01 | The operator asked for a live Rapid-MLX versus `mlx_lm.server` comparison, so report-only M8 evidence is insufficient for M9. | v1.0 | user directive 2026-07-06 |
| M9.D-02 | Existing M8/M6 reports already enforce aggregate privacy and context matching. | v1.0 | [../M8-runtime-benchmark/README.md](../M8-runtime-benchmark/README.md) |
| M9.D-03 | Synthetic prompts can measure endpoint TTFT/total latency without transmitting legal text. | v1.0 | `legal_redactor/runtime_benchmark.py` |
| M9.D-04 | Comparing different models would mix runtime and model effects. | v1.0 | `legal_redactor/status.py` |
| M9.D-05 | Runtime defaults are product decisions outside automatic M9 delivery. | v1.0 | [../M8-runtime-benchmark/README.md](../M8-runtime-benchmark/README.md) |
| M9.D-06 | Headless workers must report actual availability instead of waiting for manual setup. | v1.0 | FFCS worker contract |
| M9.D-07 | Public sample documents are approved inputs, but reports remain privacy-safe. | v1.0 | user directives |

## §3 · Step Sequence

### Step 0 · Spec + POC

**Time box**: `0.5 day`

1. Run `milestone-doc-check.mjs --dir`.
2. POC E-1: detect live `mlx_lm.server` identity on `127.0.0.1:18080`.
3. POC E-2: detect Rapid-MLX CLI/server availability.
4. POC E-3: run a synthetic chat probe against the live baseline endpoint.
5. POC E-4: verify public SPC sample paths are available by metadata only.
6. Gate 0a and Gate 0b review.

### Step 1 · live report schema + probe helpers

**Time box**: `1 day`

- RED-first tests for M9 schema, model mismatch, candidate unavailability, and privacy.
- Add endpoint observation/report helpers to `legal_redactor/runtime_benchmark.py`.
- Keep existing M8 report API stable.

**tier**: `service`

### Step 2 · CLI and docs

**Time box**: `1 day`

- Add CLI flags for a local M9 live benchmark report.
- Print concise summary and write privacy-safe JSON.
- Update README with baseline/Rapid-MLX commands and no-default-switch caveat.

**tier**: `service`

### Step 3 · live evidence + Gate 2 + delivery

**Time box**: `1 day`

- Run focused tests and full validation.
- Run live baseline/Rapid-MLX evidence where locally available.
- Run `milestone-doc-check --gate2`, `pre-push-checklist`, Gate 2 review, PR/CI, merge guard, and cleanup.

**tier**: `service`

## §4 · Time Box

| Step | Estimate | Commit window | Notes |
|---|---:|---|---|
| Step 0 · Spec + POC | 0.5 day | uncommitted | live availability and privacy constraints |
| Step 1 · schema/probe | 1 day | uncommitted | tests first |
| Step 2 · CLI/docs | 1 day | uncommitted | local-only report |
| Step 3 · review/delivery | 1 day | uncommitted | PR/CI/merge |
| **Total** | **3-5 days** | | Medium complexity |

## §5 · Cross-Module Signoff

| Change | Downstream impact | Decision | owner_signoffs | Test coverage |
|---|---|---|---|---|
| M9 report schema | Later runtime/default decision consumes M9 report | M9.D-01, M9.D-05 | project-local owner accepted by this spec | `tests/test_runtime_benchmark.py` |
| Endpoint probe helpers | Local benchmark CLI calls OpenAI-compatible endpoints | M9.D-03, M9.D-04 | project-local owner accepted by this spec | mocked HTTP tests + live smoke |
| CLI live benchmark | Operator workflow | M9.D-06 | project-local owner accepted by this spec | CLI tests |

No external credential, remote host, or default runtime owner signoff is required
for Gate 0a. A future default switch remains a separate product decision.

## §6 · Server-Authoritative Recompute

M9 computes all recommendation fields locally:

- Endpoint model identity is computed from `/v1/models` payloads.
- TTFT/total latency/error counts are computed from local synthetic chat probe observations.
- Quality/workflow regression status is computed from M8/M6 aggregate reports, not caller labels.
- Missing candidate evidence blocks automatic runtime preference.
- Privacy checks run before JSON write.

## §7 · Documentation Sweep

- [ ] README includes M9 live benchmark command examples.
- [ ] M9 `_progress.md` records Gate 0a/0b/2 artifacts and DoD evidence.
- [ ] HUMAN_TASKS contains only external/manual work, if any.
- [ ] Step 0 POC report records PASS/fallback evidence.
- [ ] Generated benchmark JSON stays outside tracked artifacts unless sanitized fixture data is needed for tests.
- [x] No `DESIGN.md` is required because this is non-visual runtime work.

## §8 · Exit Checklist

- [ ] Five-file spec set is complete.
- [ ] POC E-1 through E-4 pass or fallback is recorded.
- [ ] D/P/S/N/C+A/T/E gates have evidence.
- [ ] `milestone-doc-check.mjs --gate2` passes.
- [ ] `pre-push-checklist.mjs` passes or records only allowed warnings.
- [ ] Gate 2 review passes with required artifacts.
- [ ] `_progress.md` §1 is `✅ 完成`; §3 Gate 2 and §8 DoD are closed before first PR push.
- [ ] PR checks are green.
- [ ] Merge guard artifact allows `auto_squash_merge` before any merge.
