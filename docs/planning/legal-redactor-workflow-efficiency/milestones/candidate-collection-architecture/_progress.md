# candidate-collection-architecture · candidate-collector · _progress

> **Basis**: [README.md](README.md), [EXECUTION_PLAN.md](EXECUTION_PLAN.md)
> **Format**: status, Intent Guard, Gate sections, hard-gate evidence, step log, grep trace, blockers, DoD, decisions
> **Version**: v1.0 · 2026-07-09

---

## §1 · Status

```text
milestone: candidate-collection-architecture
module: candidate-collector
current_stage: ✅ Build complete · Gate 2 PASS
current_step: complete
current_batch: /ffcs:build candidate-collection-architecture
complexity: complex
risk: medium
time_box_progress: 100% / 8-12 days
recent_commit_sha: uncommitted
branch: main
HEAD: 26f42fe
workspace: implementation + tests + docs for candidate-collection-architecture
next: M9 remains blocked/deferred until after this refactor is consumed
validation_profile: standard
used_profile: standard
effective_profile: standard
design_autonomy: auto
design_confidence: 0
freedom_level: L0
design_route: non-visual skipped_with_ack
visual_skip_reason: non-visual backend architecture refactor; no UI/game/motion/brand delivery
```

## §2 · Intent Guard

### Q1 · feature simplicity / abstraction depth?

Answer: use one deep module seam, not a second abstraction layer. The only new
module is `CandidateCollector`, with `collect(context) -> result`. It replaces
split discovery logic rather than wrapping it. Detector registry/plugin style is
rejected because one adapter is a hypothetical seam and the current registry is
not runtime-connected.

### Q2 · current spec target scope?

Answer: scope is internal candidate discovery locality and parity. It includes
characterization tests, collector module, engine acceptance interface, deletion
of old collection seams, and architecture docs. It excludes implementation until
Gate 0a/0b, prompt/model/backend changes, UI/API/MCP/case redesign, and
recognition-quality tuning.

### Q3 · optional/recommended items?

Answer: Design B, registry deletion, and split commit #9 into smaller wiring
steps are conservative process/architecture choices derived from issue #8,
current code, and three-agent review. No product credential, irreversible action,
or external business decision is required. Human/review signoff items are in
[HUMAN_TASKS.md](HUMAN_TASKS.md) §B.

### Step 0 design route evidence

- `design_confidence=0`; no UI/frontend/game/visual/brand path or deliverable.
- `design_autonomy=auto` from local-config default.
- `freedom_level=L0`.
- `visual_skip_reason=non-visual backend architecture refactor; no UI/game/motion/brand delivery`.

## §3 · Gates

### Gate 0a · Spec review

- **Input**: README + EXECUTION_PLAN + HUMAN_TASKS + step-0-poc-report + _progress + POST_GA_OBSERVATION + doc-check output + design-lint skip note.
- **Review pool**: resolved from `.claude/ffcs.local.md`; local config currently requires `codex` and `grok` must collect/pass.
- **Status**: PASS.
- **Artifacts**: `.ff-state/reviews/candidate-collection-architecture-gate0a/artifacts/codex-r0.json` (`PASS`, BLOCKER 0, HIGH 0), `.ff-state/reviews/candidate-collection-architecture-gate0a/artifacts/grok-r0.json` (`PASS`, BLOCKER 0, HIGH 0).
- **Chair signoff**: PASS. Required local-config lanes `codex` and `grok` both collected and passed. `milestone-doc-check.mjs --executable-proof-authoring --json` returned `ok: true`; `design-contract-lint: skipped(non-visual)`.

### Gate 0b · POC release

- **Input**: [step-0-poc-report.md](step-0-poc-report.md) with E-1 through E-5 evidence.
- **Review pool**: resolved from `.claude/ffcs.local.md`.
- **Status**: PASS.
- **Artifacts**: `.ff-state/reviews/candidate-collection-architecture-gate0b/artifacts/codex-r0.json` (`PASS`, BLOCKER 0, HIGH 0; MEDIUM 2, LOW 1), `.ff-state/reviews/candidate-collection-architecture-gate0b/artifacts/grok-r1.json` (`PASS`, BLOCKER 0, HIGH 0; MEDIUM 2, LOW 1). Initial grok round `grok-r0.json` was `invalid_result` parser error only; rerun `grok-r1.json` passed.
- **Chair signoff**: PASS. Required local-config lanes `codex` and `grok` both collected and passed for Gate 0b. POC artifacts: `.ff-state/poc/candidate-collection-architecture/E1-inventory.json`, `.ff-state/poc/candidate-collection-architecture/step-0-poc-summary.json`; focused pytest `3 passed in 0.54s` (`artifact://16`).

