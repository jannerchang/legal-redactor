# M6-regression-measurement · regression-measurement · _progress

> **依据**:[README.md](README.md) + [EXECUTION_PLAN.md](EXECUTION_PLAN.md)
> **格式**:状态速览 + Intent Guard + Gate 节 + 硬门槛证据 + Step 日志 + grep 留痕 + 断路记录 + DoD 闭环 + 决策日志
> **更新节奏**:每 Step / Gate / 断路事件实时更新
> **版本**:v1.0 · 2026-06-29

---

## §1 · 状态速览

```text
milestone: M6-regression-measurement
module: regression-measurement
当前阶段: ✅ Build complete
当前 Step: Gate 2 PASS + closeout
当前批次: /ffcs:build M6-regression-measurement
complexity: complex
risk: medium
validation_profile: standard
effective_profile: standard
profile_source: default
时间盒进度: build completed in current Codex run
最近 commit SHA: 6dc17b6
分支: main
HEAD: 6dc17b6
工作区: existing M3/M4/M5 changes remain dirty; M6 build changes are layered on top and not committed
待办: next `/ffcs:spec M7-discord-hermes-restore-status`
```

## §2 · Intent Guard

### Q1 · feature 简洁度 / 抽象层数?

**答**:M6 should add a small measurement/reporting layer around the existing
gold evaluator, M5 sample-summary payloads, sample metadata, and restore preview
helpers. It should not rewrite the recognition engine, create a new Web app, or
change the default MLX model.

### Q2 · 当前 spec 目标 scope?

**答**:Scope is regression measurement: report schema, gold-set quality metrics,
workflow correction metrics, newest-sample provenance checks, restore
placeholder metric, local timing fields, privacy-safe JSON output, and M8
handoff. It does not tune rules, change prompts, run runtime benchmarks, or
implement Discord/Hermes restore status.

### Q3 · "可选 / 推荐项" 分类?

**答**:Exact CLI flag names and report file naming are reversible build details.
Hard gates are stable schema, gold metrics preservation, M5 summary aggregation,
sample privacy, newest-sample gate, restore unresolved placeholder semantics,
threshold exits, no external notification, and model default preservation.

## §3 · Gate 节

### Gate 0a · 规划文档评审

- **评审输入**:README + EXECUTION_PLAN + HUMAN_TASKS + step-0-poc-report + _progress + POST_GA_OBSERVATION + milestone-doc-check output
- **评审池**:`codex,grok`
- **状态**:✅ PASS
- **validation_profile**:`standard`
- **effective_profile**:`standard`
- **profile_source**:`default`
- **结构机检**:PASS · r0 `.ff-state/logs/M6-spec-milestone-doc-check-gate0a-2026-06-29-145708.log` and r1 `.ff-state/logs/M6-spec-milestone-doc-check-gate0a-r1-2026-06-29-150749.log` · `files_scanned=6 · findings=0`
- **artifacts**:
  - `.ff-state/reviews/M6-regression-measurement-gate0a/artifacts/codex-r0.json` · `status=ok · verdict=FAIL · BLOCKER=1 · HIGH=1`
  - `.ff-state/reviews/M6-regression-measurement-gate0a/artifacts/grok-r0.json` · `status=ok · verdict=PASS`
  - `.ff-state/reviews/M6-regression-measurement-gate0a/artifacts/codex-r1.json` · `status=ok · verdict=PASS`
  - `.ff-state/reviews/M6-regression-measurement-gate0a/artifacts/grok-r1.json` · `status=ok · verdict=PASS`
  - `.ff-state/reviews/M6-regression-measurement-gate0a/chair-signoff.json` · `status=ok · verdict=PASS · decision=pass_defer`
- **结果**:PASS · `all_pass=true · peer_all_pass=true · failed=[]`

### Gate 0b · POC 放行

