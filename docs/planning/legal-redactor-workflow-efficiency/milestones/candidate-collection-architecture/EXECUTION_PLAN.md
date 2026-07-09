# candidate-collection-architecture · candidate-collector · execution plan

> **Basis**: [README.md](README.md), GitHub issue #8, [../../../../LINEAR_REFACTOR.md](../../../../LINEAR_REFACTOR.md)
> **Schema reference**: `/Users/jannerchang/.claude/plugins/cache/pbvcity/ffcs/1.1.30/templates/gate.schema.md`
> **Update rhythm**: synchronize this file and [_progress.md](_progress.md) at each step/gate
> **Version**: v1.0 · 2026-07-09

---

## §1 · Hard Gates

| id | title | description | evidence_required | pass_condition | block_severity | typical_count |
|---|---|---|---|---|---|---:|
| D1 | Public pipeline entry preserved | `RedactionPipeline.redact` and `redact_many` remain the public orchestration interface; no caller-facing strategy or compatibility branch is added. | prose_only:non_executable_semantic_judgment; lsp_references; diff_readback | All changed callsites use the existing public pipeline entry and no `strategy=legacy` or deleted compatibility branch is restored. | block_severity:BLOCKER | 1 |
| D2 | Collector interface small | `CandidateCollector.collect(context)` is the only discovery seam; no public detector registry/plugin interface is exposed. | prose_only:non_executable_semantic_judgment; code_readback | `candidate_collector.py` exposes context/result plus collector and no detector registration API. | block_severity:BLOCKER | 1 |
| D3 | Design B LLM ownership | Collector accepts `llm_analysis` and owns `linear_llm_exact` candidate materialization; non-primary mode may collect through the same module twice. | prose_only:non_executable_semantic_judgment; unit_test_count | Audit-only entities still enter final candidates as `linear_llm_exact` without keeping `_llm_candidates` in `LinearRuleEngine`. | block_severity:BLOCKER | 1 |
| D4 | Verdict order invariant | LLM reject/calibrate verdicts execute before `resolve_candidate_overlaps` and before acceptance. | prose_only:non_executable_semantic_judgment; unit_test_count | Calibrated span-rewrite case preserves the same winning candidate, source, span, mask, and order. | block_severity:BLOCKER | 1 |
| D5 | Admin DB remains span gate | Admin DB detections remain pre-accepted mappings plus `admin_spans`, distinct from collector seed candidates. | prose_only:non_executable_semantic_judgment; integration_test_count | Admin DB wins over overlapping HanLP and china-rule candidates; admin DB entities are not reintroduced as collector candidates. | block_severity:BLOCKER | 1 |
| D6 | China-admin quirk preserved | Span-filtered pipeline china-rule seed plus current full-text rediscovery behavior is preserved until a later explicit cleanup. | prose_only:non_executable_semantic_judgment; unit_test_count | Characterization fixtures show identical candidate/mapping behavior across collector wiring commits. | block_severity:BLOCKER | 1 |
| D7 | Engine accepts discoveries | `LinearRuleEngine` becomes acceptance/expansion: it accepts pre-collected candidates, applies verdicts/overlap, and emits mappings. | prose_only:non_executable_semantic_judgment; unit_test_count | Engine no longer imports detector discovery functions after the old collection path is deleted. | block_severity:BLOCKER | 1 |
| D8 | Registry removed | The unused `detector_registry` seam is deleted or fully absorbed privately, never left as a tested non-runtime extension point. | prose_only:non_executable_semantic_judgment; grep_stdout | After cleanup, production grep has zero `DetectorRegistry`, `FunctionDetector`, `PartyLineDetector`, or `build_default_registry` matches. | block_severity:BLOCKER | 1 |
| D9 | No legacy relapse | Deleted legacy strategy, detector/filter aliases, pipeline postprocess re-exports, Browser `/api/save-to-local`, and pruned `PipelineConfig` fields stay deleted. | prose_only:non_executable_semantic_judgment; grep_stdout; diff_readback | Scoped grep/diff shows no restored legacy branch, alias surface, save-to-local API, postprocess re-export, or pruned config field. | block_severity:BLOCKER | 1 |
| D10 | Boundaries documented | Durable docs describe only module responsibilities, not every helper or private class. | prose_only:non_executable_semantic_judgment; doc_anchor | `docs/LINEAR_REFACTOR.md` states collector owns discovery/order, engine owns acceptance/expansion, pipeline owns orchestration/result shape. | block_severity:BLOCKER | 1 |
| P1 | RED characterization first | Characterization tests for current offline path, admin/HanLP, and LLM review are added before production discovery moves. | prose_only:non_executable_semantic_judgment; red_test_stdout | First three commits are tests-only and each goes red when pointed at a seeded failing expectation or pre-refactor gap. | block_severity:BLOCKER | 1 |
| P2 | Review selector scoped | Review-candidate predicates may move to collector module, but cap/dedupe selection policy stays in pipeline orchestration. | prose_only:non_executable_semantic_judgment; code_readback | Cap 80 and `(type,text)` review dedupe remain visible in orchestration or a pipeline-owned selector. | block_severity:BLOCKER | 1 |
| P3 | Offset helpers pure | Sentence span and offset rewrite helpers are moved only after tests pin exact start/end behavior. | prose_only:non_executable_semantic_judgment; unit_test_count | Direct collector tests cover segmented offsets and dedupe by `(type,text,start)`. | block_severity:BLOCKER | 1 |
| P4 | HanLP org suppression preserved | Local organization regex discovery is suppressed whenever supplied HanLP candidates include an organization. | prose_only:non_executable_semantic_judgment; unit_test_count | A fixture with HanLP organization seed produces no duplicate `linear_full_org` or `linear_bare_org_alias` for the same span region. | block_severity:BLOCKER | 1 |
| P5 | No profile overfilter | Collector does not add new profile/sample filtering beyond current behavior; acceptance remains profile-gated where it is today. | prose_only:non_executable_semantic_judgment; code_readback | Profile filtering diff is limited to moved existing logic and tests show existing disabled-category behavior unchanged. | block_severity:BLOCKER | 1 |
| S1 | Fail-closed short-circuit above collector | When sentence extraction errors and `fail_open=False`, pipeline returns regex/base/sample-only fallback without invoking collector or engine. | prose_only:non_executable_semantic_judgment; integration_test_count | Spy test proves `CandidateCollector.collect` and `LinearRuleEngine.discover` are not called in fail-closed short-circuit. | block_severity:BLOCKER | 1 |
| S2 | Web offline fallback stable | MLX unavailable Web `/redact` uses `PipelineConfig.offline_without_llm`, warns, avoids auditor calls, and remains non-blocking. | prose_only:non_executable_semantic_judgment; integration_test_count | Web test asserts warning, successful response, no local LLM audit call, and case persistence behavior unchanged. | block_severity:BLOCKER | 1 |
| S3 | Audit-only entities preserved | Entities surfaced only by `audit_and_verify` survive final wiring and still win as `linear_llm_exact` when applicable. | prose_only:non_executable_semantic_judgment; integration_test_count | Fixture asserts audit-only original appears in mapping with identical source/mask after wiring. | block_severity:BLOCKER | 1 |
| S4 | Calibrate-before-overlap stable | LLM `calibrate` rewrites candidate text/span before overlap resolution. | prose_only:non_executable_semantic_judgment; unit_test_count | Fixture with overlapping calibrated candidate produces identical winning span/source/mask. | block_severity:BLOCKER | 1 |
| N1 | No external contract redesign | Remote API, MCP, case manifest, Discord/Hermes, prompt/model/backend selection are untouched unless regression tests are needed for touched imports. | grep_stdout; diff_readback | Scoped diff confirms no route/schema/model/default changes outside the candidate collection refactor. | HIGH | 1 |
| N2 | No notification surface | Candidate collection refactor introduces no webhook, Discord, Hermes, browser, or network notification path. | grep_stdout | Scoped grep on touched files finds no new external emission calls. | HIGH | 1 |
| CA1 | Reversible commit sequence | Follow the issue #8 staged sequence: tests, inert module, helper moves, collector parity, review wire, engine input, final cutover, deletion, docs. | prose_only:non_executable_semantic_judgment; commit_log | Each commit is green and can be reverted independently; no wiring commit mixes unrelated cleanup. | block_severity:BLOCKER | 1 |
| CA2 | Wiring commits byte-identical | Every wiring commit preserves serialized `RedactionResult.redaction_map` and `redacted_text` for all characterization fixtures. | prose_only:non_executable_semantic_judgment; integration_test_count | Baseline fixtures pass unchanged at commits that wire review prepass, engine input, and final cutover. | block_severity:BLOCKER | 1 |
| CA3 | Temporary path deleted | Any temporary `LinearRuleEngine.collect_candidates` compatibility exists only during the migration window and is deleted before closeout. | prose_only:non_executable_semantic_judgment; grep_stdout | Production callers of `collect_candidates` are zero and no `_legacy`, `_old`, `_compat` wrapper remains. | block_severity:BLOCKER | 1 |
| CA4 | Fact-boundary cleanup deliberate | Duplicate fact-section truncation is treated as no-op cleanup only after parity gates, not as behavior change. | prose_only:non_executable_semantic_judgment; unit_test_count | Fixture containing `本院认为` remains identical before/after any boundary cleanup. | block_severity:BLOCKER | 1 |
| T1 | Offline path characterized | Cover document-order person candidates, title candidates, inline party list, fallback people, china-admin rules, local orgs, same-surname numbering, and org alias. | prose_only:non_executable_semantic_judgment; unit_test_count; integration_test_count | Pipeline-level tests pass and assert externally observable mappings/redacted text, not helper call counts. | block_severity:BLOCKER | 1 |
| T2 | Admin HanLP characterized | Cover admin DB precedence, HanLP enable gate, and HanLP project-suffix conversion using fakes/mocks only. | prose_only:non_executable_semantic_judgment; unit_test_count; integration_test_count | Tests pass without HanLP model download and prove project/工程/小区 suffix conversion parity. | block_severity:BLOCKER | 1 |
| T3 | LLM review characterized | Cover fallback candidates requiring review, partial batch warnings with successful batches, and MLX unavailable Web fallback. | prose_only:non_executable_semantic_judgment; unit_test_count; integration_test_count | Tests assert `review_candidates`, warnings, and non-blocking Web behavior. | block_severity:BLOCKER | 1 |
| T4 | Collector direct tests scoped | Direct collector tests only cover behavior not cleanly observable through pipeline output. | unit_test_count | Direct tests are limited to offset math, dedupe key, HanLP-org suppression, detector concatenation order, and pure predicates. | HIGH | 1 |
| T5 | Focused suite green | Focused tests for touched modules remain green after every commit. | prose_only:non_executable_semantic_judgment; unit_test_count | `.venv/bin/python -m pytest tests/test_linear_engine.py tests/test_sample_integration.py tests/test_postprocess.py tests/test_web_app.py tests/test_china_admin.py tests/test_cases.py tests/test_status.py` passes unless an unrelated environment failure is documented. | block_severity:BLOCKER | 1 |
| T6 | Ruff/LSP clean for touched Python | Touched Python files have no new Ruff or language-server diagnostics. | lint_stdout; lsp_diagnostics | Ruff/LSP diagnostics for touched files are zero new errors. | HIGH | 1 |
| E1 | Architecture docs updated | Docs reflect actual runtime responsibilities after code cutover. | prose_only:non_executable_semantic_judgment; doc_anchor | Docs state durable module roles and no stale `LinearRuleEngine`-as-collector wording remains. | block_severity:BLOCKER | 1 |
| E2 | Planning closeout before PR | `_progress.md` records Gate artifacts, profile, decisions, grep trace, DoD, and next `/ffcs:build candidate-collection-architecture` before first PR push. | prose_only:non_executable_semantic_judgment; doc_anchor | Progress status moves to Spec complete after Gate 0a/0b PASS and all tracked closeout fields are filled. | block_severity:BLOCKER | 1 |
| E3 | Sensitive data safe | Tests/fixtures/docs do not commit raw legal samples, mappings, restored text, prompts, completions, tokens, or local absolute case paths. | prose_only:non_executable_semantic_judgment; grep_stdout; diff_readback | Scoped audit finds no sensitive artifacts in tracked files. | block_severity:BLOCKER | 1 |