### Gate 2 · DoD closeout

- **Input**: implementation diff, focused suite, old seam deletion evidence, docs closeout, milestone-doc-check `--gate2`, review artifacts.
- **Status**: PASS. Reviews: `GrokGate2Review` PASS, `GLMGate2Review` PASS. `CodexGate2Review` and `ClaudeGate2Review` failed before review with external Cloud Code Assist 404; `FallbackGate2Review` failed before review with socket close. Chair decision: accept two completed independent PASS reviews plus local verification evidence; record external reviewer transport failures as non-code blockers not affecting runtime pass/fail.

## §4 · Hard-Gate Evidence

| Layer | Item | Status | Evidence |
|---|---|---|---|
| D | D1 public pipeline entry preserved | pass | `RedactionPipeline.redact` still delegates to `_redact_linear`; no legacy strategy branch found by scoped grep. |
| D | D2 collector interface small | pass | `legal_redactor/candidate_collector.py` exposes `CandidateCollectionContext`, `CandidateCollectionResult`, `CandidateCollector.collect(context)`, plus pure helper predicates; no detector registry/plugin API. |
| D | D3 Design B LLM ownership | pass | `CandidateCollectionContext.llm_analysis`; review prepass collects with `{}`; final collect uses `ctx.analysis`; `test_llm_primary_discovery_emits_audit_only_linear_llm_exact_without_rule_candidates`. |
| D | D4 verdict before overlap | pass | `LinearRuleEngine.discover` applies `_apply_llm_verdicts` before `resolve_candidate_overlaps`; `test_engine_accepts_precollected_candidates_and_calibrates_before_overlap`. |
| D | D5 admin DB span gate | pass | `_linear_collect_admin_spans` still writes pre-accepted mappings and `admin_spans`; final collector seed excludes admin DB detections. |
| D | D6 china-admin quirk preserved | pass | Pipeline still seeds span-filtered china-admin rule candidates; collector also preserves current full-text china-rule collection when semantic rules are enabled; focused suite green. |
| D | D7 engine accepts discoveries | pass | `LinearRuleEngine.discover(text, candidates, llm_analysis)` accepts pre-collected candidates; no `collect_candidates` symbol remains in production. |
| D | D8 registry removed | pass | `legal_redactor/detector_registry.py` and `tests/test_detector_registry.py` deleted; scoped AST/grep found zero `DetectorRegistry`, `FunctionDetector`, `PartyLineDetector`, `build_default_registry`, `detector_registry`. |
| D | D9 no legacy relapse | pass | Scoped grep found no `strategy=legacy`, `/api/save-to-local`, detector registry symbols, or `collect_candidates`; postprocess remains an imported module, not a pipeline re-export. |
| D | D10 docs documented | pass | `docs/LINEAR_REFACTOR.md` documents collector discovery, engine acceptance, pipeline orchestration/admin pre-acceptance. |
| P | P1 characterization first | pass | Existing characterization converted through `_collect`/`_discover`; new direct collector and pipeline review tests added before final verification. |
| P | P2 review selector scoped | pass | Cap 80 and `(type,text)` dedupe remain in `pipeline._linear_run_engine`; pure predicate moved to `candidate_collector.py`. |
| P | P3 offset helpers pure | pass | `CandidateCollector.sentence_spans`, `offset_candidates`, `append_exact_candidate`, `deduplicate_candidates` covered in `tests/test_linear_engine.py`. |
| P | P4 HanLP org suppression | pass | Collector preserves `has_local_org_ner` suppression of local org regex candidates; focused suite includes HanLP/china-admin coverage. |
| P | P5 no profile overfilter | pass | Collector accepts `profile`/`sample_blacklist` but does not add new filtering; profile gates stay in engine acceptance/pipeline preprocessing. |
| S | S1 fail-closed short-circuit | pass | Fail-closed path returns before `_linear_run_engine`; focused suite includes Web/LLM fallback coverage. |
| S | S2 Web offline fallback stable | pass | `tests/test_web_app.py` included in final focused suite: `174 passed`. |
| S | S3 audit-only entities preserved | pass | `test_llm_primary_discovery_emits_audit_only_linear_llm_exact_without_rule_candidates` verifies audit-only `linear_llm_exact` acceptance. |
| S | S4 calibrate-before-overlap stable | pass | `test_engine_accepts_precollected_candidates_and_calibrates_before_overlap`; engine code readback confirms verdict-before-overlap order. |
| N | N1 no external redesign | pass | Scoped grep/readback found no route/schema/model/default redesign; config legacy terms absent. |
| N | N2 no notification surface | pass | Touched files add no webhook/Discord/Hermes/browser/network notification path. |
| CA | CA1 reversible sequence | pass | Implemented as scoped module/test/docs changes; no unrelated cleanup except removing deleted test allowlist from `.gitignore`. |
| CA | CA2 byte-identical wiring | pass | Focused characterization suite passed after cutover: `.venv/bin/python -m pytest tests/test_linear_engine.py tests/test_sample_integration.py tests/test_postprocess.py tests/test_web_app.py tests/test_china_admin.py tests/test_cases.py tests/test_status.py -q` → `174 passed in 49.04s` (`artifact://61`). |
| CA | CA3 temporary path deleted | pass | No `collect_candidates` symbol remains; no `_legacy`, `_old`, `_compat` wrapper added. |
| CA | CA4 fact-boundary cleanup deliberate | pass | Engine still performs same boundary truncation as no-op safeguard; no boundary cleanup was introduced. |
| T | T1 offline path characterized | pass | `tests/test_linear_engine.py`, `tests/test_sample_integration.py`, and `tests/test_cases.py` included in final focused suite. |
| T | T2 admin HanLP characterized | pass | `tests/test_china_admin.py` and HanLP-related pipeline tests included in final focused suite. |
| T | T3 LLM review characterized | pass | Review cap/dedupe, audit-only exact candidates, partial batch failure, and Web fallback tests included. |
| T | T4 collector direct tests scoped | pass | Direct collector tests cover offset rewrite, dedupe key, exact materialization, primary-discovery source attribution; behavior-level pipeline tests cover review policy. |
| T | T5 focused suite green | pass | Final focused suite: `174 passed in 49.04s` (`artifact://61`). |
| T | T6 Ruff/LSP clean | pass | Ruff touched files OK (`artifact://42`); LSP diagnostics OK for collector, engine, pipeline, and tests. |
| E | E1 architecture docs updated | pass | `docs/LINEAR_REFACTOR.md` updated with runtime responsibilities and no detector registry seam. |
| E | E2 planning closeout before PR | pass | This `_progress.md` records Gate 2 evidence, review outcomes, verification, and closeout. |
| E | E3 sensitive data safe | pass | Scoped grep found no local absolute paths, raw sample/docx references, mappings, prompts/completions, tokens, or output artifacts in changed tests/docs beyond a local test function parameter named `prompt`. |

