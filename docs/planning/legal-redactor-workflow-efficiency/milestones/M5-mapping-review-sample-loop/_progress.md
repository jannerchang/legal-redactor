# M5-mapping-review-sample-loop · mapping-review-sample-loop · _progress

> **依据**:[README.md](README.md) + [EXECUTION_PLAN.md](EXECUTION_PLAN.md)
> **格式**:状态速览 + Intent Guard + Gate 节 + 硬门槛证据 + Step 日志 + grep 留痕 + 断路记录 + DoD 闭环 + 决策日志
> **更新节奏**:每 Step / Gate / 断路事件实时更新
> **版本**:v1.0 · 2026-06-29

---

## §1 · 状态速览

```text
milestone: M5-mapping-review-sample-loop
module: mapping-review-sample-loop
当前阶段: ✅ Build complete · Gate 2 PASS
当前 Step: closeout complete
当前批次: /ffcs:build M5-mapping-review-sample-loop
complexity: complex
risk: medium
validation_profile: standard
effective_profile: standard
profile_source: default
时间盒进度: build implementation and Gate 2 closeout completed in current Codex run
最近 commit SHA: 6dc17b6
分支: main
HEAD: 6dc17b6
工作区: existing M3/M4 product/test/planning changes remain dirty; M5 build touched web/sample/tests/docs
待办: handoff to `/ffcs:spec M6-regression-measurement` when continuing the optimization program
```

## §2 · Intent Guard

### Q1 · feature 简洁度 / 抽象层数?

**答**:M5 should add a small row-classification/sample-summary layer around the
existing Web mapping result page and sample helpers. It should not create a
second app, rewrite the recognition engine, change the MLX runtime, or require
live sample data.

### Q2 · 当前 spec 目标 scope?

**答**:Scope is mapping review and sample learning UX: filters/views,
`map_reason` preservation, restore-risk warnings, structured sample-save
summary, refreshless save behavior, and M6 handoff fields. It does not tune
rules from newest samples, run gold-set measurement, or implement runtime
benchmarking.

### Q3 · "可选 / 推荐项" 分类?

**答**:Exact visual style for filters, counters, and warnings is reversible build
detail. Hard gates are the row category vocabulary, `map_reason` preservation,
sample summary schema, sample-safety guards, local sample-data boundary,
refreshless context preservation, server recompute, and M6 handoff keys.

## §3 · Gate 节

### Gate 0a · 规划文档评审

- **评审输入**:README + EXECUTION_PLAN + HUMAN_TASKS + step-0-poc-report + _progress + POST_GA_OBSERVATION + milestone-doc-check output
- **评审池**:`codex,grok`
- **状态**:✅ PASS
- **validation_profile**:`standard`
- **effective_profile**:`standard`
- **profile_source**:`default`
- **结构机检**:`milestone-doc-check` PASS · `files_scanned=6` · `findings=0`
- **artifacts**:
  - `.ff-state/reviews/M5-mapping-review-sample-loop-gate0a/artifacts/codex-r1.json` · `status=ok` · `verdict=PASS`
  - `.ff-state/reviews/M5-mapping-review-sample-loop-gate0a/artifacts/grok-r1.json` · `status=ok` · `verdict=PASS`
  - `.ff-state/reviews/M5-mapping-review-sample-loop-gate0a/chair-signoff.json` · `status=ok` · `verdict=PASS` · `decision=pass_defer`
- **结果**:`all_pass=true` · `peer_all_pass=true` · `failed=[]`

### Gate 0b · POC 放行

- **评审输入**:[step-0-poc-report.md](step-0-poc-report.md) E-1 through E-3 results
- **评审池**:`codex,grok`
- **状态**:✅ PASS
- **POC 结果**:E-1/E-2/E-3 all `非阻塞`; Defense PASS and `非阻塞`
- **POC focused verification**:`.venv/bin/python -m pytest tests/test_sample_integration.py` · `16 passed in 8.93s`
- **artifacts**:
  - `.ff-state/reviews/M5-mapping-review-sample-loop-gate0b/artifacts/codex-r0.json` · `status=ok` · `verdict=PASS`
  - `.ff-state/reviews/M5-mapping-review-sample-loop-gate0b/artifacts/grok-r0.json` · `status=ok` · `verdict=PASS`
  - `.ff-state/reviews/M5-mapping-review-sample-loop-gate0b/chair-signoff.json` · `status=ok` · `verdict=PASS` · `decision=pass_defer`