## §V · Visual Acceptance Layer

| Field | Value |
|---|---|
| `design_confidence` | `0` |
| `design_autonomy` | `auto` |
| `freedom_level` | `L0` |
| `mutability` | `frozen` |
| `visual_evidence` | `not_required` |
| `visual_capability_status` | `skipped_with_ack` |
| `visual_skip_reason` | `non-visual backend architecture refactor; no UI/game/motion/brand delivery` |

## §2 · Decisions

| # | Decision | Impact | Source | Status |
|---|---|---|---|---|
| candidate-collection-architecture.D-01 | Preserve `RedactionPipeline.redact` public entry | Runtime caller stability | README D-01 | locked |
| candidate-collection-architecture.D-02 | CandidateCollector owns discovery | Module locality | README D-02 | locked |
| candidate-collection-architecture.D-03 | Design B for LLM exact materialization | Resolves collect-once contradiction | README D-03 | locked |
| candidate-collection-architecture.D-04 | Verdicts before overlap stay in engine | Span/order parity | README D-04 | locked |
| candidate-collection-architecture.D-05 | Admin DB stays pipeline span gate | Admin precedence | README D-05 | locked |
| candidate-collection-architecture.D-06 | Preserve china-admin double source | Behavior parity | README D-06 | locked |
| candidate-collection-architecture.D-07 | Review selection cap/dedupe stays orchestration | Avoid collector god-module | README D-07 | locked |
| candidate-collection-architecture.D-08 | Delete unused detector registry | Remove wrong seam | README D-08 | locked |
| candidate-collection-architecture.D-09 | Tests before moves | Legal-redaction quality guard | README D-09 | locked |
| candidate-collection-architecture.D-10 | No legacy compatibility shims | Prevent relapse | README D-10 | locked |
| candidate-collection-architecture.D-11 | Non-visual route | No DESIGN.md | README D-11 | locked |
| candidate-collection-architecture.D-12 | Medium risk, complex size | Gate ceremony and spec set | README D-12 | locked |