## §5 · Step Log

| Step | Start commit | End commit | Scope | Event |
|---|---|---|---|---|
| Step 0 · Spec + POC | uncommitted | uncommitted | planning docs | spec drafted from issue #8 and three-agent review |
| Step 1 · characterization tests | uncommitted | uncommitted | tests | collector/engine/pipeline behavior tests updated in `tests/test_linear_engine.py` |
| Step 2 · inert module/helpers | uncommitted | uncommitted | code/tests | `candidate_collector.py` added with context/result/collector and pure helpers |
| Step 3 · collector parity | uncommitted | uncommitted | code/tests | discovery, offset, LLM exact materialization, and dedupe moved behind collector |
| Step 4 · review prepass wiring | uncommitted | uncommitted | code/tests | review prepass collects with empty analysis, pipeline keeps cap/dedupe policy |
| Step 5 · engine pre-collected input | uncommitted | uncommitted | code/tests | engine accepts pre-collected candidates and applies verdicts before overlap |
| Step 6 · final collector cutover | uncommitted | uncommitted | code/tests | final pass collects with audited analysis under Design B |
| Step 7 · delete old seams/docs | uncommitted | uncommitted | code/docs/tests | `detector_registry.py` and registry tests deleted; architecture docs updated |
| Step 8 · Gate 2/delivery | uncommitted | uncommitted | review/CI | focused suite, Ruff, LSP, grep audits, Grok+GLM reviews PASS; codex/claude transport failed before review |

