# M6-regression-measurement · regression-measurement · 执行计划

> **依据**:[README.md](README.md), [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §6.4, [../../SPLIT.md](../../SPLIT.md)
> **格式**:七层硬门槛 + 决策表 + Step 顺序 + 时间盒 + 跨模块签字 + 服务端权威重算 + 文档维护扫
> **schema 引用**:/Users/example/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.0.123/templates/gate.schema.md
> **更新节奏**:Step 进 / 出时同步本文件 + [_progress.md](_progress.md)
> **版本**:v1.0 · 2026-06-29

---

## §1 · 七层硬门槛

| id | title | description | evidence_required | pass_condition | block_severity | typical_count |
|---|---|---|---|---|---|---:|
| D1 | Report schema fixed | Define a stable regression report schema with `gold`, `workflow`, `samples`, `restore`, `timing`, `privacy`, and `regression_suggestions` sections. | unit_test_count, doc_anchor | Tests fail if required top-level keys disappear or raw sample/original/map fields are emitted by default. | BLOCKER | 1 |
| D2 | Gold metrics preserved | Preserve existing precision, recall, F1, TP, FP, FN, and evaluator compatibility while projecting only sanitized per-case counts into M6's default `gold` object. | unit_test_count, integration_test_count | Existing `--eval-gold` behavior still passes; M6 regression JSON contains aggregate metrics and per-case missing/extra counts but no raw `matched`/`missing`/`extra` originals or masks. | BLOCKER | 1 |
| D3 | M5 summary consumed | Aggregate M5 `sample_summary` keys without parsing raw sensitive sample entries. | unit_test_count | Synthetic M5 summaries produce manual correction, false-positive delete, missing add, suppressed-risk, and suggestion totals. | BLOCKER | 1 |
| D4 | Sample privacy boundary | Reports and docs omit sample originals, masked values, restored text, maps, and debug traces by default. | unit_test_count, grep_stdout | Tests and grep prove output contains only metadata/counts unless an explicit unsafe debug mode is absent from M6. | BLOCKER | 1 |
| D5 | Newest sample gate | Verify newest sample provenance before any sample-driven tuning is reported as allowed. | unit_test_count, grep_stdout | Report contains metadata-only newest sample freshness and blocks/flags tuning when provenance is missing. | BLOCKER | 1 |
| D6 | Restore placeholder metric | Count unresolved restore placeholders only when redacted text/map evidence is supplied; otherwise return `null`. | unit_test_count | Tests cover evidence-present count and evidence-absent null behavior. | HIGH | 1 |
| D7 | Timing scope fixed | Capture local evaluation/redaction/report durations, compute `document_input_to_saved_case_ms` when input/save timestamp evidence exists, and explicitly defer Discord-to-restore timing to M7. | unit_test_count, doc_anchor | Report timing fields are present; saved-case timing is an integer or `null` with reason; M7-only fields are null/deferred. | HIGH | 1 |
| D8 | Threshold exits | Support fail-under precision/recall thresholds for regression commands without changing current eval CLI semantics. | integration_test_count | CLI returns non-zero below threshold and zero above threshold using synthetic gold data. | HIGH | 1 |
| D9 | Model default unchanged | M6 must not alter the fixed MLX model, startup path, or model picker state. | grep_stdout | Diff/readback proves model defaults and `start.sh` runtime behavior are unchanged. | BLOCKER | 1 |
| P1 | Gold projector pure | Add a pure projector that converts existing evaluation reports into privacy-safe M6 `gold` objects. | unit_test_count | Synthetic evaluation report maps aggregate metrics and per-case counts while dropping raw `original`, `masked`, `matched`, `missing`, `extra`, `warnings`, and `leaks` payloads from the default M6 report. | BLOCKER | 1 |
| P2 | Workflow aggregator pure | Add a pure aggregator for one or more M5 sample summaries. | unit_test_count | Aggregator sums counts and merges suggestions deterministically. | BLOCKER | 1 |
| P3 | Sample provenance pure | Add a metadata-only helper for newest sample provenance. | unit_test_count | Helper returns file name, mtime, total/count fields only, never entry text. | BLOCKER | 1 |
| P4 | Restore metric pure | Add a pure restore placeholder metric helper. | unit_test_count | Helper counts placeholders when supplied text/map evidence is complete and returns null otherwise. | HIGH | 1 |
| P5 | Privacy sanitizer pure | Add a sanitizer/assertion helper for regression report payloads. | unit_test_count | Tests fail if `original`, `masked`, raw map, restored text, or sample entry arrays leak. | BLOCKER | 1 |
| P6 | Timing wrapper pure | Add bounded timing helpers using monotonic clock values and supplied case/redaction timestamps. | unit_test_count | Timings are non-negative integers when evidence exists, `null` with reason when absent, and report generation works under patched clocks. | MEDIUM | 1 |
| S1 | CLI report command | Provide a local command for regression measurement that writes a privacy-safe JSON report and prints a concise summary. | integration_test_count | Synthetic command creates the report file, exits 0, and does not copy raw eval diagnostics into the default M6 artifact. | BLOCKER | 1 |
| S2 | Bounded JSON parsing | Parse M5 summary inputs and gold reports with clear errors for invalid JSON or unexpected shapes. | unit_test_count, integration_test_count | Malformed input returns a deterministic error without stack trace or partial report. | HIGH | 1 |
| S3 | Server-authoritative metrics | Do not accept browser category/status labels as metrics; consume only M5 summary payloads or local evaluator outputs. | integration_test_count | Forged labels in summary-like input do not change official counts. | HIGH | 1 |
| S4 | No report overwrite surprise | Report output path creation is deterministic and does not overwrite unrelated case artifacts by default. | integration_test_count | Tests cover explicit output path and default safe output directory. | MEDIUM | 1 |
| N1 | No external notification | Regression reports must not send samples, maps, originals, restored text, or metrics to Discord/Hermes/webhooks. | grep_stdout, unit_test_count | Report path has no Discord/Hermes/MCP calls and tests use local files only. | BLOCKER | 1 |
| CA1 | CLI summary | Print compact local metrics summary for humans. | integration_test_count | CLI stdout includes case count, precision/recall/F1 when gold exists, workflow correction counts when summaries exist, and saved-case timing when evidence exists. | HIGH | 1 |
| CA2 | JSON artifact | Persist machine-readable JSON report for M8 and future comparison. | integration_test_count | JSON report validates against required top-level keys and safe privacy flags. | BLOCKER | 1 |
| CA3 | Operator docs | Update README or milestone docs with safe commands and sample privacy caveats. | doc_anchor | Docs include gold-set command, M5 summary input, and newest-sample metadata warning. | MEDIUM | 1 |
| T1 | Regression tests | Add focused regression-report unit tests. | unit_test_count | `.venv/bin/python -m pytest tests/test_regression.py` passes. | BLOCKER | 1 |
| T2 | Eval CLI tests | Cover threshold exit, existing eval compatibility, and privacy-safe M6 projection using synthetic gold data. | integration_test_count | Focused CLI/evaluation tests pass without MLX or real samples and assert raw entity diagnostics are omitted from M6's default report. | BLOCKER | 1 |
| T3 | Sample privacy tests | Cover sample provenance and M5 summary aggregation with synthetic inputs. | unit_test_count | Tests prove no raw sample strings in report. | BLOCKER | 1 |
| T4 | Restore metric tests | Cover unresolved placeholder count and absent evidence null. | unit_test_count | Restore metric tests pass. | HIGH | 1 |
| T5 | Full focused suite | Run focused M6 suite plus existing sample/pipeline tests. | unit_test_count | Focused suite passes before Gate 2. | BLOCKER | 1 |
| T6 | Sensitive audit | Audit tracked files and report output for sample/map/original/restored text leakage before delivery. | grep_stdout | `git ls-files samples` empty and no generated report with sensitive data is tracked. | BLOCKER | 1 |
| E1 | README docs | Update README or operator docs for regression measurement commands. | doc_anchor | User can run local measurement without reading code. | MEDIUM | 1 |
| E2 | M8 handoff | Record exact report fields M8 can consume for runtime A/B benchmarks. | doc_anchor | M8 can start without rediscovering report schema. | HIGH | 1 |
| E3 | Progress closeout | `_progress.md` records Gate 0a/0b/2 artifacts, profile, POC, and DoD evidence. | doc_anchor | Gate closeout is complete before handoff. | BLOCKER | 1 |
| E4 | POST_GA observation | Keep POST_GA plan for report privacy and metric usefulness after local use. | doc_anchor | POST_GA plan exists and is linked from closeout. | MEDIUM | 1 |

## §2 · 决策表

| # | 决策 | 影响范围 | 来源 | 状态 |
|---|---|---|---|---|
| D-01 | Measure before tuning. | Build order/tests/docs | README D-01 | 锁 |
| D-02 | Reuse existing gold evaluator. | `evaluation.py`, CLI, tests | README D-02 | 锁 |
| D-03 | Consume M5 summary keys first. | M5/M6 contract | README D-03 | 锁 |
| D-04 | Keep report privacy-safe by default. | Report schema/tests/docs | README D-04 | 锁 |
| D-05 | Require newest-sample provenance before tuning. | Sample workflow | README D-05 | 锁 |
| D-06 | Restore unresolved count only with evidence. | Restore metric | README D-06 | 锁 |
| D-07 | Defer remote timing to M7. | M6/M7 boundary | README D-07 | 锁 |
| D-08 | JSON report is authoritative. | M8 handoff | README D-08 | 锁 |
| D-09 | Do not change model defaults. | Runtime/startup | README D-09 | 锁 |

### §2 附录 · 决策详情

| # | rationale | signoff_version | evidence_link |
|---|---|---|
| D-01 | Requirements explicitly require focused regression checks before sample-driven rule changes. | v1.0 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §4 story 6 |
| D-02 | Existing evaluator already handles JSON cases and emits precision/recall/F1. | v1.0 | `legal_redactor/evaluation.py:29-63` |
| D-03 | M5 Gate 2 exported stable summary keys and handoff says M6 should not parse raw sample files for correction counts. | v1.0 | [../M5-mapping-review-sample-loop/_progress.md](../M5-mapping-review-sample-loop/_progress.md) Gate 2 followup |
| D-04 | Sensitive samples, maps, originals, and restored text must remain local/private. | v1.0 | [../../SPLIT.md](../../SPLIT.md) Signoff Needs |
| D-05 | Freshness prevents stale sample blacklists or risky mappings from degrading recall. | v1.0 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §6.4 |
| D-06 | Existing restore preview can provide evidence when text/map are available; absent evidence must not be guessed. | v1.0 | `legal_redactor/restore.py:42-61` |
| D-07 | Discord/Hermes timing depends on M7 readiness and credentials. | v1.0 | [../../SPLIT.md](../../SPLIT.md) M7 dependency |
| D-08 | M8 needs comparable JSON artifacts for runtime A/B. | v1.0 | [../../SPLIT.md](../../SPLIT.md) M6/M8 dependency |
| D-09 | Default model changes are explicitly benchmark-gated. | v1.0 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §3 and §6.5 |

## §3 · Step 顺序

### Step 0 · POC + 防护栏

**时间盒**:`1 day`

1. Run `milestone-doc-check.mjs --dir` before Gate 0a.
2. POC E-1: run a synthetic gold-set eval command and confirm current metric fields plus the required privacy-safe M6 projection boundary.
3. POC E-2: inspect M5 `sample_summary` output shape and confirm aggregation can use synthetic payloads.
4. POC E-3: verify newest-sample provenance can be checked by metadata and Git audit without printing sample bodies.
5. POC E-4: inspect restore preview path and confirm unresolved placeholder metrics are implementable.
6. POC E-5: inspect case manifest/redaction timestamp paths and confirm saved-case timing can be computed or reported as `null`.
7. Update `step-0-poc-report.md`, then run Gate 0b review before build.

### Step 1 · schema + pure metrics

**时间盒**:`2 days`

- Add report dataclasses/helpers for `gold`, `workflow`, `samples`, `restore`,
  `timing`, `privacy`, and suggestions.
- Add synthetic unit tests before implementation for report schema, M5 summary
  aggregation, sample provenance redaction, and restore placeholder count.

**Checkpoint 1**:

- `tests/test_regression.py` covers pure helpers and privacy sanitizer.

### Step 2 · CLI + report output

**时间盒**:`2 days`

- Add a local regression measurement command or flags.
- Reuse existing `evaluate_gold_file()` for gold-set metrics, then sanitize the
  M6 default projection instead of embedding raw evaluator diagnostics.
- Write JSON report to an explicit output path or safe default under `output/`.
- Keep threshold exits deterministic.

**Checkpoint 2**:

- CLI integration tests cover synthetic gold input, privacy-safe output JSON,
  threshold pass/fail, saved-case timing evidence/null behavior, and invalid JSON.

### Step 3 · docs + validation + Gate 2

**时间盒**:`2-3 days`

- Update README/operator docs with safe commands.
- Update M8 handoff with report fields.
- Run focused tests:

```bash
.venv/bin/python -m pytest tests/test_regression.py tests/test_sample_integration.py tests/test_pipeline.py
```

- Run full pytest if shared pipeline/evaluator behavior changes.
- Audit Git/tracked files for generated reports, samples, maps, originals, restored text, and debug traces.
- Run FFCS Gate 2 review with effective `codex + grok` policy.

## §4 · 时间盒细分

| Step | 估时 | 起止 commit | 备注 |
|---|---:|---|---|
| Step 0 · POC + 防护栏 | 1 day | not committed | Eval CLI, summary shape, metadata boundary, restore metric feasibility |
| Step 1 · schema + pure metrics | 2 days | not committed | Report helpers and tests |
| Step 2 · CLI + report output | 2 days | not committed | Measurement command and JSON report |
| Step 3 · docs + validation + Gate 2 | 2-3 days | not committed | Docs, M8 handoff, review proof |
| **总计** | **5-8 days** | | |

## §5 · 跨模块签字规则

| 跨模块变更 | 影响下游 | D-XX 决策 | owner_signoffs | 测试覆盖 |
|---|---|---|---|---|
| Regression report schema | M8 runtime benchmark consumes M6 metrics | D-08 | project-local owner accepted by this spec | `tests/test_regression.py` |
| M5 summary aggregation | M5 sample-save output feeds M6 metrics | D-03, D-04 | project-local owner accepted by M5/M6 specs | `tests/test_sample_integration.py`, `tests/test_regression.py` |
| Gold evaluator projection | Existing eval CLI remains compatible | D-02 | project-local owner accepted by this spec | CLI/evaluation focused tests |
| Restore unresolved placeholder metric | M7 can later enrich restore timing/status | D-06, D-07 | project-local owner accepted by this spec | restore metric tests |

No external owner or live credential signoff is required for Gate 0a. Live
sample contents are not used as review material.

## §6 · 服务端权威重算

M6 consumes measurement inputs and produces decision-like report fields. The
build must apply authoritative recompute:

- D3/S3 require official workflow counts to come from M5 `sample_summary`
  payloads or local evaluator outputs, not forged browser row labels.
- D4/P5 require report sanitization before output is treated as deliverable.
- D5 requires newest-sample provenance to be computed locally from metadata and
  sample summary facts, not user-provided freshness labels.
- Tests must include at least one forged or irrelevant label proving it does
  not affect official counts.

## §7 · 文档维护扫

- [x] README expanded from placeholder to M6 spec door.
- [x] EXECUTION_PLAN includes D/P/S/N/C+A/T/E hard gates.
- [x] HUMAN_TASKS keeps external/live credentials out of M6.
- [x] step-0-poc-report includes E-1 through E-5 and fallback design.
- [x] `_progress.md` records profile, complexity, grep trace, and Gate status.
- [x] POST_GA observation plan exists because M6 is complex.
- [x] Gate 0a PASS recorded.
- [x] Gate 0b PASS recorded after POC.

## §8 · 出口 checklist

- [x] Six-file spec set drafted.
- [x] M6 report schema and decisions are explicit.
- [x] M5 handoff fields are included.
- [x] Sensitive sample boundary is a BLOCKER hard gate.
- [x] `milestone-doc-check.mjs --dir` passes before Gate 0a.
- [x] Gate 0a review passes with effective policy artifacts.
- [x] Step 0 POC E-1 through E-5 is executed and recorded.
- [x] Gate 0b review passes or records non-blocking POC findings.
- [x] `_progress.md` records next `/ffcs:build M6-regression-measurement`.