### §2 Appendix · Decision Details

| # | rationale | signoff_version | evidence_link |
|---|---|---|
| candidate-collection-architecture.D-01 | Issue #8 names `RedactionPipeline.redact` as the public orchestration interface. | v1.0 | issue #8 lines 31-40 |
| candidate-collection-architecture.D-02 | Discovery/order/offset logic is the poor-locality source and needs one deep module seam. | v1.0 | issue #8 lines 17-23, 31-42 |
| candidate-collection-architecture.D-03 | Audit-derived candidates are discovery products; Design B keeps collection quirks out of the engine. | v1.0 | AdversarialRisk R1/R10 and ImplementationFeasibility delta |
| candidate-collection-architecture.D-04 | Existing engine applies `_apply_llm_verdicts` before `resolve_candidate_overlaps`; changing this changes winners. | v1.0 | `legal_redactor/linear_engine.py` lines 100-107, 239-282 |
| candidate-collection-architecture.D-05 | Admin DB creates mappings and spans before HanLP/china candidates are filtered. | v1.0 | `legal_redactor/pipeline.py` lines 512-565 |
| candidate-collection-architecture.D-06 | Current behavior combines span-filtered seed and rediscovery; cleanup needs separate evidence. | v1.0 | `pipeline.py` lines 534-540; `linear_engine.py` lines 156-163 |
| candidate-collection-architecture.D-07 | Cap and dedupe are review orchestration policy, not candidate discovery. | v1.0 | `legal_redactor/pipeline.py` lines 712-727 |
| candidate-collection-architecture.D-08 | Issue #8 explicitly rejects an unconnected extension point. | v1.0 | issue #8 lines 105-108, 140 |
| candidate-collection-architecture.D-09 | Ordering, offsets, review candidates, and fallback are product behavior. | v1.0 | issue #8 lines 23, 141-143 |
| candidate-collection-architecture.D-10 | User explicitly forbids reintroducing removed legacy paths/aliases. | v1.0 | user directive 2026-07-09 |
| candidate-collection-architecture.D-11 | No visual trigger signal appears in user-visible product scope. | v1.0 | design route score 0 |
| candidate-collection-architecture.D-12 | Work is cross-module and legal-redaction sensitive but does not change external API/permission/money/data migration. | v1.0 | template selector risk matrix |