- **结果**:`all_pass=true` · `peer_all_pass=true` · `failed=[]`
- **accepted followups**:M6 handoff schema finalized during build; Gate 2 T6 proves tracked test and clean sensitive-data audit.

### Checkpoint 1 · Step 1 ~ N-1 自验

- Step 1:✅ complete · row classifier and sample summary helpers implemented
- Step 2:✅ complete · review filters and restore-risk UI implemented
- Step 3:✅ complete · refreshless sample save and M6 handoff implemented

### Gate 2 · DoD 闭环

- **评审输入**:implementation diff, focused/full tests, browser smoke, sensitive-data audit, docs closeout
- **评审池**:`codex,grok`
- **状态**:✅ PASS
- **结构机检**:`.ff-state/logs/M5-build-milestone-doc-check-gate2-2026-06-29.log` · `files_scanned=6` · `findings=0`
- **测试证据**:
  - `.ff-state/logs/M5-build-baseline-focused-2026-06-29.log` · baseline focused suite `55 passed, 6 subtests passed`
  - `.ff-state/logs/M5-build-red-first-2026-06-29.log` · RED-first run witnessed 4 expected failures before implementation
  - `.ff-state/logs/M5-build-focused-2026-06-29.log` · focused suite `60 passed, 6 subtests passed`
  - `.ff-state/logs/M5-build-full-pytest-2026-06-29.log` · full regression rerun after final low-confidence mirror fix · `170 passed, 11 subtests passed`
  - `.ff-state/logs/M5-build-browser-smoke-2026-06-29.json` · isolated browser smoke PASS with synthetic data only; proves modified/delete filters, restore-risk code, and retry delta
- **敏感样本审计**:`git ls-files samples` empty; `git check-ignore -v samples/_auto.sample.json` points to `.gitignore:9 samples/`; `git status --short -- samples '*.sample.json' '*redaction_map*'` empty; `git ls-files --error-unmatch tests/test_sample_integration.py tests/test_web_app.py` passes after `git add -N`
- **pre-push checklist**:`.ff-state/logs/M5-build-pre-push-checklist-2026-06-29.json` · `severity=pass` · `blocker_reasons=[]` · `codex,grok` present; check_1 skipped/pass due `git ls-files` ENOBUFS, covered by separate T6 git audit above
- **review artifacts**:
  - `.ff-state/reviews/M5-mapping-review-sample-loop-gate2/artifacts/codex-r1.json` · `status=ok` · `verdict=PASS` · `blocker_count=0` · `high_count=0`
  - `.ff-state/reviews/M5-mapping-review-sample-loop-gate2/artifacts/grok-r1.json` · `status=ok` · `verdict=PASS` · `blocker_count=0` · `high_count=0`
  - `.ff-state/reviews/M5-mapping-review-sample-loop-gate2/chair-signoff.json` · `status=ok` · `verdict=PASS` · `decision=pass_defer`
- **结果**:`all_pass=true` · `peer_all_pass=true` · `failed=[]`
- **accepted followups**:M6 consumes `sample_summary` keys without reading raw sensitive sample files; POST_GA observation remains opt-in and focuses sample-save safety/context preservation.

## §4 · 硬门槛证据追踪

