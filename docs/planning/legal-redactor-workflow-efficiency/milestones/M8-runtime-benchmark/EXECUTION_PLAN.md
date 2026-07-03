# M8-runtime-benchmark · runtime-benchmark · execution plan

> **Basis**: [README.md](README.md), [../../REQUIREMENTS.md](../../REQUIREMENTS.md), [../M6-regression-measurement/README.md](../M6-regression-measurement/README.md)
> **Schema reference**: `/Users/jannerchang/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.1.14/templates/gate.schema.md`
> **Update rhythm**: synchronize this file and [_progress.md](_progress.md) at each step/gate
> **Version**: v1.0 · 2026-07-03

---

## §1 · Hard Gates

| id | title | description | evidence_required | pass_condition | block_severity | typical_count |
|---|---|---|---|---|---|---:|
| D1 | M6 contract validated | Accept only `M6-regression-report/v1` input with required aggregate quality, workflow, sample, restore, timing, and privacy fields. | unit_test_count, integration_test_count | Missing schema/required fields return deterministic errors; valid synthetic M6 reports load. | BLOCKER | 1 |
| D2 | Privacy boundary preserved | M8 reports must not include raw eval diagnostics, sample entries, mapping values, restored text, absolute paths, tokens, or debug traces. | unit_test_count, grep_stdout | Tests reject raw keys and sensitive free-text values; generated reports contain only labels/counts/deltas. | BLOCKER | 1 |
| D3 | Candidate context compatible | Compare runtime candidates by explicit labels only when `benchmark_context` matches on gold set, input set, and benchmark profile. | unit_test_count | Mismatched contexts set `comparison.compatible=false`, block winner selection, and return `recommendation.action=manual_review`. | BLOCKER | 1 |
| D4 | No default runtime switch | Build must not change `scripts/start_mlx9b_server.sh` defaults, the fixed model, or CLI `--llm` default. | grep_stdout, diff_readback | Diff/readback proves runtime defaults remain unchanged. | BLOCKER | 1 |
| D5 | Synthetic probe only | Optional endpoint probes use synthetic prompt text and `/v1/models` identity checks only. | unit_test_count, integration_test_count | Probe tests never require legal document text, samples, maps, restored text, or cloud credentials. | BLOCKER | 1 |
| D6 | Pure-rule fallback benchmarkable | `--llm off` / pure-rule comparison stays representable as a candidate run. | unit_test_count, doc_anchor | Report schema supports candidate labels such as `rules-only` without endpoint evidence. | HIGH | 1 |
| D7 | Public sample inputs bounded | Existing public Supreme People's Court documents under `samples/` may be used as benchmark inputs, while generated reports stay privacy-safe. | unit_test_count, grep_stdout | Benchmark tests/docs reference approved sample paths or synthetic fixtures; report JSON omits raw text/diagnostics. | HIGH | 1 |
| D8 | Required metrics explicit | First-token latency, total redaction/eval duration, Web timing, peak memory, and error rate must be present or carry nullable reason fields. | unit_test_count, integration_test_count | Missing metric evidence blocks auto-switch recommendations; tests cover null+reason behavior. | HIGH | 1 |
| P1 | Report loader pure | Add pure loader/validator helpers for M6 reports. | unit_test_count | Loader returns sanitized runtime input or raises clear `ValueError`. | BLOCKER | 1 |
| P2 | Delta calculator pure | Add pure comparison helpers for quality, timing, workflow, restore, memory, and error-rate deltas. | unit_test_count | Delta output is deterministic, numeric fields are nullable with reason fields where evidence is absent. | BLOCKER | 1 |
| P3 | Privacy sanitizer reused | Reuse or mirror M6 privacy sanitizer for M8 output. | unit_test_count | Unsafe raw keys or sensitive Chinese free text are rejected before JSON write. | BLOCKER | 1 |
| P4 | Probe summarizer pure | Convert optional endpoint/model probe observations into safe metadata. | unit_test_count | Probe summary includes endpoint label, model id match, timing, status, and no prompt/output body. | HIGH | 1 |
| S1 | CLI report command | Provide a local benchmark report command that writes JSON and prints a concise summary. | integration_test_count | Synthetic CLI invocation exits 0, writes JSON, and prints candidate labels/deltas. | BLOCKER | 1 |
| S2 | Malformed input handling | Invalid JSON, missing fields, schema mismatch, or unsafe values fail without traceback. | integration_test_count | CLI exits non-zero with deterministic error and no partial benchmark file. | HIGH | 1 |
| S3 | Model identity gate | Endpoint probe must distinguish ready expected model from wrong-service listener. | unit_test_count | Tests cover ready/missing/wrong-model payloads without network dependence. | HIGH | 1 |
| S4 | No external emission | Benchmark command stays local and does not call Discord/Hermes/webhooks. | grep_stdout | Runtime benchmark module and CLI path contain no remote notification calls. | BLOCKER | 1 |
| N1 | No notification surface | M8 has no notification/webhook delivery. | grep_stdout | Code path is local file/HTTP probe only; no Hermes/Discord transport import. | BLOCKER | 1 |
| CA1 | JSON artifact | Persist a machine-readable benchmark report for later product decision. | integration_test_count | JSON includes schema, benchmark_context, candidates, comparison, privacy, and recommendation sections. | BLOCKER | 1 |
| CA2 | Concise CLI summary | Print human-readable deltas without dumping raw reports. | integration_test_count | Stdout includes labels and key metric deltas, not full JSON or raw legal text. | MEDIUM | 1 |
| CA3 | Operator docs | README documents reproducible benchmark commands and default-switch caveat. | doc_anchor | Docs include commands and explicit "no default runtime switch from M8 alone" note. | MEDIUM | 1 |
| T1 | Unit tests | Add focused runtime benchmark helper tests. | unit_test_count | `.venv/bin/python -m pytest tests/test_runtime_benchmark.py` passes. | BLOCKER | 1 |
| T2 | CLI tests | Cover benchmark report CLI success/error paths. | integration_test_count | CLI tests pass using synthetic files only. | BLOCKER | 1 |
| T3 | Regression compatibility | Keep M6 regression tests passing. | unit_test_count | `.venv/bin/python -m pytest tests/test_regression.py` passes. | BLOCKER | 1 |
| T4 | Full suite | Run full pytest before Gate 2 unless blocked by environment. | unit_test_count | Full suite passes or environment failure is classified with focused passing evidence. | HIGH | 1 |
| E1 | Planning closeout | `_progress.md` records Gate artifacts, Step evidence, and DoD closeout. | doc_anchor | Status moves to complete before first PR push. | BLOCKER | 1 |
| E2 | Runtime docs | README records benchmark workflow and preserves startup/default notes. | doc_anchor | Operator can reproduce A/B comparison from docs. | MEDIUM | 1 |
| E3 | Sensitive artifact audit | Generated reports, samples, maps, restored text, and debug traces are not tracked. | grep_stdout | `git status` / `git ls-files` audit confirms no sensitive artifacts are added. | BLOCKER | 1 |

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
| M8.D-01 | Benchmark before runtime switch | Build, docs, merge decision | README D-01 | locked |
| M8.D-02 | Consume only M6 safe reports | Loader, schema, privacy tests | README D-02 | locked |
| M8.D-03 | Compare explicit candidate labels | Report schema, CLI UX | README D-03 | locked |
| M8.D-04 | Synthetic first-token probe only | Probe helper and tests | README D-04 | locked |
| M8.D-05 | Keep MLX model identity gate | Probe/startup boundary | README D-05 | locked |
| M8.D-06 | Preserve pure-rule fallback | Report schema and docs | README D-06 | locked |
| M8.D-07 | Local JSON report is authoritative | M8 output and later decision | README D-07 | locked |
| M8.D-08 | Allow public SPC samples as inputs | Benchmark fixture/input boundary | README D-08 | locked |
| M8.D-09 | Context mismatch blocks recommendations | Candidate comparison and recommendation | README D-09 | locked |