## §3 · Step Sequence

### Step 0 · POC + Gate 0b

**Time box**: `1 day`

1. E-1: baseline characterization inventory. List existing tests covering same-surname, org alias, admin/china rules, LLM review, Web fallback, postprocess, cases/status.
2. E-2: audit-only candidate feasibility. Create a minimal temporary or test-only POC showing the current final pass materializes `linear_llm_exact` from non-empty audit analysis while review prepass with empty analysis does not.
3. E-3: admin span-gate feasibility. Build a POC fixture for admin DB overlap against HanLP/china-rule candidates and record expected current result.
4. E-4: fail-closed short-circuit feasibility. Record how to spy that collector/engine are not called when sentence extraction errors with `fail_open=False`.
5. E-5: candidate interface smoke. Import the planned inert `CandidateCollectionContext`/`CandidateCollectionResult` shape in a throwaway branch or describe exact import smoke if implementation has not started.
6. Gate 0b reviews the full POC report; implementation stays out of scope until Gate 0b PASS.

### Step 1 · characterization tests before moves

**Time box**: `2 days`
**tier**: `service`

- Add tests for offline linear path via `RedactionPipeline.redact`.
- Add tests for admin/HanLP injection with faked HanLP.
- Add tests for LLM review candidate behavior, partial failures, and Web offline fallback.
- Capture RED-first output for newly added tests where behavior is not already present.

