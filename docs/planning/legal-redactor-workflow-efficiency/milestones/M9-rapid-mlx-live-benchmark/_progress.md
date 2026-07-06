# M9-rapid-mlx-live-benchmark · rapid-mlx-live-benchmark · _progress

> **Basis**: [README.md](README.md), [EXECUTION_PLAN.md](EXECUTION_PLAN.md)
> **Format**: status, Intent Guard, Gate sections, hard-gate evidence, step log, grep trace, blockers, DoD, decisions
> **Version**: v1.0 · 2026-07-06

---

## §1 · Status

```text
milestone: M9-rapid-mlx-live-benchmark
module: rapid-mlx-live-benchmark
current_stage: BLOCKED
current_step: Gate 0a mandatory reviewer auth failure
current_batch: FFCS AutoFlow worker lease lease-d4b25e66
time_box_progress: 10% / 3-5 days
recent_commit_sha: uncommitted
branch: ffcs/m9-rapid-mlx-live-benchmark
HEAD: pending
workspace: README.md, EXECUTION_PLAN.md, HUMAN_TASKS.md, step-0-poc-report.md, _progress.md
next: restore Grok review capacity or explicitly change review policy, then retry M9 Gate 0a
validation_profile: standard
effective_profile: standard
design_autonomy: auto
design_route: non-visual skipped_with_ack
```

## §2 · Intent Guard

### Q1 · Feature simplicity / abstraction depth?

M9 extends the existing M8 runtime benchmark layer rather than creating a new
runtime abstraction. The new behavior is one local live benchmark report path:
probe named OpenAI-compatible endpoints, combine the timing/model evidence with
M8/M6 quality evidence, and emit a privacy-safe recommendation.

### Q2 · Current spec scope?

Scope is live local evidence for `mlx_lm.server` versus Rapid-MLX. It includes
synthetic endpoint probes, model identity, candidate availability, optional M8
quality report input, operator docs, and no default runtime change.

### Q3 · Optional / recommended items?

Starting a managed Rapid-MLX server is recommended when the CLI can do so within
the worker. If it cannot, the report must record insufficient candidate evidence.
Any default runtime/model switch stays outside automatic M9 delivery.

## §3 · Gates

### Gate 0a · Spec review

- **Input**: README + EXECUTION_PLAN + HUMAN_TASKS + step-0-poc-report + _progress
- **Review pool**: `codex`, `grok`
- **Status**: BLOCKED · mandatory Grok lane unavailable
- **Artifacts**:
  - `.ff-state/reviews/M9-rapid-mlx-live-benchmark-gate0a/artifacts/grok-r0.json` · `status=auth_fail`, `verdict=ERROR`, `error=auth_missing`
- **Cause**: Grok CLI returned `402 Payment Required` / `403 Forbidden` for exhausted Grok Build usage or spending-limit block. FFCS policy requires `grok` in `must_collect` and `must_pass`, so Gate 0a cannot PASS.

### Gate 0b · POC release

- **Input**: [step-0-poc-report.md](step-0-poc-report.md)
- **Review pool**: `codex`, `grok`
- **Status**: pending
- **Artifacts**: pending

### Checkpoint 1 · Build self-check

- Step 1: pending
- Step 2: pending
- Step 3: pending

### Gate 2 · DoD closeout

- **Input**: implementation diff + tests + final docs + milestone-doc-check --gate2 + pre-push checklist
- **Review pool**: `codex`, `grok`
- **Status**: pending
- **Artifacts**: pending

## §4 · Hard-Gate Evidence

| Layer | Item | Status | Evidence |
|---|---|---|---|
| D | D1 Live endpoints explicit | pending | Step 1 tests |
| D | D2 M8 accuracy boundary | pending | Step 1 tests |
| D | D3 Model identity gate | POC PASS | baseline `/v1/models` contains expected model; implementation tests pending |
| D | D4 Synthetic prompts only | POC PASS | baseline synthetic chat probe works; sanitizer tests pending |
| D | D5 No default switch | pending | final diff readback |
| D | D6 Comparable context | pending | Step 1 tests |
| D | D7 Public sample boundary | POC PASS | grouped `find` returned approved public sample paths |
| D | D8 Missing Rapid-MLX fails closed | pending | Step 1/2 tests |
| P | P1 Endpoint probe pure wrapper | pending | tests |
| P | P2 Live report builder | pending | tests |
| P | P3 Privacy sanitizer extended | pending | tests |
| P | P4 Runtime command metadata | pending | tests |
| S | S1 CLI live benchmark | pending | CLI tests |
| S | S2 Live error handling | pending | CLI tests |
| S | S3 Existing M8 command preserved | pending | current M8 tests |
| S | S4 No external emission | pending | scoped grep |
| N | N1 No notification surface | pending | scoped grep |
| C+A | CA1 JSON artifact | pending | CLI tests |
| C+A | CA2 Concise CLI summary | pending | CLI tests |
| C+A | CA3 Operator docs | pending | README |
| T | T1 RED-first tests | pending | red failure output |
| T | T2 Focused tests | pending | pytest |
| T | T3 Regression compatibility | pending | pytest |
| T | T4 Full suite | pending | pytest |
| E | E1 Planning closeout | pending | this file |
| E | E2 Runtime docs | pending | README |
| E | E3 Sensitive artifact audit | pending | git audit |

