---
milestone: M8-runtime-benchmark
status: planned
risk: low-medium
time_box: 5-7 days
requires: [M3-startup-status-diagnostics, M6-regression-measurement]
blocks: []
source: docs/planning/legal-redactor-workflow-efficiency/REQUIREMENTS.md
---

# M8 runtime benchmark

## Scope

Evaluate Rapid-MLX or other runtime changes only as an A/B benchmark. A runtime
change is useful only if it reduces total workflow time, improves reliability,
or lowers operating cost without degrading redaction/restore outcomes.

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

## M6 Input Contract

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
- `restore.unresolved_placeholder_count` when restore evidence exists; otherwise
  `restore` is `null`.
- `timing.gold_evaluation_ms`, `timing.report_generation_ms`,
  `timing.document_input_to_saved_case_ms`,
  `timing.discord_thread_to_restored_ms`.
- `privacy.safe_by_default` must stay `true`.

M8 must not read raw `matched` / `missing` / `extra` eval diagnostics, sample
entries, mapping values, restored text, or debug traces from M6 artifacts.

## Validation Pointers

- Benchmark report with reproducible inputs.
- MLX `/v1/models` smoke for expected model identity.
- Regression/eval comparison before any runtime default changes.