| 层 | 条目 | 状态 | 证据 |
|---|---|---|---|
| D | D1-D9 row/sample data contracts | ✅ | `legal_redactor/web_app.py` row categories + sample summary keys; forged-label test `test_save_sample_page_recomputes_summary_from_rows_not_forged_labels` |
| P | P1-P5 pure helpers | ✅ | `_classify_mapping_review_row`, `_build_sample_save_summary`, `_sample_summary_response`, `_samples.is_sample_lookup_allowed` |
| S | S1-S3 service recompute/retry behavior | ✅ | Save-sample route recomputes from form rows/original map/delete flags; retry delta reports created/updated/unchanged; focused suite PASS |
| N | N1-N2 in-page/no-external notification | ✅ | `sample_summary` postMessage + no Discord/Hermes call in save-sample path; browser smoke URL stayed `/redact` |
| C+A | CA1-CA5 filters/UI/context | ✅ | `mapping-review-toolbar`, `sample-summary-panel`, `data-map-filter`, `data-map-row`; browser smoke proves modified/delete/restore-risk dynamic filters |
| T | T1-T6 tests/audit | ✅ | Focused `60 passed`; full `170 passed`; sensitive sample and tracked-test audit PASS |
| E | E1-E4 docs/handoff/POST_GA | ✅ | README updated; M6 README handoff fields added; POST_GA plan present |
| Delivery | pre-push checklist | ✅ | `.ff-state/logs/M5-build-pre-push-checklist-2026-06-29.json` · `severity=pass` |

## §5 · Step 执行日志

| Step | 起 commit | 止 commit | 交付规模 | 关键事件 |
|---|---|---|---|---|
| Spec draft | 6dc17b6 | not committed | M5 spec docs | Expanded M5 from planned README to complex six-file spec set |
| Gate 0a | 6dc17b6 | not committed | review artifacts | r0 findings repaired; codex-r1/grok-r1/chair PASS |
| Step 0 POC | 6dc17b6 | not committed | POC report | E-1/E-2/E-3 and Defense recorded as non-blocking with code/test evidence |
| Gate 0b | 6dc17b6 | not committed | review artifacts | codex-r0/grok-r0/chair PASS; Grok doc-hygiene findings accepted/repaired/deferred |
| Step 1 build | 6dc17b6 | not committed | tests | Baseline focused suite stored at `.ff-state/logs/M5-build-baseline-focused-2026-06-29.log`; RED-first failures stored at `.ff-state/logs/M5-build-red-first-2026-06-29.log` |
| Step 2 build | 6dc17b6 | not committed | code/tests | Row classifier, sample summary, guard wrapper, refreshless `sample_summary` response, and forged-label tests implemented |
| Step 3 build | 6dc17b6 | not committed | UI/JS/tests | Mapping filters, row badges, sample summary panel, add-row filter metadata, and Web tests implemented |
| Step 4 build | 6dc17b6 | not committed | validation/docs | Focused/full pytest PASS, isolated browser smoke PASS, sensitive-data audit PASS, README/M6 handoff docs updated |
| Gate 2 closeout | 6dc17b6 | not committed | review/progress | codex-r1/grok-r1/chair PASS, machine proof `all_pass=true`, doc-check gate2 PASS |

## §6 · grep 留痕

### 6.1 · Requirements and split anchors

- **命令**:`rg -n "mapping review|map_reason|low confidence|added manually|modified|deleted as false positive|restore-risk|sample-reused|saving samples|delete blacklist|suppressed|regression|province abbreviations|refresh|samples/_auto|newest sample|correction counts|false-positive deletes|missing adds" docs/planning/legal-redactor-workflow-efficiency/REQUIREMENTS.md docs/planning/legal-redactor-workflow-efficiency/SPLIT.md docs/planning/legal-redactor-workflow-efficiency/milestones/M5-mapping-review-sample-loop/README.md`
- **实测时间**:2026-06-29 CST

| # | 名称 | 文档分类 | 权威分类 | 权威源行号 | 动作 |
|---|---|---|---|---|---|
| 1 | mapping review faster than full table | requirement | review UX | `REQUIREMENTS.md:79-82`, `REQUIREMENTS.md:182-191` | Build CA1/CA2 |
| 2 | preserve `map_reason` | requirement | rationale field | `REQUIREMENTS.md:108-112`, `REQUIREMENTS.md:183-184` | Build D2/P1/T2 |
| 3 | sample-save summary | requirement | sample learning feedback | `REQUIREMENTS.md:192-197` | Build D3/CA3 |
| 4 | short person and province guards | requirement | sample safety | `REQUIREMENTS.md:198-200` | Build D4/D5 |
| 5 | no context-dropping refresh | requirement | review state | `REQUIREMENTS.md:200` | Build D6/CA4/N1 |
| 6 | local sensitive samples | requirement/signoff | privacy boundary | `REQUIREMENTS.md:68`, `REQUIREMENTS.md:207`, `SPLIT.md:88-89` | Build D6/T6 |
| 7 | M6 correction metrics | downstream | measurement handoff | `REQUIREMENTS.md:218-229`, `SPLIT.md:33`, `SPLIT.md:75-76` | Build D8/P5/E2 with `restore_unresolved_placeholders` and `newest_sample_provenance` |

