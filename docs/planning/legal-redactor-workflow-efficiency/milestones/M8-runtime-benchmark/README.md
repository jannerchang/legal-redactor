---
milestone: M8-runtime-benchmark
module: runtime-benchmark
version: v1.0
created: 2026-07-03
status: Build complete · Gate 2 PASS · PR pending
complexity: medium
risk: low-medium
time_box: 5-7 days
requires: [M3-startup-status-diagnostics, M6-regression-measurement]
blocks: []
source: docs/planning/legal-redactor-workflow-efficiency/REQUIREMENTS.md
validation_profile: standard
effective_profile: standard
---

# M8-runtime-benchmark · runtime-benchmark · module door

> **Status**: `Build complete · Gate 2 PASS · PR pending`
> **Basis**: [../../REQUIREMENTS.md](../../REQUIREMENTS.md), [../../SPLIT.md](../../SPLIT.md), [../M6-regression-measurement/README.md](../M6-regression-measurement/README.md)
> **Complexity**: `medium`
> **Risk**: `low-medium`
> **Time box**: `5-7 days`
> **Upstream**: `M3-startup-status-diagnostics`, `M6-regression-measurement`

---

## 1. Basis

- The user asked whether Rapid-MLX could improve this repo. The prior fit
  assessment concluded it belongs in M8 benchmarking, not in an immediate
  default runtime change.
- M6 now emits privacy-safe regression reports with aggregate quality,
  workflow, sample provenance, restore, timing, and privacy fields.
- M3 already owns startup/status diagnostics, including MLX model identity
  probes. M8 should reuse those probes instead of weakening startup safety.

## 2. Goal

Evaluate Rapid-MLX or other compatible local runtime changes only through a
repeatable A/B benchmark. A candidate runtime is useful only if it reduces total
workflow time, improves reliability, or lowers operating cost without degrading
redaction/restore outcomes.

Completion definition for build:

- Add a privacy-safe benchmark report schema and CLI path that compare two or
  more runtime runs using the same M6 regression report contract.
- Capture first-token latency, total redaction/eval duration, memory, error
  rate, manual correction count, and available Web workflow timing.
- Keep the default runtime/model unchanged unless a later product decision uses
  benchmark evidence to approve a switch.
- Preserve pure-rule fallback and existing `--llm off` behavior for emergency
  or low-cost operation.
- Gate 0a, Gate 0b, and Gate 2 review pass with the configured `codex + grok`
  policy.

## 3. Scope

### 3.1 In Scope

- Add a runtime benchmark module, likely `legal_redactor/runtime_benchmark.py`,
  with pure helpers for loading M6 reports, validating privacy-safe fields, and
  comparing runtime candidates only when their privacy-safe benchmark contexts
  match.
- Add CLI flags in `legal_redactor/__main__.py` for a benchmark report command
  that reads one or more M6 regression reports and optional runtime probe data.
- Add optional runtime probe helpers that can call MLX-compatible
  `/v1/models` and `/v1/chat/completions` endpoints with synthetic prompt data
  only.
- Use existing public Supreme People's Court documents under `samples/` as
  approved benchmark/test inputs when document-level timing is needed. Reports
  still must not emit raw matched/missing/extra diagnostics, restored text,
  sample entries, mapping values, or sensitive debug traces.
- Add tests for schema validation, M6 contract validation, candidate comparison,
  privacy boundaries, malformed input handling, and CLI output.
- Update README/operator docs with reproducible benchmark commands.

### 3.2 Out of Scope

- Do not switch from `mlx_lm.server` to Rapid-MLX by default during M8.
- Do not change `mlx-community/Qwen3.5-9B-MLX-4bit` or add cloud inference as a
  default path.
- Do not read raw M6 diagnostics, sample entries, mapping values, restored text,
  absolute Office paths, tokens, or debug traces.
- Do not send benchmark material to Discord/Hermes/webhooks.
- Do not tune recognition prompts/rules based on benchmark output; M8 only
  measures runtime behavior.

### 3.3 Key Deliverables

| # | Path | Type | Notes |
|---|---|---|---|
| 1 | `legal_redactor/runtime_benchmark.py` | code | Benchmark report schema, M6 report validation, candidate comparison |
| 2 | `legal_redactor/__main__.py` | CLI | Local benchmark-report flags and concise summary |
| 3 | `tests/test_runtime_benchmark.py` | tests | Unit and CLI coverage |
| 4 | `README.md` | docs | Operator benchmark commands and no-default-switch caveat |
| 5 | `docs/planning/legal-redactor-workflow-efficiency/milestones/M8-runtime-benchmark/*` | docs | Spec, POC, progress, Gate evidence |