### §2 Appendix · Decision Details

| # | rationale | signoff_version | evidence_link |
|---|---|---|
| M8.D-01 | Runtime speed alone is insufficient for legal redaction; quality, workflow, and restore metrics must be compared before changing defaults. | v1.0 | [README.md](README.md) §4 |
| M8.D-02 | M6 already strips raw diagnostics; M8 must not reopen sensitive inputs. | v1.0 | [../M6-regression-measurement/README.md](../M6-regression-measurement/README.md) |
| M8.D-03 | Explicit labels make baseline/candidate comparisons reproducible and avoid hidden global runtime state. | v1.0 | [README.md](README.md) §4 |
| M8.D-04 | Endpoint latency can be probed with synthetic text; legal documents and samples are unnecessary and unsafe. | v1.0 | [README.md](README.md) §6 |
| M8.D-05 | Existing startup guard prevents benchmarking the wrong listener on `18080`. | v1.0 | `scripts/start_mlx9b_server.sh` |
| M8.D-06 | The emergency/cheap operation path must remain measurable and available. | v1.0 | `legal_redactor/__main__.py` |
| M8.D-07 | Local JSON is enough for PR/Gate proof and later product decision. | v1.0 | [README.md](README.md) §3.3 |
| M8.D-08 | The user explicitly approved existing public Supreme People's Court documents under `samples/` for M8 benchmark/test input use, while preserving report privacy boundaries. | v1.0 | user directive 2026-07-03 |
| M8.D-09 | Without shared context, a faster candidate could be compared against a different gold set or document set; M8 must fail closed and require manual review. | v1.0 | Gate 0a r0 codex HIGH-1 |

## §3 · Step Sequence

### Step 0 · POC + guardrails

**Time box**: `0.5-1 day`

1. Run `milestone-doc-check.mjs --dir` before Gate 0a.
2. POC E-1: validate a synthetic M6 report with required fields and privacy flag.
3. POC E-2: validate benchmark delta shape using two synthetic M6 reports, including a context mismatch case.
4. POC E-3: confirm current MLX identity probe behavior can be represented as safe metadata.
5. POC E-4: confirm no default runtime/model switch is required for benchmark reporting.
6. POC E-5: confirm existing public SPC sample paths can be referenced as approved benchmark inputs without emitting raw text in reports.
7. Update `step-0-poc-report.md`, then run Gate 0b review.

