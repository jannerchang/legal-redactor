---
milestone: M9-rapid-mlx-live-benchmark
module: rapid-mlx-live-benchmark
version: v1.0
created: 2026-07-06
status: Spec draft · Gate 0a pending
complexity: medium
risk: medium
time_box: 3-5 days
requires: [M8-runtime-benchmark]
blocks: []
source: docs/planning/legal-redactor-workflow-efficiency/REQUIREMENTS.md
validation_profile: standard
effective_profile: standard
---

# M9-rapid-mlx-live-benchmark · rapid-mlx-live-benchmark · module door

> **Status**: `Spec draft · Gate 0a pending`
> **Basis**: [../../REQUIREMENTS.md](../../REQUIREMENTS.md), [../../SPLIT.md](../../SPLIT.md), [../M8-runtime-benchmark/README.md](../M8-runtime-benchmark/README.md)
> **Complexity**: `medium`
> **Risk**: `medium`
> **Time box**: `3-5 days`
> **Upstream**: `M8-runtime-benchmark`

---

## 1. Basis

- The user asked to run M9 as a live benchmark comparing Rapid-MLX with the
  current `mlx_lm.server` path to determine which is faster and which is more
  accurate.
- M8 delivered the privacy-safe benchmark report framework and default-switch
  guardrails, but did not perform a live Rapid-MLX versus `mlx_lm.server`
  operational A/B run.
- M3/M8 already require model identity checks so the benchmark must prove the
  endpoint under test is the intended local Qwen runtime, not merely any
  listener on the MLX port.

## 2. Goal

Produce a reproducible, privacy-safe live A/B benchmark for:

- baseline: current `mlx_lm.server` serving
  `mlx-community/Qwen3.5-9B-MLX-4bit`;
- candidate: Rapid-MLX or the closest locally installed Rapid-MLX-compatible
  serving path for the same model.

The result must compare speed and quality together. A faster runtime is not a
better runtime if recall, precision, correction count, restore safety, error
rate, or model identity regresses.

## 3. Scope

### 3.1 In Scope

- Detect or document the local Rapid-MLX launch surface and compare it against
  the existing `scripts/start_mlx9b_server.sh` / `mlx_lm.server` baseline.
- Run both candidates on matching inputs, gold set, benchmark context, and
  privacy-safe M6/M8 report contracts.
- Capture at least first-token latency, total redaction/eval duration, memory
  evidence when available, error rate, precision, recall, F1, and manual
  correction metrics.
- Use approved public Supreme People's Court sample inputs under `samples/`
  only by path/category metadata in generated reports; do not write raw document
  text, mapping values, restored text, prompts, completions, tokens, or absolute
  Office paths into tracked artifacts.
- Produce a concise operator-facing recommendation: faster with no quality
  regression, quality regression, insufficient evidence, or manual review.

### 3.2 Out of Scope

- Do not switch the default runtime/model during M9 without a separate explicit
  product decision.
- Do not tune recognition rules or prompts based on live benchmark misses.
- Do not send benchmark material to Discord, Hermes, webhooks, or cloud
  inference providers.
- Do not weaken the existing pure-rule fallback or startup model identity gate.

### 3.3 Key Deliverables

| # | Path | Type | Notes |
|---|---|---|---|
| 1 | `scripts/` or `legal_redactor/` | code | Live benchmark runner or reusable probe wrapper |
| 2 | `tests/` | tests | Unit/integration coverage with network mocked where needed |
| 3 | `README.md` | docs | Reproducible live benchmark commands and interpretation |
| 4 | `docs/planning/legal-redactor-workflow-efficiency/milestones/M9-rapid-mlx-live-benchmark/*` | docs | Spec, POC, progress, Gate evidence |

## 4. Decisions

| # | Decision | Rationale | Signoff | Evidence |
|---|---|---|---|---|
| D-01 | Live evidence before recommendation | M9 exists because M8 created a report contract but did not run a live Rapid-MLX versus `mlx_lm.server` comparison. | v1.0 | user directive 2026-07-06 |
| D-02 | M8/M6 remains the accuracy boundary | Accuracy is read from privacy-safe M6/M8 aggregate reports, not from raw matched/missing/extra diagnostics. | v1.0 | [../M8-runtime-benchmark/README.md](../M8-runtime-benchmark/README.md) |
| D-03 | Endpoint speed probes use synthetic prompts | First-token/total endpoint timing does not require legal document text. | v1.0 | `legal_redactor/runtime_benchmark.py` |
| D-04 | Same model identity required | Runtime speed is comparable only when both endpoints expose the expected Qwen 9B model or record a non-comparable reason. | v1.0 | `scripts/start_mlx9b_server.sh`, `legal_redactor/status.py` |
| D-05 | No default runtime switch | M9 may recommend an operator decision, but it must not change `start.sh`, `scripts/start_mlx9b_server.sh`, or default `--llm`. | v1.0 | M8 D-01/D-05 |
| D-06 | Rapid-MLX absence is evidence | If Rapid-MLX cannot be started or probed locally, the report says `insufficient_evidence` instead of pretending a comparison ran. | v1.0 | headless worker constraint |
| D-07 | Public SPC samples remain metadata-only | Existing public Supreme People's Court inputs may be used for benchmark selection, but tracked artifacts only carry relative path/category hashes and aggregate metrics. | v1.0 | user directives 2026-07-03 and 2026-07-06 |

## 5. Live Benchmark Contract

M9 writes `M9-rapid-mlx-live-benchmark-report/v1`. The report is local JSON and
extends the M8 comparison with live endpoint evidence:

| key | meaning |
|---|---|
| `schema_version` | Must be `M9-rapid-mlx-live-benchmark-report/v1` |
| `generated_at` | UTC timestamp |
| `benchmark_context` | Same privacy-safe M8 context fields |
| `endpoints[]` | Baseline/candidate labels, runtime kind, base URL label, model-match status, prompt count, timing stats, error stats |
| `runtime_comparison` | Baseline versus candidate deltas for first-token, total latency, error rate, and model comparability |
| `quality_comparison` | M8/M6 recommendation and aggregate quality/workflow regression status |
| `recommendation` | `rapid_mlx_faster_no_quality_regression`, `mlx_lm_server_preferred`, `insufficient_evidence`, or `manual_review` |
| `privacy` | Safe-by-default flags; no raw prompts, completions, sample entries, mappings, restored text, tokens, absolute paths, or sensitive traces |

Live speed prompts are synthetic, short, deterministic, and stored only as a
prompt profile id such as `synthetic-openai-chat-v1`. Response bodies are not
stored. Accuracy evidence comes from matching M8/M6 aggregate reports for the
same `benchmark_context`.

## 6. Acceptance Direction

- The benchmark can be rerun locally with clear commands.
- `mlx_lm.server` and Rapid-MLX candidates use comparable model/config evidence.
- The generated comparison is privacy-safe and compatible with the M8 report
  guardrails.
- The final answer states which path is faster and whether quality is unchanged,
  degraded, or not proven from the available evidence.

## 7. Primary Surfaces

- `legal_redactor/runtime_benchmark.py`
- `legal_redactor/__main__.py`
- `tests/test_runtime_benchmark.py`
- `README.md`
- `scripts/start_mlx9b_server.sh` for baseline identity evidence only