- **评审输入**:[step-0-poc-report.md](step-0-poc-report.md) E-1 through E-5 results
- **评审池**:`codex,grok`
- **状态**:✅ PASS
- **POC 结果**:E-1 修订非阻塞; E-2 非阻塞; E-3 非阻塞; E-4 修订非阻塞; E-5 非阻塞; Defense PASS
- **artifacts**:
  - `.ff-state/reviews/M6-regression-measurement-gate0b/artifacts/codex-r0.json` · `status=ok · verdict=PASS`
  - `.ff-state/reviews/M6-regression-measurement-gate0b/artifacts/grok-r0.json` · `status=ok · verdict=PASS`
  - `.ff-state/reviews/M6-regression-measurement-gate0b/chair-signoff.json` · `status=ok · verdict=PASS · decision=pass_defer`
- **结果**:PASS · `all_pass=true · peer_all_pass=true · failed=[]`

### Gate 2 · DoD 闭环

- **评审输入**:implementation diff, focused/full tests, report artifact behavior, privacy audit, docs closeout
- **评审池**:`codex,grok`
- **状态**:✅ PASS
- **结构机检**:PASS · `.ff-state/logs/M6-build-milestone-doc-check-gate2-r1-repair-2026-06-29.log` · `files_scanned=6 · findings=0`
- **artifacts**:
  - `.ff-state/reviews/M6-regression-measurement-gate2/artifacts/codex-r0.json` · `status=ok · verdict=FAIL · BLOCKER=1 · HIGH=1`
  - `.ff-state/reviews/M6-regression-measurement-gate2/artifacts/grok-r0.json` · `status=ok · verdict=FAIL · BLOCKER=0 · HIGH=1`
  - `.ff-state/reviews/M6-regression-measurement-gate2/artifacts/codex-r1.json` · `status=ok · verdict=PASS · BLOCKER=0 · HIGH=0`
  - `.ff-state/reviews/M6-regression-measurement-gate2/artifacts/grok-r1.json` · `status=ok · verdict=PASS · BLOCKER=0 · HIGH=0`
  - `.ff-state/reviews/M6-regression-measurement-gate2/chair-signoff.json` · `status=ok · verdict=PASS · decision=pass_defer`
- **结果**:PASS · `all_pass=true · peer_all_pass=true · failed=[]`

## §4 · 硬门槛证据追踪

| 层 | 条目 | 状态 | 证据 |
|---|---|---|---|
| D | D1-D9 report/data contracts | ✅ | `legal_redactor/regression.py`, `legal_redactor/__main__.py`, `tests/test_regression.py`; model audit log `.ff-state/logs/M6-build-model-default-audit-2026-06-29.log` |
| P | P1-P6 pure helpers | ✅ | `tests/test_regression.py` 10 focused cases; r1 focused log `.ff-state/logs/M6-build-focused-regression-r1-repair-2026-06-29.log` |
| S | S1-S4 CLI/report service behavior | ✅ | CLI subprocess test in `tests/test_regression.py`; threshold pass/fail covered |
| N | N1 no external notification | ✅ | M6 implementation is local file/CLI only; no Discord/Hermes/MCP calls in `legal_redactor/regression.py` |
| C+A | CA1-CA3 CLI/JSON/docs | ✅ | README M6 command docs; M8 input contract updated; JSON report schema tested |
| T | T1-T6 tests/audit | ✅ | focused suite `58 passed`; full suite `180 passed, 11 subtests passed`; ruff PASS; sensitive audit PASS |
| E | E1-E4 docs/handoff/POST_GA | ✅ | README/M8/M6 docs updated; POST_GA plan present; Gate 2 doc-check `findings=0` |

## §5 · Step 执行日志