## 4. Decisions

| # | Decision | Rationale | Signoff | Evidence |
|---|---|---|---|---|
| D-01 | Benchmark before runtime switch | Runtime changes can improve speed while degrading quality or reliability; default changes need measured evidence. | v1.0 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md), prior Rapid-MLX assessment |
| D-02 | Consume only M6 safe reports | M6 is the privacy boundary for quality/workflow metrics; M8 must not reopen raw diagnostics. | v1.0 | [../M6-regression-measurement/README.md](../M6-regression-measurement/README.md) |
| D-03 | Candidate reports are comparable by label | Runtime candidates should be compared as named runs, not as hidden global state. | v1.0 | M8 CLI/report contract |
| D-04 | First-token probe is synthetic-only | Endpoint latency probes must not transmit legal document text or sample entries. | v1.0 | `legal_redactor/llm.py`, `scripts/start_mlx9b_server.sh` |
| D-05 | MLX model identity remains a hard gate | A port listener is not enough; `/v1/models` must still report the expected model. | v1.0 | `scripts/start_mlx9b_server.sh` |
| D-06 | Pure-rule fallback remains explicit | `--llm off` is an operational fallback and must stay benchmarkable. | v1.0 | `legal_redactor/__main__.py` |
| D-07 | Benchmark report is local JSON | Local JSON is reproducible and can feed later product decisions without screenshots or raw logs. | v1.0 | M8 deliverables |
| D-08 | Public SPC samples allowed as inputs | Existing public Supreme People's Court documents under `samples/` are approved for benchmark/test input selection, but report output stays privacy-safe. | v1.0 | user directive 2026-07-03 |
| D-09 | Context mismatch blocks recommendations | Candidates must carry matching privacy-safe `benchmark_context` for gold set, document/sample input set, and benchmark profile before M8 can recommend a runtime. | v1.0 | Gate 0a r0 codex HIGH-1 |

## 5. M6 Input Contract

M8 consumes M6 JSON artifacts written by:

```bash
.venv/bin/python -m legal_redactor --eval-gold path/to/gold.json --regression-report output/regression-report.json
```

Required M6 report fields for M8:

- `schema_version`: must be `M6-regression-report/v1`.
- `gold.case_count`, `gold.precision`, `gold.recall`, `gold.f1`,
  `gold.true_positive`, `gold.false_positive`, `gold.false_negative`.
- `workflow.manual_corrections`, `workflow.false_positive_deletes`,
  `workflow.missing_adds`, `workflow.suppressed_risky_entry_count`.
- `samples.newest_sample_provenance.exists`, `sample_file`, `mtime`,
  `entry_count`, `has_updated_at`, `updated_at`.
- `restore.unresolved_placeholder_count` when restore evidence exists;
  otherwise `restore` is `null`.
- `timing.gold_evaluation_ms`, `timing.report_generation_ms`,
  `timing.document_input_to_saved_case_ms`,
  `timing.discord_thread_to_restored_ms`.
- `privacy.safe_by_default` must stay `true`.

M8 must not read raw `matched`, `missing`, `extra`, sample entries, mapping
values, restored text, absolute paths, tokens, or debug traces from M6 artifacts.

## 6. Benchmark Report Contract

M8 writes `M8-runtime-benchmark-report/v1`. The report is the authoritative
local artifact for later runtime decisions.

| key | type | meaning |
|---|---|---|
| `schema_version` | string | Must be `M8-runtime-benchmark-report/v1` |
| `generated_at` | string | UTC generation timestamp |
| `benchmark_context` | object | Shared context required across compared candidates |
| `candidates[]` | list | One object per labeled runtime run |
| `comparison` | object | Baseline/candidate deltas and compatibility result |
| `recommendation` | object | `action`, `reason`, and evidence flags |
| `privacy` | object | Safe-by-default flags proving raw content was omitted |

`benchmark_context` is privacy-safe and must not contain raw document text,
sample entries, mappings, restored content, tokens, or absolute Office paths.
It contains only comparable identifiers:

| field | required | meaning |
|---|---|---|
| `gold_set_id` | yes | Operator-chosen stable id, such as `spc-construction-public-v1` |
| `gold_set_hash` | yes | Hash of the gold-set fixture or manifest, not raw diagnostics |
| `input_set_id` | yes | Stable id for the document/sample set |
| `input_set_kind` | yes | `synthetic`, `public_spc_sample`, or `operator_private_local` |
| `input_set_hash` | yes | Hash of a manifest containing relative paths/categories only |
| `sample_provenance_id` | no | Metadata-only M6 sample provenance id when available |
| `benchmark_profile` | yes | Comparable profile, for example `m8-default-v1` |