### Step 2 · inert collector module and pure helpers

**Time box**: `1 day`
**tier**: `service`

- Add `legal_redactor/candidate_collector.py` with context/result/collector skeleton.
- Move only pure helpers: project conversion and review-eligibility predicates.
- Do not wire runtime yet.
- Do not expose a detector registration surface.

### Step 3 · collector parity implementation

**Time box**: `2 days`
**tier**: `service`

- Implement collector parity for non-primary and LLM-primary collection.
- Port sentence spans, offset rewrite, local org discovery, LLM exact candidate materialization, and dedupe.
- Direct tests cover only unobservable collector mechanics.
- Pipeline and engine runtime path remains unchanged until parity tests pass.

### Step 4 · review prepass wiring

**Time box**: `1 day`
**tier**: `service`

- Wire only the review-candidate prepass to the collector with empty analysis.
- Final `LinearRuleEngine.discover` still uses old internal collection.
- Assert `review_candidates` are identical for characterization fixtures.

### Step 5 · engine pre-collected candidate input

**Time box**: `1.5 days`
**tier**: `service`

- Add acceptance interface that takes pre-collected candidates plus analysis.
- Keep old internal collection only temporarily for direct tests during this step.
- Verify mapping output remains unchanged.

### Step 6 · final collector cutover

**Time box**: `1 day`
**tier**: `service`

- Use Design B: collect through collector with empty analysis for review selection, run audit when applicable, then collect through collector with audited analysis for final candidate set.
- Pass final ordered candidates plus analysis to engine acceptance.
- Preserve audit-only `linear_llm_exact` and calibrate-before-overlap invariants.
- Remove duplicate runtime `engine.collect_candidates` call.

### Step 7 · delete old seams and docs closeout

**Time box**: `1.5 days`
**tier**: `service`

- Delete temporary old internal collection path once production callers are gone.
- Delete or privately absorb `detector_registry`; no public registry remains.
- Rename remaining collection/review/acceptance names for locality.
- Update architecture docs.
- Run focused suite and touched-file Ruff/LSP checks.