### Step 1 · schema + pure comparison

**Time box**: `1-2 days`

- Add `legal_redactor/runtime_benchmark.py`.
- Write failing tests first for report loading, privacy rejection, context compatibility, candidate delta, nullable metric reasons, and recommendation status.
- Implement minimal helpers to make those tests pass.

**Checkpoint 1**:

- `tests/test_runtime_benchmark.py` covers pure helpers and privacy sanitizer.

### Step 2 · CLI + optional probe metadata

**Time box**: `1-2 days`

- Add CLI flags for benchmark report generation.
- Support multiple candidate inputs as explicit `label=path` pairs.
- Require or derive a shared `benchmark_context` for each candidate; reject or
  manual-review mismatches instead of selecting a winner.
- Print compact deltas and write JSON output.
- Add deterministic errors for malformed labels, missing files, unsafe reports, or schema mismatch.
- Permit approved public SPC sample paths as optional benchmark input metadata,
  without copying document text into the M8 report.

**Checkpoint 2**:

- CLI tests pass using synthetic reports and no network dependency.

### Step 3 · docs + validation + Gate 2

**Time box**: `1-2 days`

- Update README with reproducible M6 + M8 commands.
- Run focused tests:

```bash
.venv/bin/python -m pytest tests/test_runtime_benchmark.py tests/test_regression.py -q -p no:cacheprovider
```

- Run full pytest before Gate 2. If the environment blocks full-suite temp/capture behavior, rerun with `-s` and record the environment classification.
- Run `milestone-doc-check.mjs --gate2`, `pre-push-checklist.mjs`, Gate 2 review, then GitHub PR/CI.

## §4 · Time Box

| Step | Estimate | Commit window | Notes |
|---|---:|---|---|
| Step 0 · POC + guardrails | 0.5-1 day | uncommitted | M6 contract, delta shape, probe metadata |
| Step 1 · schema + pure comparison | 1-2 days | uncommitted | Runtime benchmark helpers |
| Step 2 · CLI + report output | 1-2 days | uncommitted | Local command and errors |
| Step 3 · docs + validation + Gate 2 | 1-2 days | uncommitted | Docs, review, PR/CI |
| **Total** | **5-7 days** | | Medium complexity |

## §5 · Cross-Module Signoff

| Change | Downstream impact | Decision | owner_signoffs | Test coverage |
|---|---|---|---|---|
| M8 benchmark report schema | Later runtime/default decision consumes M8 report | M8.D-01, M8.D-07 | project-local owner accepted by this spec | `tests/test_runtime_benchmark.py` |
| M6 report loader | M8 depends on M6 privacy-safe JSON | M8.D-02 | project-local owner accepted by M6/M8 specs | `tests/test_runtime_benchmark.py`, `tests/test_regression.py` |
| CLI benchmark command | Operator workflow | M8.D-03, M8.D-06 | project-local owner accepted by this spec | CLI tests |

No external credential, remote host, or live runtime owner signoff is required
for Gate 0a. Live endpoint benchmarking may be run locally when available, but
synthetic tests are the required Gate evidence.

## §6 · Server-Authoritative Recompute

M8 contains decision-like comparison fields (`recommendation`, `winner`,
`quality_regression`, `runtime_improvement`). These fields must be recomputed
from loaded M6 reports and optional probe metadata:

- D3/P2/S1 require candidate deltas to be calculated locally from report facts,
  not accepted from user-provided labels.
- D3/D8 require `recommendation` to fail closed when `benchmark_context`
  differs or required metric evidence is missing.
- D2/P3 require privacy validation before a report can contribute to a
  recommendation.
- D5/S3 require model identity to be computed from `/v1/models` metadata or
  test fixtures, not from a caller-supplied readiness label.

## §7 · Documentation Sweep

- [x] README includes benchmark command examples.
- [x] M8 `_progress.md` records Gate 0a/0b/2 artifacts and DoD evidence.
- [x] HUMAN_TASKS contains only external/manual work, if any.
- [x] Step 0 POC report records PASS/fallback evidence.
- [x] Generated benchmark JSON stays outside tracked artifacts unless explicitly sanitized fixture data is needed for tests.
- [x] No `DESIGN.md` is required because this is non-visual runtime work.

## §8 · Exit Checklist

- [x] Five-file spec set is complete.
- [x] POC E-1 through E-5 pass or fallback is recorded.
- [x] D/P/S/N/C+A/T/E gates have evidence.
- [x] `milestone-doc-check.mjs --gate2` passes.
- [x] `pre-push-checklist.mjs` passes or records only allowed warnings.
- [x] Gate 2 review passes with required artifacts.
- [x] `_progress.md` §1 is `✅ 完成`; §3 Gate 2 and §8 DoD are closed before first PR push.
- [ ] PR checks are green.
- [ ] Merge guard artifact allows `auto_squash_merge` before any merge.