Each candidate must include:

| field | required | nullable reason |
|---|---|---|
| `label` | yes | none |
| `runtime_kind` | yes | none |
| `runtime_config_id` | yes | none |
| `m6_report_path` | yes | path may be relative to working directory |
| `quality` | yes | projected from M6 `gold` |
| `workflow` | yes | projected from M6 `workflow` |
| `timing.total_redaction_eval_ms` | yes | null allowed only with `total_redaction_eval_reason` |
| `timing.first_token_latency_ms` | yes | null allowed only with `first_token_latency_reason` |
| `timing.web_workflow_ms` | yes | null allowed only with `web_workflow_reason` |
| `resources.peak_memory_mb` | yes | null allowed only with `peak_memory_reason` |
| `errors.error_count` | yes | integer, defaults to 0 when no error evidence exists |
| `errors.error_rate` | yes | null allowed only with `error_rate_reason` |
| `probe.model_match` | no | nullable when no endpoint probe was run |

Recommendation rules:

- If candidate `benchmark_context` values differ, set
  `recommendation.action="manual_review"` and
  `comparison.compatible=false`; do not choose a winner.
- If quality or privacy regresses, do not recommend a runtime switch.
- If first-token latency, total duration, memory, or error-rate evidence is
  missing, emit deltas with reason fields and block auto-switch
  recommendations.
- `recommendation.action="candidate_faster_no_regression"` is only allowed
  when contexts match, privacy is safe, quality/workflow do not regress, and
  required timing/error/resource evidence exists.

## Primary Surfaces

- `scripts/start_mlx9b_server.sh`
- `legal_redactor/llm.py`
- current CLI eval paths
- future benchmark script or planning notes under `scripts/` or this planning
  domain

## Acceptance Direction

- Compare the same documents, samples, and gold set across candidate runtimes.
- Capture first-token latency, total redaction time, memory, error rate, manual
  correction count, and Web workflow timing.
- Do not change the default model or require cloud inference without benchmark
  evidence and explicit product decision.
- Preserve pure-rule fallback for emergency/cheap operation.

## Validation Pointers

- Benchmark report with reproducible inputs.
- MLX `/v1/models` smoke for expected model identity.
- Regression/eval comparison before any runtime default changes.

## 7. Risk And Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| Benchmark report leaks legal text | Privacy breach | Validate M6 privacy flags and reject raw diagnostic keys/Chinese free text fields in M8 reports |
| Speed-only comparison hides quality regression | Bad default switch | Compare quality and workflow metrics alongside latency |
| Wrong service listens on MLX port | False benchmark | Reuse model identity probe and record endpoint/model evidence |
| Rapid-MLX CLI shape differs | Benchmark blocked | Treat candidate runtime command as optional metadata; benchmark report can compare existing M6 artifacts first |
| Synthetic endpoint probe becomes real-data probe | Sensitive data exposure | Hard-code synthetic prompt/probe text and document the boundary |
| Public sample input leaks into artifacts | Sensitive-report regression | Refer to public documents by path/category only; benchmark reports contain metrics/deltas rather than raw text or raw eval diagnostics |

## 8. Time Box

| Step | Estimate | Notes |
|---|---:|---|
| Step 0 · POC + guardrails | 0.5-1 day | Validate M6 report contract, runtime probe feasibility, schema shape |
| Step 1 · report schema + pure compare | 1-2 days | Load/validate candidate reports and calculate deltas |
| Step 2 · CLI + optional probe | 1-2 days | Local JSON output, concise summary, deterministic errors |
| Step 3 · docs + validation + Gate 2 | 1-2 days | Focused tests, doc closeout, reviews, PR/CI |
| **Total** | **5-7 days** | Medium complexity, low-medium risk |

## 9. Milestone Docs

| Piece | File | Purpose |
|---|---|---|
| 1 · README | [README.md](README.md) | Milestone door and decisions |
| 2 · EXECUTION_PLAN | [EXECUTION_PLAN.md](EXECUTION_PLAN.md) | Hard gates and build steps |
| 3 · HUMAN_TASKS | [HUMAN_TASKS.md](HUMAN_TASKS.md) | External/manual blockers only |
| 4 · step-0-poc-report | [step-0-poc-report.md](step-0-poc-report.md) | POC commands, findings, fallback |
| 5 · _progress | [_progress.md](_progress.md) | Gate/progress/DoD state |