### Step 8 · Gate 2 and delivery

**Time box**: `1 day`
**tier**: `service`

- Run focused regression suite.
- Run `milestone-doc-check.mjs --gate2` and tracked closeout.
- Run `/ffcs:review-repair --scope=build` for Gate 2.
- Before first PR push, update `_progress.md` closeout and planning docs.

## §4 · Time Box

| Step | Estimate | Commit window | Notes |
|---|---:|---|---|
| Step 0 · POC + Gate 0b | 1 day | docs only | spec accepted before implementation |
| Step 1 · characterization tests | 2 days | commits 1-3 | tests-only |
| Step 2 · inert module/helpers | 1 day | commits 4-5 | no runtime wiring |
| Step 3 · collector parity | 2 days | commit 6 | direct collector tests only for unobservables |
| Step 4 · review prepass wiring | 1 day | commit 7 | final engine unchanged |
| Step 5 · engine pre-collected input | 1.5 days | commit 8 | temporary dual path |
| Step 6 · final collector cutover | 1 day | commits 9a/9b | Design B through one module seam |
| Step 7 · delete old seams/docs | 1.5 days | commits 10-13 | no aliases |
| Step 8 · Gate 2/delivery | 1 day | commit 14-15 | focused suite and review |
| **Total** | **8-12 days** | | Complex |

## §5 · Cross-Module Signoff

| Change | Downstream impact | Decision | owner_signoffs | Test coverage |
|---|---|---|---|---|
| `CandidateCollector` discovery seam | Pipeline, engine, LLM review, tests | D-02, D-03 | project-local owner accepted by issue #8 and Gate 0a | collector parity + pipeline characterization |
| Engine acceptance interface | Direct engine tests and pipeline runtime | D-04, D-07 | project-local owner accepted by Gate 0a | engine acceptance and pipeline byte-identical tests |
| Admin DB span gate unchanged | Admin/china/HanLP redaction quality | D-05, D-06 | project-local owner accepted by Gate 0a | admin/HanLP overlap tests |
| Detector registry deletion | Tests/imports that referenced unused seam | D-08 | project-local owner accepted by Gate 0a | grep zero + focused suite |
| Docs responsibility update | Future maintainers | D-10 | project-local owner accepted by Gate 2 | doc readback |

No external API, DB schema, event, field, permission, or cross-service owner
signoff is required. The changed interface is internal Python module shape.

## §6 · Server-Authoritative Recompute

This milestone does not expose a client-supplied decision, pricing, permission,
role, status, policy, threshold, ownership, routing, or eligibility field over an
HTTP/RPC boundary. It changes internal discovery/acceptance locality. The
service-authoritative recompute hard gates from `authoritative-recompute.md` are
not injected.

## §7 · Documentation Sweep

- [ ] README/module docs state `CandidateCollector` owns discovery/order.
- [ ] `docs/LINEAR_REFACTOR.md` no longer says `LinearRuleEngine` is the center of candidate discovery after the cutover.
- [ ] `_progress.md` records Gate artifacts, grep trace, profile, design route, D-XX, and next `/ffcs:build candidate-collection-architecture`.
- [ ] HUMAN_TASKS contains only review signoff, not AI-self-decided design knobs.
- [ ] Step 0 POC report records PASS/fallback evidence.
- [ ] No `DESIGN.md` is required because this is non-visual backend architecture work.

## §8 · Exit Checklist

- [ ] Spec set is complete.
- [ ] POC E-1 through E-5 pass or fallback is recorded.
- [ ] Characterization tests are in place before production discovery moves.
- [ ] All D/P/S/N/C+A/T/E gates have evidence.
- [ ] Focused suite passes.
- [ ] Ruff/LSP for touched Python files has no new errors.
- [ ] `milestone-doc-check.mjs --gate2` passes.
- [ ] Gate 2 review passes with required artifacts.
- [ ] `_progress.md` §1 is `✅ 完成`; §3 Gate 2 and §8 DoD are closed before first PR push.
- [ ] PR checks are green if GitHub delivery is in scope.
