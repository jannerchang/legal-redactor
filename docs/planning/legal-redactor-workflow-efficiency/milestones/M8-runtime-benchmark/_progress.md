# M8-runtime-benchmark · runtime-benchmark · _progress

> **Basis**: [README.md](README.md), [EXECUTION_PLAN.md](EXECUTION_PLAN.md)
> **Format**: status, Intent Guard, Gate sections, hard-gate evidence, step log, grep trace, blockers, DoD, decisions
> **Version**: v1.0 · 2026-07-03

---

## §1 · Status

```text
milestone: M8-runtime-benchmark
module: runtime-benchmark
current_stage: ✅ 完成
current_step: PR/CI/merge cleanup
current_batch: FFCS AutoFlow worker lease lease-e6afe2fb
time_box_progress: 100% / 5-7 days
recent_commit_sha: uncommitted
branch: ffcs/m8-runtime-benchmark
HEAD: pending
workspace: README.md, EXECUTION_PLAN.md, HUMAN_TASKS.md, step-0-poc-report.md, _progress.md, legal_redactor/runtime_benchmark.py, legal_redactor/__main__.py, tests/test_runtime_benchmark.py
next: PR creation, CI watch, merge-decision guard, merge cleanup
validation_profile: standard
effective_profile: standard
design_autonomy: auto
design_route: non-visual skipped_with_ack
```

## §2 · Intent Guard

### Q1 · Feature simplicity / abstraction depth?

M8 adds one small benchmark/reporting layer around existing M6 reports and
runtime probes. It does not add a new runtime abstraction or default model
switch.

### Q2 · Current spec scope?

Scope is a privacy-safe runtime benchmark report and CLI. It consumes M6
reports, compares labeled candidates, optionally records synthetic endpoint
probe metadata, may use approved public Supreme People's Court documents under
`samples/` as benchmark inputs, and leaves actual runtime switching to a later
explicit product decision.

### Q3 · Optional / recommended items?

Live Rapid-MLX installation and real endpoint timing are optional. Synthetic
tests plus M6-report comparison are sufficient for M8 Gate proof. Any default
runtime switch is a human/product decision and is outside automatic merge.

## §3 · Gates

### Gate 0a · Spec review

- **Input**: README + EXECUTION_PLAN + HUMAN_TASKS + step-0-poc-report + _progress
- **Review pool**: `codex`, `grok`
- **Status**: ✅ PASS
- **Result**: r0 found HIGH issues; r1 repaired and passed. Chair signoff
  `status=ok`, `verdict=PASS`, `decision=pass_defer`.
- **Artifacts**:
  - `.ff-state/reviews/M8-runtime-benchmark-gate0a/artifacts/codex-r1.json`
  - `.ff-state/reviews/M8-runtime-benchmark-gate0a/artifacts/grok-r1.json`
  - `.ff-state/reviews/M8-runtime-benchmark-gate0a/chair-signoff.json`

### Gate 0b · POC release

- **Input**: [step-0-poc-report.md](step-0-poc-report.md)
- **Review pool**: `codex`, `grok`
- **Status**: ✅ PASS
- **Result**: E-1 through E-5 measured and accepted. Chair signoff
  `status=ok`, `verdict=PASS`, `decision=pass_defer`. Grok r0 medium
  documentation findings were repaired before chair closeout.
- **Artifacts**:
  - `.ff-state/reviews/M8-runtime-benchmark-gate0b/artifacts/codex-r0.json`
  - `.ff-state/reviews/M8-runtime-benchmark-gate0b/artifacts/grok-r0.json`
  - `.ff-state/reviews/M8-runtime-benchmark-gate0b/chair-signoff.json`

### Checkpoint 1 · Build self-check

- Step 1: ✅ PASS · `tests/test_runtime_benchmark.py` RED import failure observed, then green after `legal_redactor/runtime_benchmark.py`.
- Step 2: ✅ PASS · CLI writes M8 report and malformed input exits without traceback.
- Step 3: ✅ PASS · README docs updated; Gate 2 codex+grok PASS with chair signoff.

### Gate 2 · DoD closeout

- **Input**: implementation diff + tests + final docs + milestone-doc-check --gate2 + pre-push checklist
- **Review pool**: `codex`, `grok`
- **Status**: ✅ PASS
- **Result**: r0 grok PASS; r0 codex found 2 BLOCKER + 1 HIGH. Repair added
  workflow-regression blockers, embedded absolute-path rejection, and a
  gitignore exception for `tests/test_runtime_benchmark.py`. r1 codex PASS.
  Chair signoff `status=ok`, `verdict=PASS`, `decision=pass_defer`.