| Step | 起 commit | 止 commit | 交付规模 | 关键事件 |
|---|---|---|---|---|
| Spec draft | 6dc17b6 | not committed | M6 spec docs | Expanded M6 from placeholder README to complex six-file spec set |
| Gate 0a r0 repair | 6dc17b6 | not committed | M6 spec docs | Repaired codex-r0 BLOCKER/HIGH: sanitized M6 gold projection and saved-case timing field/POC |
| Gate 0a r1 signoff | 6dc17b6 | not committed | M6 spec docs + review artifacts | codex-r1 PASS, grok-r1 PASS, chair PASS, final doc-check findings=0 |
| Step 0 POC | 6dc17b6 | not committed | POC logs + report doc | E-1 through E-5 executed with synthetic inputs/metadata-only sample checks; no blocking findings |
| Gate 0b signoff | 6dc17b6 | not committed | POC report + review artifacts | codex-r0 PASS, grok-r0 PASS, chair PASS; spec can proceed to build |
| Build clean baseline | 6dc17b6 | not committed | no product edits | `.venv/bin/python -m pytest` PASS · `170 passed, 11 subtests passed in 80.41s` · log `.ff-state/logs/M6-build-clean-baseline-2026-06-29.log` |
| Step 1 RED tests | 6dc17b6 | not committed | `tests/test_regression.py` | RED witnessed: `.venv/bin/python -m pytest tests/test_regression.py` exit 2 · missing `legal_redactor.regression` module · log `.ff-state/logs/M6-build-red-tests-2026-06-29.log` |
| Step 1/2 implementation | 6dc17b6 | not committed | `legal_redactor/regression.py`, `legal_redactor/__main__.py`, `tests/test_regression.py` | Focused M6 report/CLI tests PASS · `7 passed in 3.64s` · log `.ff-state/logs/M6-build-focused-regression-2026-06-29.log` |
| Step 3 validation/docs | 6dc17b6 | not committed | README/M8/M6 docs + validation | Focused suite PASS · `55 passed in 60.04s`; full pytest PASS · `177 passed, 11 subtests passed in 84.25s`; ruff PASS; sensitive audit PASS; Gate 2 doc-check PASS |
| Gate 2 r0 review | 6dc17b6 | not committed | `codex,grok` artifacts | codex-r0 FAIL `BLOCKER=1 HIGH=1`; grok-r0 FAIL `BLOCKER=0 HIGH=1`; artifacts under `.ff-state/reviews/M6-regression-measurement-gate2/artifacts/` |
| Gate 2 r0 repair | 6dc17b6 | not committed | `legal_redactor/regression.py`, `legal_redactor/__main__.py`, `tests/test_regression.py` | Removed per-case name leakage via `case_id`, added no-traceback malformed input handling, moved report timing to include report assembly, added sensitive-value sanitizer coverage; focused M6 PASS `10 passed`, focused suite PASS `58 passed`, full pytest PASS `180 passed, 11 subtests passed`, ruff/audit/doc-check PASS |
| Gate 2 r1 signoff | 6dc17b6 | not committed | review artifacts + closeout | codex-r1 PASS, grok-r1 PASS, chair PASS `pass_defer`; proof `all_pass=true · peer_all_pass=true · failed=[]` |

## §6 · grep 留痕

### 6.1 · Requirements and split anchors

- **命令**:`rg -n "regression|gold-set|precision|recall|F1|manual corrections|false-positive deletes|missing entity adds|restore unresolved|newest sample|sample provenance|workflow metrics|runtime benchmark|sensitive sample" docs/planning/legal-redactor-workflow-efficiency/REQUIREMENTS.md docs/planning/legal-redactor-workflow-efficiency/SPLIT.md docs/planning/legal-redactor-workflow-efficiency/milestones/M6-regression-measurement/README.md`
- **实测时间**:2026-06-29 CST

| # | 名称 | 文档分类 | 权威分类 | 权威源行号 | 动作 |
|---|---|---|---|---|---|
| 1 | optimizer starts from newest samples | requirement | workflow ordering | `REQUIREMENTS.md:83-84` | Build D5/P3/T3 |
| 2 | hybrid architecture remains explicit | requirement | architecture boundary | `REQUIREMENTS.md:104-107`, `REQUIREMENTS.md:224-227` | Build docs and avoid model/runtime changes |
| 3 | recognition metrics | requirement | gold-set metrics | `REQUIREMENTS.md:213-215` | Build D2/P1/S1/T2 |
| 4 | workflow metrics | requirement | correction/restore/timing metrics | `REQUIREMENTS.md:216-222` | Build D3/D6/D7/P2/P4 |
| 5 | newest sample provenance before tuning | requirement | sample safety gate | `REQUIREMENTS.md:223` | Build D5/P3 |
| 6 | focused rule changes only after evidence | requirement | no broad prompt/rule churn | `REQUIREMENTS.md:228-229` | Keep tuning out of M6 until report exists |
| 7 | M6 blocks M8 | downstream | runtime benchmark dependency | `SPLIT.md:33`, `SPLIT.md:75-80` | Build D8/E2 |
| 8 | sensitive samples remain local | signoff | privacy boundary | `REQUIREMENTS.md:68`, `SPLIT.md:88-89` | Build D4/T6 |