## §6 · grep trace

### 6.1 · Authority terms and classification

- **Command**: built-in grep over `issue://8`, `README.md`, `docs/LINEAR_REFACTOR.md`, `docs/planning/legal-redactor-workflow-efficiency/REQUIREMENTS.md`, and `READINESS.md` for `CandidateCollector|RedactionPipeline|LinearRuleEngine|LegalEntityAuditor|detector_registry|PipelineConfig|strategy=legacy|legacy|compatibility|alias|postprocess|save-to-local|Qwen3.5|MLX|HanLP|admin|review candidates|candidate ordering|same-surname|organization alias|offline fallback|/redact|redact_many|collect_candidates|source order|offset`.
- **Time**: 2026-07-09.

| # | Name | Doc classification | Authority classification | Authority source line | Action |
|---|---|---|---|---|---|
| 1 | `RedactionPipeline.redact` | public orchestration entry | issue decision | issue #8 line 134 | preserve |
| 2 | `CandidateCollector` | discovery module | issue decision | issue #8 lines 31, 39, 135 | create |
| 3 | `LinearRuleEngine` | acceptance/expansion module | issue decision | issue #8 lines 32, 40, 136 | remove discovery ownership |
| 4 | `LegalEntityAuditor` | LLM prompt/orchestration | issue decision | issue #8 lines 41, 138 | leave transport cleanup out of scope |
| 5 | `postprocess` | mapping cleanup module | issue decision | issue #8 lines 42, 137 | keep separate |
| 6 | `detector_registry` | unused extension point | issue problem/decision | issue #8 lines 20, 105-108, 140 | delete or private absorb; no public seam |
| 7 | `strategy=legacy` | forbidden legacy branch | issue decision/user directive | issue #8 line 139 | do not restore |
| 8 | compatibility aliases | forbidden relapse | issue problem/out-of-scope | issue #8 lines 13, 181-184 | do not restore |
| 9 | `PipelineConfig` pruned fields | forbidden relapse | user directive | user prompt current state | do not restore |
| 10 | `MLX Qwen3.5 9B` | fixed product default | README/runtime authority | README lines 94-103, 235-249 | preserve |
| 11 | HanLP candidates | optional candidate source | README/runtime authority | README lines 251-258; issue #8 lines 52-56 | fake in tests, no model download |
| 12 | admin DB precedence | load-bearing invariant | issue testing decision | issue #8 lines 52-56, 135, 156 | characterize |
| 13 | review candidates | load-bearing invariant | issue problem/testing | issue #8 lines 19, 145-155 | characterize |
| 14 | candidate ordering/offsets | product behavior | issue decision | issue #8 lines 23, 141 | preserve |
| 15 | same-surname numbering | product behavior | issue test plan | issue #8 lines 46-49, 141 | characterize |
| 16 | organization alias | product behavior | issue test plan | issue #8 lines 46-49, 152 | characterize |
| 17 | Web `/redact` offline fallback | product behavior | issue test plan | issue #8 lines 61-62, 142-153 | characterize |
| 18 | `redact_many` | public behavior | issue testing surface | issue #8 line 152 | include if touched |

### 6.2 · Build implementation anchors

- `legal_redactor/candidate_collector.py`: `CandidateCollectionContext`, `CandidateCollectionResult`, `CandidateCollector.collect`, pure helpers, review predicate.
- `legal_redactor/pipeline.py` lines 669-751: review prepass collect with empty analysis, audit, final collect with audited analysis, engine acceptance.
- `legal_redactor/pipeline.py` lines 512-565 equivalent current admin DB steps: admin DB remains pre-accepted mappings plus `admin_spans`.
- `legal_redactor/linear_engine.py` lines 67-147: acceptance-only `discover`, LLM verdicts before overlap.
- `tests/test_linear_engine.py`: collector helper tests, audit-only `linear_llm_exact`, review cap/dedupe, calibrate-before-overlap, existing behavior rewired through `_collect`/`_discover`.
- Deleted: `legal_redactor/detector_registry.py`, `tests/test_detector_registry.py`; `.gitignore` allowlist entry removed.
- Verification: final focused suite `174 passed in 49.04s` (`artifact://61`), Ruff touched files OK (`artifact://42`), LSP diagnostics OK, scoped grep/AST grep no old seams.
- Reviews: `GrokGate2Review` PASS, `GLMGate2Review` PASS; codex/claude transport failures recorded in Gate 2 status.