- **Artifacts**:
  - `.ff-state/reviews/M8-runtime-benchmark-gate2/artifacts/codex-r1.json`
  - `.ff-state/reviews/M8-runtime-benchmark-gate2/artifacts/grok-r0.json`
  - `.ff-state/reviews/M8-runtime-benchmark-gate2/chair-signoff.json`

## §4 · Hard-Gate Evidence

| Layer | Item | Status | Evidence |
|---|---|---|---|
| D | D1 M6 contract validated | ✅ PASS | `tests/test_runtime_benchmark.py::test_privacy_boundary_rejects_raw_diagnostics_but_allows_m6_omitted_flags`; focused `16 passed` |
| D | D2 Privacy boundary preserved | ✅ PASS | M8 sanitizer rejects raw `matched`, raw `sample_entries`, and embedded absolute paths; report privacy flags stay `omitted` |
| D | D3 Candidate context compatible | ✅ PASS | `test_context_mismatch_blocks_winner_selection` |
| D | D4 No default runtime switch | ✅ PASS | `git diff -- scripts/start_mlx9b_server.sh legal_redactor/config.py` empty; grep confirms `--llm` default `max-effect` and fixed MLX model unchanged |
| D | D5 Synthetic probe only | ✅ PASS | `test_models_probe_summary_uses_identity_metadata_without_prompt_or_body`; no live/legal text probe required |
| D | D6 Pure-rule fallback benchmarkable | ✅ PASS | `rules-only` candidate accepted by report schema test |
| D | D7 Public sample inputs bounded | ✅ PASS | worker directive consumed; README documents public SPC sample use by manifest/hash/category only |
| D | D8 Required metrics explicit | ✅ PASS | missing first-token/Web/memory/error-rate evidence emits nullable reason fields and blocks auto-switch; workflow regressions block runtime-switch recommendations |
| P | P1 Report loader pure | ✅ PASS | `BenchmarkCandidateInput` + M6 validation in `legal_redactor/runtime_benchmark.py` |
| P | P2 Delta calculator pure | ✅ PASS | deterministic quality/workflow/timing/resource/error deltas in tests |
| P | P3 Privacy sanitizer reused | ✅ PASS | M6 `assert_privacy_safe_report` plus M8 output sanitizer |
| P | P4 Probe summarizer pure | ✅ PASS | `/v1/models` payload summarizer emits model_match/status/count only |
| S | S1 CLI report command | ✅ PASS | CLI test exits 0 and writes `M8-runtime-benchmark-report/v1` |
| S | S2 Malformed input handling | ✅ PASS | CLI bad JSON exits 1 with `[基准报告错误]` and no traceback/partial file |
| S | S3 Model identity gate | ✅ PASS | ready/wrong model payload tests |
| S | S4 No external emission | ✅ PASS | `rg -n "Discord|Hermes|webhook|telegram|requests|http\\.client|urllib|notify" legal_redactor/runtime_benchmark.py legal_redactor/__main__.py` exit 1 |
| N | N1 No notification surface | ✅ PASS | same scoped grep exit 1; report path is local JSON only |
| C+A | CA1 JSON artifact | ✅ PASS | CLI test verifies schema, benchmark_context, candidates, comparison, privacy, recommendation |
| C+A | CA2 Concise CLI summary | ✅ PASS | CLI stdout prints labels/recommendation/deltas, not full JSON |
| C+A | CA3 Operator docs | ✅ PASS | README M8 section added with command examples and no-default-switch caveat |
| T | T1 Unit tests | ✅ PASS | `.venv/bin/python -m pytest tests/test_runtime_benchmark.py -q -p no:cacheprovider` → `19 passed` |
| T | T2 CLI tests | ✅ PASS | included in `tests/test_runtime_benchmark.py` |
| T | T3 Regression compatibility | ✅ PASS | `.venv/bin/python -m pytest tests/test_runtime_benchmark.py tests/test_regression.py -q -p no:cacheprovider` → `29 passed` |
| T | T4 Full suite | ✅ PASS | `.venv/bin/python -m pytest -q -p no:cacheprovider` → `307 passed in 94.42s` |
| E | E1 Planning closeout | ✅ PASS | this file; Gate 2 PASS and DoD closed before first PR push |
| E | E2 Runtime docs | ✅ PASS | README M8 runtime benchmark section |
| E | E3 Sensitive artifact audit | ✅ PASS | no generated reports/maps/restored text/debug traces tracked; `.DS_Store` ignored from delivery commit; `tests/test_runtime_benchmark.py` visible to git |