### 6.2 · Current eval/report paths

- **命令**:`nl -ba legal_redactor/__main__.py | sed -n '90,260p'` and `nl -ba legal_redactor/evaluation.py | sed -n '1,140p'`
- **实测时间**:2026-06-29 CST

| # | 名称 | 文档分类 | 权威分类 | 权威源行号 | 动作 |
|---|---|---|---|---|---|
| 1 | `--eval-gold` CLI | CLI | existing gold-set input | `__main__.py:93-104` | Preserve D2/S1 |
| 2 | threshold flags | CLI | current fail-under behavior | `__main__.py:106-115`, `__main__.py:250-253` | Preserve/extend D8 |
| 3 | eval report write | CLI | JSON artifact | `__main__.py:245-249` | Reuse for M6 JSON output |
| 4 | `evaluate_gold_file` totals | helper | precision/recall/F1 source | `evaluation.py:29-63` | Build P1 |
| 5 | per-case missing/extra | helper | diagnosis fields | `evaluation.py:81-94` | Preserve existing eval compatibility, but sanitize M6 default report to counts only |

### 6.3 · M5 summary and sample helpers

- **命令**:`nl -ba legal_redactor/_samples.py | sed -n '245,345p'` and `nl -ba legal_redactor/web_app.py | sed -n '1220,1310p'`
- **实测时间**:2026-06-29 CST

| # | 名称 | 文档分类 | 权威分类 | 权威源行号 | 动作 |
|---|---|---|---|---|---|
| 1 | recent error sample metadata | helper | newest-sample ordering | `_samples.py:245-277` | Build P3 with sanitized output |
| 2 | sample lookup/blacklist loader | helper | sample behavior source | `_samples.py:280-310` | Do not parse raw entries for report output |
| 3 | trusted mappings | helper | sample reuse source | `_samples.py:313-345` | Preserve safety guards |
| 4 | M5 empty summary keys | helper | sample_summary schema | `web_app.py:1224-1238` | Build D3/P2 |
| 5 | M5 provenance metadata | helper | metadata-only source | `web_app.py:1241-1253` | Build D5/P3 |
| 6 | M5 summary builder | helper | correction counts | `web_app.py:1256-1306` | Build workflow aggregator |

### 6.4 · Restore metric path

- **命令**:`nl -ba legal_redactor/restore.py | sed -n '1,90p'`
- **实测时间**:2026-06-29 CST

| # | 名称 | 文档分类 | 权威分类 | 权威源行号 | 动作 |
|---|---|---|---|---|---|
| 1 | `restore_text` | helper | text restore source | `restore.py:9-19` | Use only with supplied evidence |
| 2 | `preview_restore` | helper | preview/diff evidence | `restore.py:42-61` | Build restore unresolved metric |
| 3 | all entries restored | helper | restore semantics | `restore.py:64-67` | Count placeholders separately; do not change restore behavior |

## §7 · 断路事件记录

| # | 时间戳 | 类型 | 上下文 | 尝试路径 | 诊断入口 |
|---|---|---|---|---|---|
| 1 | 2026-06-29T15:04:46+08:00 | Gate 0a r0 FAIL | codex-r0 found 1 BLOCKER and 1 HIGH | Repaired docs to separate existing eval raw diagnostics from M6 privacy-safe projection and to include `document_input_to_saved_case_ms` timing | `.ff-state/reviews/M6-regression-measurement-gate0a/outputs/codex-r0.md` |
| 2 | 2026-06-29T18:15:00+08:00 | Gate 2 r0 FAIL | codex-r0 found case-name privacy leak and malformed eval traceback; grok-r0 found report timing boundary issue | Repaired gold projection to stable `case_id`, added no-traceback CLI error handling, moved report timing after assembly, added malformed summary and value-sanitizer tests | `.ff-state/reviews/M6-regression-measurement-gate2/outputs/codex-r0.md`, `.ff-state/reviews/M6-regression-measurement-gate2/outputs/grok-r0.md` |

