# M5-mapping-review-sample-loop · mapping-review-sample-loop · 执行计划

> **依据**:[README.md](README.md), [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §6.3, [../../SPLIT.md](../../SPLIT.md)
> **格式**:七层硬门槛 + 决策表 + Step 顺序 + 时间盒 + 跨模块签字 + 服务端权威重算 + 文档维护扫
> **schema 引用**:/Users/example/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.0.123/templates/gate.schema.md
> **更新节奏**:Step 进 / 出时同步本文件 + [_progress.md](_progress.md)
> **版本**:v1.0 · 2026-06-29

---

## §1 · 七层硬门槛

| id | title | description | evidence_required | pass_condition | block_severity | typical_count |
|---|---|---|---|---|---|---:|
| D1 | Row categories fixed | Define server-computed row category values for `low_confidence`, `manual_added`, `modified`, `delete_candidate`, `restore_risk`, and `sample_reused`; `low_confidence` follows existing pipeline review semantics (`confidence < 0.85` or existing `review_candidates` membership). | code_path_read, unit_test_count | Tests prove every rendered/filterable row category comes from the allowed set and is recomputed from row facts. | BLOCKER | 1 |
| D2 | Reason preserved | Preserve `map_reason` across render, add-row, apply-edited-map, save-sample, and sample-edit flows. | integration_test_count, code_path_read | Focused tests fail if a non-empty reason disappears from the edited map or saved sample entry. | BLOCKER | 1 |
| D3 | Sample summary schema | Define a structured sample-save summary with counts and row labels for lookup entries, delete blacklist candidates, suppressed risky entries, and suggested regression checks. | unit_test_count, integration_test_count | Save-sample response includes machine-readable or testable summary fields for all four classes. | BLOCKER | 1 |
| D4 | Risky delete guard kept | Keep short common Chinese person names out of global delete blacklists unless their type is an explicitly safe structured type. | unit_test_count | Existing and new tests prove 2-3 character person-like deletes do not enter `load_all_samples()` blacklist or LLM few-shot negatives. | BLOCKER | 1 |
| D5 | Province abbreviation guard kept | Keep one-character province abbreviations out of trusted lookup samples. | unit_test_count | Tests prove `冀` and other one-character province abbreviations cannot become trusted sample mappings. | BLOCKER | 1 |
| D6 | Local sample boundary | Treat `samples/_auto.sample.json` as local sensitive data and never as committed evidence. | grep_stdout | Git audit before delivery proves `samples/` remains ignored and no tracked sample data was added. | BLOCKER | 1 |
| D7 | Restore-risk visible | Rows that are likely to break restore or suppress true entities are visibly flagged before sample save. | integration_test_count | Web tests prove risky delete or restore-disabled rows render warning labels and appear in summary. | HIGH | 1 |
| D8 | M6 handoff fields | Emit downstream summary fields for correction count, false-positive deletes, missing adds, suppressed risky rows, restore unresolved placeholders, newest-sample provenance, and suggested regression commands. | doc_anchor, integration_test_count | Build closeout records field names and tests prove they are present in save summary. | HIGH | 1 |
| D9 | No client-trusted labels | Browser-submitted row category/status/filter labels are not accepted as final sample-save decisions. | integration_test_count | Forged category/status fields do not affect saved sample entries or summary counts. | BLOCKER | 1 |
| P1 | Row classifier pure | Add a pure row classifier that consumes original mapping, edited row facts, confidence, source, reason, delete flag, restore flag, sample metadata, and existing `review_candidates` membership. | unit_test_count | Classifier tests cover all D1 categories, `confidence < 0.85` low-confidence rows, and mixed-category rows. | BLOCKER | 1 |
| P2 | Summary builder pure | Add a pure sample summary builder shared by the Web route and tests. | unit_test_count | Summary builder output matches actual entries passed to `save_sample_auto()`. | BLOCKER | 1 |
| P3 | Restore-risk classifier | Add a pure helper for restore-risk warnings such as delete candidate, restore disabled, empty mask, or risky global suppression. | unit_test_count | Restore-risk helper returns stable reason codes and human-readable text. | HIGH | 1 |
| P4 | Existing guard reuse | Reuse `_samples.py` guard helpers instead of duplicating person/province heuristics in Web code. | code_path_read | Code review shows Web summary calls shared sample guard helpers. | HIGH | 1 |
| P5 | M6 projector | Add a small projector that converts the save summary into M6-friendly metric keys. | unit_test_count, doc_anchor | Tests or docs list stable keys for M6: `manual_corrections`, `false_positive_deletes`, `missing_adds`, `suppressed_risky_entries`, `restore_unresolved_placeholders`, `newest_sample_provenance`, `regression_suggestions`. | MEDIUM | 1 |
| S1 | Authoritative recompute | Server recomputes filter/category/summary from original map, edited rows, delete flags, restore flags, and sample guards. | integration_test_count | Submitting forged category/filter/status fields does not change saved entries or summary. | BLOCKER | 1 |
| S2 | Bounded form parsing | Save-sample and apply-edited-map routes handle mismatched row arrays deterministically and without index exceptions. | unit_test_count, integration_test_count | Tests cover missing reason/confidence/restore fields and invalid delete indexes. | HIGH | 1 |
| S3 | Retry safe save | Repeated save of the same correction does not duplicate effective sample entries or report misleading new counts. | unit_test_count | Sample merge tests prove same original/action is overwritten or merged as designed. | HIGH | 1 |
| N1 | In-page notification | Sample-save result uses in-page message/update behavior, not full-page navigation. | integration_test_count | Test or browser smoke proves save-sample returns message/update payload and the review form remains present. | BLOCKER | 1 |
| N2 | No external sample notify | No Discord/Hermes/API notification path sends sample details, originals, maps, or restored full text. | grep_stdout, integration_test_count | Grep/tests prove save-sample path has no Discord/Hermes call and no outbound sample content. | BLOCKER | 1 |
| CA1 | Review filters | Add action-focused mapping review filters or views for low-confidence, added, modified, deleted, restore-risk, and sample-reused rows. | integration_test_count | Rendered HTML contains controls and row attributes for each category. | BLOCKER | 1 |
| CA2 | Counter defaults | Default view shows all rows plus action counters; filters narrow only when explicitly chosen. | integration_test_count | Tests prove all rows are present by default and counters match row classes. | HIGH | 1 |
| CA3 | Sample summary UI | User sees sample-save summary with lookup, blacklist, suppressed, and regression suggestion counts. | integration_test_count | Web test asserts summary text or JSON fields after save. | BLOCKER | 1 |
| CA4 | Context preserved | Save-sample does not drop current mapping rows, case context fields, filters, scroll target, or edited reasons. | integration_test_count, browser_smoke | Browser smoke or Web test proves current form context remains after save. | BLOCKER | 1 |
| CA5 | Restore warning UI | Restore-risk warnings appear before save for delete/restore-disabled/risky rows. | integration_test_count | Tests assert warning labels are rendered for representative risky rows. | HIGH | 1 |
| T1 | Sample integration tests | Extend `tests/test_sample_integration.py` for summary builder, guards, retry merge, and M6 projector. | unit_test_count | `.venv/bin/python -m pytest tests/test_sample_integration.py` passes. | BLOCKER | 1 |
| T2 | Web tests | Extend `tests/test_web_app.py` for filters, warnings, forged labels, reason preservation, and refreshless save. | integration_test_count | `.venv/bin/python -m pytest tests/test_web_app.py` passes. | BLOCKER | 1 |
| T3 | Focused workflow suite | Run focused M5 suite with sample and Web tests. | unit_test_count, integration_test_count | Focused suite passes or blocks Gate 2. | BLOCKER | 1 |
| T4 | Full regression | Run full pytest if shared `web_app.py`, `_samples.py`, or mapping rendering behavior changes broadly. | unit_test_count | Full pytest passes or scoped failure is documented and justified. | HIGH | 1 |
| T5 | Browser smoke | Run a local browser smoke for paste/upload result, filter toggle, manual add, sample save, and context preservation. | doc_anchor | Build closeout records browser steps, URL, and result. | HIGH | 1 |
| T6 | Sensitive data and test audit | Before any GitHub delivery, inspect tracked files and diff for `samples/_auto.sample.json`, maps, originals, restored text, or sample contents; also prove required M5 tests are trackable. | grep_stdout | Delivery checklist confirms no sensitive data is tracked or staged and `git ls-files --error-unmatch tests/test_sample_integration.py` succeeds after implementation. | BLOCKER | 1 |
| E1 | README docs | Update README or operator docs only for user-visible mapping/sample workflow behavior. | doc_anchor | Docs explain filters and sample summary without exposing sample data. | MEDIUM | 1 |
| E2 | M6 handoff | Update M6 README or M5 closeout with exact summary fields available for regression measurement. | doc_anchor | M6 can start without re-discovering M5 output shape. | HIGH | 1 |
| E3 | Progress closeout | `_progress.md` records Gate 0a/0b/2 artifacts, validation/effective profile, POC results, and DoD evidence. | doc_anchor | Gate closeout is complete before handoff. | BLOCKER | 1 |
| E4 | POST_GA observation | Keep `POST_GA_OBSERVATION.md` for D+1/D+7 review of sample-save safety and context preservation after merge. | doc_anchor | POST_GA plan exists and is linked from closeout. | MEDIUM | 1 |

## §2 · 决策表

| # | 决策 | 影响范围 | 来源 | 状态 |
|---|---|---|---|---|
| D-01 | Keep existing redaction result page as mapping-review surface. | Web result UI/tests | README D-01 | 锁 |
| D-02 | Server computes row categories from raw row facts. | Web route/helpers/tests | README D-02, D-09 | 锁 |
| D-03 | Preserve `map_reason` through edit/apply/save/sample-edit. | Web/sample entries | README D-03 | 锁 |
| D-04 | Return structured sample-save summary. | Web route, M6 | README D-04, D-08 | 锁 |
| D-05 | Preserve risky delete and province abbreviation guards. | `_samples.py`, tests | README D-05 | 锁 |
| D-06 | Use in-page save result, no context-dropping refresh. | Web UI/JS/tests | README D-06 | 锁 |
| D-07 | Keep sample data local and ignored. | Git delivery, docs | README D-07 | 锁 |
| D-08 | Export M6-friendly summary keys. | M6 regression | README D-08 | 锁 |
| D-09 | Server-authoritative row/sample recompute. | Web route/helpers/tests | README D-09 | 锁 |

### §2 附录 · 决策详情

| # | rationale | signoff_version | evidence_link |
|---|---|---|
| D-01 | Existing result page already contains the mapping form and sample-save actions; adding filters in place is the lowest-disruption path. | v1.0 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §6.3 |
| D-02 | Row categories must derive from row facts so filters, warnings, and sample summaries stay consistent. | v1.0 | [README.md](README.md) D-02 |
| D-03 | `map_reason` is the user's explanation for why a correction exists and must survive into sample diagnostics. | v1.0 | `legal_redactor/web_app.py` save-sample route |
| D-04 | A plain toast count is not enough for the user to know what future behavior changes. | v1.0 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §6.3 |
| D-05 | Prior sample-safety fixes prevent short names and one-character provinces from becoming broad suppressions or replacements. | v1.0 | `legal_redactor/_samples.py` guard helpers |
| D-06 | Review context is the active work state; navigation or reload loses row edits, filters, and reasons. | v1.0 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §6.3 |
| D-07 | Sample files can contain sensitive originals/corrections and are intentionally ignored by Git. | v1.0 | `.gitignore` |
| D-08 | M6 needs correction counts, newest-sample signals, and restore placeholder counts; M5 should provide stable summary keys at source. | v1.0 | [../../SPLIT.md](../../SPLIT.md) M5/M6 dependency |
| D-09 | Filter/status/risk labels are decision-like and must not be trusted from stale browser state. | v1.0 | /Users/example/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.0.123/templates/authoritative-recompute.md |

## §3 · Step 顺序

### Step 0 · POC + 防护栏

**时间盒**:`1 day`

1. Run `milestone-doc-check.mjs --dir` before Gate 0a.
2. POC E-1: read current mapping form/apply/save paths and confirm where row
   metadata and `map_reason` already flow.
3. POC E-2: read sample guard and merge behavior to confirm summary/guard
   helpers can stay pure.
4. POC E-3: read current save-sample response and JS message path to confirm
   refreshless context preservation can be implemented in place.
5. Update `step-0-poc-report.md`, then run Gate 0b review before build.

### Step 1 · row classifier + sample summary helpers

**时间盒**:`2 days`

- Add pure row classification and summary helpers near the Web/sample boundary.
- Reuse `_samples.py` guards for short names and province abbreviations.
- Include stable M6 metric keys in the summary object.

**Checkpoint 1**:

- `tests/test_sample_integration.py` covers row summary classes, M6 keys, and
  existing guard preservation.

### Step 2 · review filters + restore-risk UI

**时间盒**:`2 days`

- Add compact filter controls/counters to the existing mapping review table.
- Render row attributes/classes for filter categories.
- Render restore-risk warnings before save.

**Checkpoint 2**:

- `tests/test_web_app.py` covers filter controls, category attributes, default
  all-row view, and warning labels.

### Step 3 · refreshless sample save + M6 handoff

**时间盒**:`2 days`

- Return structured sample-save summary through in-page message/update behavior.
- Preserve current rows, filter choice, reasons, scroll target, and M4 case
  context fields.
- Prevent forged category/status fields from affecting actual sample writes.
- Update M6 handoff docs with summary keys and suggested regression commands.

**Checkpoint 3**:

- Web tests or browser smoke prove sample save does not reload away the review
  context and repeated saves remain merge-safe.

### Step 4 · tests + docs + Gate 2

**时间盒**:`2-3 days`

- Run focused tests:

```bash
.venv/bin/python -m pytest tests/test_sample_integration.py tests/test_web_app.py
```

- Run full pytest if shared Web/sample behavior changed broadly.
- Run browser smoke for paste/upload result, filter toggle, manual add, sample
  save, and context preservation.
- Audit Git/tracked files for sensitive sample data.
- Update `_progress.md`, M6 handoff, README/docs, and POST_GA plan.
- Run FFCS Gate 2 review with effective `codex + grok` policy.

## §4 · 时间盒细分

| Step | 估时 | 起止 commit | 备注 |
|---|---|---|---|
| Step 0 · POC + 防护栏 | 1 day | complete in spec | Current path readback + doc-check + Gate 0b PASS |
| Step 1 · row classifier + sample summary helpers | 2 days | not committed | Pure helpers first |
| Step 2 · review filters + restore-risk UI | 2 days | not committed | Existing result page |
| Step 3 · refreshless sample save + M6 handoff | 2 days | not committed | Summary + context preservation |
| Step 4 · tests + docs + Gate 2 | 2-3 days | not committed | Review proof and handoff |
| **总计** | **7-10 days** | | |

## §5 · 跨模块签字规则

| 跨模块变更 | 影响下游 | D-XX 决策 | owner_signoffs | 测试覆盖 |
|---|---|---|---|---|
| Sample-save summary schema | M6 regression measurement consumes correction counts | D-04, D-08 | project-local owner accepted by this spec | `tests/test_sample_integration.py`, `tests/test_web_app.py` |
| Mapping row category vocabulary | Web filters and M6 metrics | D-02, D-09 | project-local owner accepted by this spec | `tests/test_web_app.py` |
| Sample guard behavior | Recognition safety and M6 newest-sample tuning | D-05 | project-local owner accepted by this spec | `tests/test_sample_integration.py` |
| Case context preservation through mapping forms | M4 case binding state and M7 restore handoff | D-06 | project-local owner accepted by this spec | `tests/test_web_app.py` |

No external owner or live credential signoff is required for Gate 0a. Live
sample contents are not used as review material.

## §6 · 服务端权威重算

M5 uses status/filter/risk/classification terms and exposes HTTP form routes.
The build must apply server-authoritative recompute:

- D9 requires browser-submitted category/filter/status fields to be ignored or
  rejected as final sample-save decisions.
- S1 requires the sample-save route to recompute summary and actions from raw
  original map JSON, edited row arrays, delete flags, restore flags, confidence,
  source, reason, and shared `_samples.py` guards.
- S2 requires bounded, deterministic handling of mismatched row arrays and
  invalid delete indexes.
- Tests must include at least one forged category/status field proving the
  server's saved entries and summary remain unchanged.

## §7 · 文档维护扫

- [x] `_progress.md` updated with Gate 0a, Gate 0b, Gate 2, validation profile, and effective profile for build closeout.
- [x] README and execution plan remain linked from upstream split docs.
- [x] M6 README or handoff records summary schema and newest-sample provenance fields after build.
- [x] README/user docs updated only for visible filters, warnings, and sample summary.
- [x] `.gitignore` remains protective for `samples/`, maps, originals, runtime logs, and generated case output; M5 test path is unignored for build tracking.
- [x] POST_GA observation plan remains present because M5 is complex.

## §8 · 出口 checklist

- [x] Six-file spec set complete.
- [x] `milestone-doc-check.mjs --dir` passes before Gate 0a.
- [x] Gate 0a review passes with effective policy artifacts.
- [x] Step 0 POC report records E-1 through E-3 results.
- [x] Gate 0b review passes or records non-blocking POC findings.
- [x] `_progress.md` records grep trace, Intent Guard, profile, complexity, and next `/ffcs:build`.
- [x] Row classifier and sample summary helpers implemented and tested.
- [x] Mapping review filters and restore-risk UI implemented and tested.
- [x] Refreshless sample save and M6 handoff implemented and tested.
- [x] Sensitive sample-data audit passes.
- [x] Gate 2 review-repair passes with effective policy artifacts.