## §5 · Step Log

| Step | Start commit | End commit | Scope | Event |
|---|---|---|---|---|
| Step 0 · Spec + POC | uncommitted | blocked | milestone docs/live POC | doc-check passed; Gate 0a blocked on mandatory Grok auth/credits |
| Step 1 · live schema + probe | pending | pending | code/tests | not started |
| Step 2 · CLI/docs | pending | pending | CLI/docs | not started |
| Step 3 · Gate 2 + delivery | pending | pending | review/CI/merge | not started |

## §6 · Grep Trace

### 6.1 · Existing runtime/eval authority

- **Command**: `rg -n "eval-gold|regression-report|M6-regression|/v1/models|mlx|runtime benchmark|Rapid-MLX" legal_redactor scripts tests README.md docs`
- **Time**: 2026-07-06
- **Result table**:

| # | Name | Doc classification | Authority classification | Source | Action |
|---|---|---|---|---|---|
| 1 | `M8-runtime-benchmark-report/v1` | upstream benchmark report | implemented in M8 | `legal_redactor/runtime_benchmark.py`, `tests/test_runtime_benchmark.py` | extend, do not break |
| 2 | `M6-regression-report/v1` | upstream quality report | implemented in M6 | `legal_redactor/regression.py`, `tests/test_regression.py` | consume as privacy boundary |
| 3 | `/v1/models` | runtime identity probe | startup/status hard gate | `scripts/start_mlx9b_server.sh`, `legal_redactor/status.py` | reuse as model identity evidence |
| 4 | `mlx-community/Qwen3.5-9B-MLX-4bit` | fixed current model | baseline runtime | `scripts/start_mlx9b_server.sh`, `legal_redactor/status.py` | require for comparable endpoints |
| 5 | `rapid-mlx` | candidate runtime CLI | local executable | `/Users/jannerchang/.local/bin/rapid-mlx` | probe candidate when available |
| 6 | public SPC samples | approved input fixture class | existing sample documents | `samples/01_*`, `samples/02_*`, `samples/03_*`, `samples/最高人民法院民事判决书（样本）.docx` | may use by path/category only |

## §7 · Blockers

| # | Timestamp | Type | Context | Tried | Diagnostic |
|---|---|---|---|---|---|
| 1 | 2026-07-06 | review auth | Gate 0a `grok` mandatory lane | `review-runner.mjs run-many` and direct `grok --prompt-file` retry | Grok Build usage balance exhausted / spending limit; artifact `.ff-state/reviews/M9-rapid-mlx-live-benchmark-gate0a/artifacts/grok-r0.json` is `auth_fail` |

## §8 · DoD Closeout

- [ ] Deliverables landed: M9 report/probe helpers, CLI, tests, docs.
- [ ] POC E-1 through E-4 pass or fallback is recorded.
- [ ] Hard gates have evidence in §4.
- [ ] Focused and full validation are recorded.
- [ ] Runtime docs are updated in README.
- [ ] No default runtime/model switch is included in the diff.
- [ ] Generated benchmark JSON, raw responses, samples, maps, restored text, and debug traces are not tracked as product artifacts.
- [ ] Gate 2 review passes with `codex` and `grok` artifacts plus chair signoff.
- [ ] `milestone-doc-check.mjs --gate2` passes.
- [ ] `pre-push-checklist.mjs` passes.

Post-push delivery evidence is recorded in FFCS runtime handoff and final worker
closeout, not as a progress-only second PR.

## §9 · SessionEnd Snapshot

Reserved for historical structure. Runtime handoff lives in `.ff-state/handoff/current.json`.

## §10 · Decision Log

| # | Time | Decision | Trigger | Impact |
|---|---|---|---|---|
| 1 | 2026-07-06 | Classify M9 as medium/non-visual | Runtime benchmark touches code/tests/docs but no UI | Five-file spec set, no DESIGN.md/POST_GA |
| 2 | 2026-07-06 | Keep Rapid-MLX candidate-only | User asked for live comparison, not default switch | No default runtime switch in M9 |
| 3 | 2026-07-06 | Use M8/M6 reports for accuracy | M8 already enforces privacy-safe aggregate report boundary | M9 does not read raw diagnostics |
| 4 | 2026-07-06 | Treat Rapid-MLX absence as insufficient evidence | `rapid-mlx ps` currently reports no running server | report fails closed if candidate unavailable |