### 6.2 · Current Web mapping/save paths

- **命令**:`nl -ba legal_redactor/web_app.py | sed -n '978,1146p'` and `nl -ba legal_redactor/web_app.py | sed -n '2907,2993p'`
- **实测时间**:2026-06-29 CST

| # | 名称 | 文档分类 | 权威分类 | 权威源行号 | 动作 |
|---|---|---|---|---|---|
| 1 | `/redact/apply-edited-map` row metadata | route | edit apply path | `web_app.py:978-1014` | Preserve and classify rows |
| 2 | save-sample reads `map_reason` | route | sample reason path | `web_app.py:1051-1128` | Preserve as sample `reason` |
| 3 | save-sample toast summary | route | current summary baseline | `web_app.py:1130-1146` | Replace/extend with structured summary |
| 4 | current mapping JSON includes reason | client helper | row snapshot | `web_app.py:2907-2928` | Reuse for filters/save |
| 5 | appended row metadata | client helper | manual add path | `web_app.py:2956-2993` | Add reason/category preservation tests |

### 6.3 · Current sample guards and tests

- **命令**:`nl -ba legal_redactor/_samples.py | sed -n '225,389p'` and `nl -ba tests/test_sample_integration.py | sed -n '78,522p'`
- **实测时间**:2026-06-29 CST

| # | 名称 | 文档分类 | 权威分类 | 权威源行号 | 动作 |
|---|---|---|---|---|---|
| 1 | `is_global_delete_sample_allowed` | helper | risky delete guard | `_samples.py:225-232` | Reuse in P4/S1 |
| 2 | `_sample_lookup_allowed` | helper | province/case-number guard | `_samples.py:382-389` | Preserve D5 |
| 3 | trusted mapping loader | helper | sample-reused rows | `_samples.py:313-360` | Use for sample-reused category |
| 4 | short person delete tests | tests | safety regression | `tests/test_sample_integration.py:100-141`, `tests/test_sample_integration.py:470-522` | Extend, do not regress |
| 5 | province abbreviation tests | tests | lookup safety | `tests/test_sample_integration.py:78-98`, `tests/test_sample_integration.py:161-189` | Extend, do not regress |
| 6 | save-sample reason tests | tests | reason persistence | `tests/test_sample_integration.py:365-467` | Extend for summary |

### 6.4 · Sensitive sample-data boundary

- **命令**:`nl -ba .gitignore | sed -n '1,30p'`
- **实测时间**:2026-06-29 CST

| # | 名称 | 文档分类 | 权威分类 | 权威源行号 | 动作 |
|---|---|---|---|---|---|
| 1 | `samples/` ignored | git safety | local-only samples | `.gitignore:9` | Preserve D6/T6 |
| 2 | generated JSON ignored | git safety | maps/sample data | `.gitignore:10` | Audit before delivery |
| 3 | required M5 sample test unignored | git safety | deliverable test evidence | `.gitignore:23` | T6 requires `git ls-files --error-unmatch tests/test_sample_integration.py` after implementation |

## §7 · 断路事件记录

| # | 时间戳 | 类型 | 上下文 | 尝试路径 | 诊断入口 |
|---|---|---|---|---|---|
| 1 | 2026-06-29T00:00:00+08:00 | none | Spec drafting | No blocker | Not needed |

## §8 · DoD 闭环条目