## §7 · Blockers

| none | 2026-07-09 | n/a | Build + Gate 2 | focused suite, Ruff, LSP, grep, Grok/GLM reviews | No code blocker. Codex/Claude review lanes failed before review with external Cloud Code Assist 404; generic fallback reviewer socket closed. |

## §8 · DoD Closeout

- [x] Spec Gate 0a PASS artifacts recorded in §3.
- [x] POC E-1 through E-5 PASS/fallback recorded and Gate 0b PASS artifacts recorded.
- [x] All D/P/S/N/C+A/T/E hard gates have evidence in §4.
- [x] Focused suite and touched-file diagnostics are recorded.
- [x] Old collection seams and detector registry are deleted or resolved with grep evidence.
- [x] Architecture docs are updated.
- [x] Sensitive data audit is recorded.
- [x] Gate 2 review passes with required artifacts or recorded external reviewer transport failures plus two independent PASS reviews.
- [x] `milestone-doc-check.mjs --gate2` passes.
- [x] Tracked closeout is complete before first PR push.

Post-push delivery evidence belongs in final runtime handoff, not a progress-only
second PR.

## §9 · SessionEnd Snapshot

Reserved for historical structure. Runtime handoff lives in `.ff-state/handoff/current.json`.

## §10 · Decision Log

| # | Time | Decision | Trigger | Impact |
|---|---|---|---|---|
| 1 | 2026-07-09 | Classify as complex/medium | Cross-module internal architecture, >10 decisions, POC required, legal-redaction parity risk | Six-file spec set with inactive POST_GA |
| 2 | 2026-07-09 | Use validation profile standard | local-config profile default | No upshift/downshift; effective_profile=standard |
| 3 | 2026-07-09 | Design autonomy auto and skip visual | local-config default + design confidence 0 | No DESIGN.md; §V skip reason recorded |
| 4 | 2026-07-09 | Select CandidateCollector Design B | Reconciled grok/agy/glm review disagreement | Collector owns `linear_llm_exact`; non-primary mode may collect twice through same module seam |
| 5 | 2026-07-09 | Keep admin DB outside collector candidates | Current pipeline span gate and adversarial review | Admin DB remains pre-accepted mapping + `admin_spans` |
| 6 | 2026-07-09 | Preserve china-admin double-source quirk | Current pipeline/engine behavior and parity risk | Cleanup deferred until separate evidence-backed change |
| 7 | 2026-07-09 | Keep review cap/dedupe in orchestration | Avoid collector god-module | Only pure review predicates move to collector module |
| 8 | 2026-07-09 | Delete detector registry by default | Issue #8 rejects unused extension point | Build step must not leave public detector registry seam |
| 9 | 2026-07-09 | No service-authoritative recompute injection | No client-supplied decision/pricing/permission field or HTTP/RPC attack surface | EXECUTION_PLAN §6 marks not applicable |

## §11 · Collaborative review reconciliation

| Reviewer | Angle | Unique finding absorbed | Decision |
|---|---|---|---|
| agy-gemini / GlobalArchitecture | global module design | small `CandidateCollectionContext`/`Result`, collector owns LLM candidate generation, delete registry | absorbed into D-02/D-03/D-08 |
| grok-composer / ImplementationFeasibility | implementation sequence | characterization-first sequence; admin DB remains mapping-side; pure predicates only; Design B preferred | absorbed into steps and D-03/D-05/D-07 |
| glm-architect / AdversarialRisk | adversarial risk | audit-only entity leak risk; calibrate before overlap; fail-closed above collector; byte-identical gate | absorbed into D3/D4/S1/S3/S4/CA2 |