## §8 · DoD 闭环条目

- [x] Six-file spec set drafted.
- [x] Intent Guard recorded.
- [x] Grep trace recorded for requirements, eval paths, M5 summary, and restore metric.
- [x] validation_profile/effective_profile recorded as `standard`.
- [x] `milestone-doc-check.mjs --dir` passes before Gate 0a.
- [x] Gate 0a review passes with real `codex,grok` artifacts.
- [x] Step 0 POC E-1 through E-5 executed.
- [x] Gate 0b review passes with real `codex,grok` artifacts.
- [x] Handoff target points to `/ffcs:build M6-regression-measurement`.
- [x] Clean build baseline passed before implementation.
- [x] RED-first failure witnessed before M6 implementation.
- [x] M6 regression report helpers and CLI output implemented.
- [x] README/M8 handoff docs updated.
- [x] Focused and full tests passed after r1 repair.
- [x] Sensitive sample/report/map audit passed.
- [x] Model default audit passed.
- [x] Gate 2 review-repair passes with real `codex,grok` artifacts.

## §11 · Build Closeout

- **final_status**:✅ Build 完成
- **next_command**:`/ffcs:spec M7-discord-hermes-restore-status`
- **Gate 0a**:PASS · `.ff-state/reviews/M6-regression-measurement-gate0a/chair-signoff.json`
- **Gate 0b**:PASS · `.ff-state/reviews/M6-regression-measurement-gate0b/chair-signoff.json`
- **Gate 2**:PASS · `.ff-state/reviews/M6-regression-measurement-gate2/chair-signoff.json`
- **POC**:E-1 through E-5 completed with no blocking findings.
- **Validation**:
  - `.venv/bin/python -m pytest tests/test_regression.py` · `10 passed`
  - `.venv/bin/python -m pytest tests/test_regression.py tests/test_sample_integration.py tests/test_pipeline.py` · `58 passed`
  - `.venv/bin/python -m pytest` · `180 passed, 11 subtests passed`
  - `ruff check legal_redactor/regression.py legal_redactor/__main__.py tests/test_regression.py` · PASS
  - sensitive audit/model audit/doc-check · PASS
- **Non-blocking followups**:
  - Optional LOW: catch `OSError` for missing `--regression-redacted` or `--regression-map` evidence paths.
  - Optional LOW: align optional finish-time type annotation if touched later.

## §9 · SessionEnd 快照

No hook snapshot for this spec run.

## §10 · 决策日志

| # | 时间 | 决策 | 触发 | 影响 |
|---|---|---|---|---|
| 1 | 2026-06-29 | Use standard validation profile | `local-config.mjs profile` returned default `standard` | No profile upshift/downshift |
| 2 | 2026-06-29 | Treat M6 as complex complexity and medium risk | 5-8 day box, report schema, sample privacy, M8 handoff, Gate 0b POC | Six-file set with POST_GA and POC |
| 3 | 2026-06-29 | Use existing gold evaluator as baseline | `evaluation.py` and `__main__.py` already emit precision/recall/F1 | Build wraps instead of replacing evaluator |
| 4 | 2026-06-29 | Keep raw samples out of report/docs/review | Sensitive sample boundary applies to M6 | Synthetic tests and metadata-only provenance |
| 5 | 2026-06-29 | Defer remote restore timing to M7 | M7 owns Discord/Hermes status and credentials | M6 report uses null/deferred remote timing fields |
| 6 | 2026-06-29 | Sanitize M6 gold projection | codex-r0 BLOCKER found raw `matched`/`missing`/`extra` eval diagnostics could conflict with D4/P5 | Existing eval report remains compatible; M6 default JSON stores aggregate metrics and per-case counts only |
| 7 | 2026-06-29 | Include saved-case timing | codex-r0 HIGH found missing document input to saved case timing | M6 report defines nullable `timing.document_input_to_saved_case_ms` and POC E-5 verifies evidence/fallback |