## §5 · Step Log

| Step | Start commit | End commit | Scope | Event |
|---|---|---|---|---|
| Step 0 · Spec + POC | uncommitted | pending | milestone docs | Gate 0a PASS; Gate 0b PASS; next `/ffcs:build M8-runtime-benchmark` |
| Step 1 · schema + pure compare | uncommitted | pending | code/tests | RED: `ModuleNotFoundError`; GREEN: `tests/test_runtime_benchmark.py` 6 passed |
| Step 2 · CLI + report output | uncommitted | pending | CLI/tests | CLI success/error tests included in `tests/test_runtime_benchmark.py`; focused 16 passed with `tests/test_regression.py` |
| Step 3 · docs + Gate 2 + PR | uncommitted | pending | docs/review/CI | Gate 2 PASS; PR/CI/merge pending |

## §6 · Grep Trace

### 6.1 · Existing runtime/eval authority

- **Command**: `rg -n "eval-gold|regression-report|M6-regression|/v1/models|mlx" legal_redactor scripts tests README.md`
- **Time**: 2026-07-03
- **Result table**:

| # | Name | Doc classification | Authority classification | Source | Action |
|---|---|---|---|---|---|
| 1 | `M6-regression-report/v1` | upstream report schema | implemented in M6 | `legal_redactor/regression.py`, `tests/test_regression.py` | preserve and validate |
| 2 | `/v1/models` | runtime identity probe | startup/status hard gate | `scripts/start_mlx9b_server.sh`, `tests/test_status.py` | reuse as metadata |
| 3 | `mlx-community/Qwen3.5-9B-MLX-4bit` | fixed local model | runtime default | `scripts/start_mlx9b_server.sh`, `README.md` | do not change |
| 4 | `--llm off` | pure-rule fallback | CLI mode | `legal_redactor/__main__.py`, `README.md` | keep benchmarkable |
| 5 | public SPC samples | approved input fixture class | existing sample documents | `samples/01_*`, `samples/02_*`, `samples/03_*`, `samples/最高人民法院民事判决书（样本）.docx` | may use by path/category only |

## §7 · Blockers

| # | Timestamp | Type | Context | Tried | Diagnostic |
|---|---|---|---|---|---|
| none | 2026-07-03 | none | no blocker at spec start | lease validated | not applicable |

## §8 · DoD Closeout

- [x] Deliverables landed: runtime benchmark module, CLI, tests, docs.
- [x] POC E-1 through E-5 pass or fallback is recorded.
- [x] Hard gates have evidence in §4.
- [x] Full pytest passes after final closeout: `307 passed in 94.42s`.
- [x] Runtime docs are updated in README.
- [x] No default runtime/model switch is included in the diff.
- [x] Generated benchmark JSON, M6 reports, sample entries, mappings, restored text, and debug traces are not tracked as product artifacts.
- [x] Gate 2 review passes with `codex` and `grok` artifacts plus chair signoff.
- [x] `milestone-doc-check.mjs --gate2` passes.
- [x] `pre-push-checklist.mjs` passes with severity `pass`.

Post-push delivery evidence is intentionally recorded in FFCS runtime handoff
and final worker closeout, not as a progress-only second PR: PR checks, merge
guard artifact, main CI watch, and branch cleanup.

## §9 · SessionEnd Snapshot

Reserved for historical structure. Runtime handoff lives in `.ff-state/handoff/current.json`.

## §10 · Decision Log

| # | Time | Decision | Trigger | Impact |
|---|---|---|---|---|
| 1 | 2026-07-03 | Classify M8 as medium/non-visual | Runtime benchmark touches code/tests/docs but no UI | Five-file spec set, no DESIGN.md/POST_GA |
| 2 | 2026-07-03 | Keep Rapid-MLX candidate-only | User asked efficiency question; prior assessment routed to M8 | No default runtime switch in M8 |
| 3 | 2026-07-03 | Allow public SPC samples as inputs | queued user directive | Benchmark inputs may use existing public `samples/` documents while reports remain privacy-safe |
| 4 | 2026-07-03 | Add benchmark context compatibility | Gate 0a r0 codex HIGH-1 | M8 report requires matching `benchmark_context`; mismatches block winner selection |
| 5 | 2026-07-03 | Make metrics nullable-with-reason | Gate 0a r0 codex HIGH-2 | First-token, total duration, Web timing, memory, and error-rate fields must exist or explain absence |