- [x] Six-file spec set exists.
- [x] `milestone-doc-check.mjs --dir` passes before Gate 0a.
- [x] Gate 0a review passes with real `codex,grok` artifacts.
- [x] Step 0 POC E-1 through E-3 recorded.
- [x] Gate 0b review passes with real `codex,grok` artifacts.
- [x] `_progress.md` records profile, complexity, grep trace, POC, and next command.
- [x] Handoff target points to `/ffcs:build M5-mapping-review-sample-loop`.
- [x] Build implementation completed and Gate 2 material prepared.
- [x] Focused suite passed: `.ff-state/logs/M5-build-focused-2026-06-29.log`.
- [x] Full regression passed: `.ff-state/logs/M5-build-full-pytest-2026-06-29.log`.
- [x] Browser smoke passed with synthetic data and isolated `/tmp` sample dir: `.ff-state/logs/M5-build-browser-smoke-2026-06-29.json`.
- [x] Sensitive sample audit passed: no tracked `samples/`; sample JSON remains ignored; M5 tests are trackable through `git add -N`.
- [x] README and M6 handoff docs updated with visible filter/summary behavior and stable summary keys.
- [x] Gate 2 review-repair passed with `codex,grok` artifacts and chair signoff.
- [x] Gate 2 machine proof passed: `all_pass=true`, `peer_all_pass=true`, `failed=[]`.
- [x] FFCS pre-push checklist passed with no blocker.
- [x] M5 closeout points the next optimization command to `/ffcs:spec M6-regression-measurement`.

## §9 · SessionEnd 快照

No hook snapshot for this spec run.

## §10 · 决策日志

| # | 时间 | 决策 | 触发 | 影响 |
|---|---|---|---|---|
| 1 | 2026-06-29 | Use standard validation profile | `local-config.mjs profile` returned default `standard` | No profile upshift/downshift |
| 2 | 2026-06-29 | Treat M5 as complex complexity and medium risk | 7-10 day time box, Web/sample/M6 surface, >20 hard gates; no external credentials or runtime change | Six-file set with POST_GA and Gate 0b POC |
| 3 | 2026-06-29 | Preserve existing result page | Requirements target faster mapping review, not a second app | Filters/warnings in current Web page |
| 4 | 2026-06-29 | Use server-authoritative recompute for row labels and sample summary | Filter/risk/status labels are decision-like and form-submitted | D9/S1/T2 require forged-label tests |
| 5 | 2026-06-29 | Keep real sample data out of docs/review/material | `samples/_auto.sample.json` can contain sensitive originals | Synthetic examples only; T6 audit before delivery |
| 6 | 2026-06-29 | Canonicalize decision IDs to README D-01 through D-09 | Gate 0a r0 review found D-08/D-09 collision | EXECUTION_PLAN §2 now mirrors README decisions |
| 7 | 2026-06-29 | Track required sample integration tests in Git | Gate 0a r0 review found `tests/test_sample_integration.py` was ignored by `tests/*` | `.gitignore` unignores the required M5 test path and T6 audits it |
| 8 | 2026-06-29 | Anchor low-confidence filter to existing pipeline semantics | Gate 0a r1 MEDIUM noted threshold drift risk | README/EXECUTION_PLAN now cite `confidence < 0.85` and `review_candidates` membership |
| 9 | 2026-06-29 | Gate 0b accepts Step 0 POC as non-blocking | Codex and Grok r0 PASS; chair `pass_defer` | Build may start; progress/doc closeout and Gate 2 audit followups retained |
| 10 | 2026-06-29 | Next command is `/ffcs:build M5-mapping-review-sample-loop` | `/ffcs:spec` Gate 0b PASS | Handoff points build to M5 spec docs, POC, and Gate artifacts |
| 11 | 2026-06-29 | Gate 2 PASS closes M5 build | `codex-r1` and `grok-r1` PASS, chair `pass_defer`, proof `all_pass=true` | Next workflow milestone is `/ffcs:spec M6-regression-measurement` |
| 12 | 2026-06-29 | Pre-push checklist passes without blocker | `pre-push-checklist.mjs` exit 0, `severity=pass` | No GitHub delivery was started in this command |
