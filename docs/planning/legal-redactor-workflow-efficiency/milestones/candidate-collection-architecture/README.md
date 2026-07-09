---
milestone: candidate-collection-architecture
module: candidate-collector
version: v1.0
created: 2026-07-09
status: Spec complete · Gate 0a PASS · Gate 0b pending
complexity: complex
risk: medium
time_box: 8-12 days
requires: [issue-8]
blocks: []
source: GitHub issue #8
validation_profile: standard
effective_profile: standard
---

# candidate-collection-architecture · candidate-collector · module door

> **Status**: `Spec complete · Gate 0a PASS · Gate 0b pending`
> **Basis**: GitHub issue #8, [../../REQUIREMENTS.md](../../REQUIREMENTS.md), [../../READINESS.md](../../READINESS.md), [../../../../LINEAR_REFACTOR.md](../../../../LINEAR_REFACTOR.md), [../../../../../CLAUDE.md](../../../../../CLAUDE.md)
> **Complexity**: `complex`
> **Risk**: `medium`
> **Time box**: `8-12 days`
> **Design route**: `non-visual · design_confidence=0 · skipped_with_ack`

---

## 1. Basis

- GitHub issue #8 is the source plan for this milestone.
- Current runtime has removed legacy strategy branching, detector/filter aliases,
  pipeline postprocess re-exports, Browser `/api/save-to-local`, and the pruned
  `PipelineConfig` fields. This milestone must not reintroduce them.
- Current architecture still spreads candidate discovery across
  `RedactionPipeline`, `LinearRuleEngine.collect_candidates`, LLM review
  prepasses, admin/HanLP preprocessing, and the unused `detector_registry` seam.
- Focused relevant suite was reported as `165 passed, 10 subtests`; this spec
  still requires fresh characterization evidence before any runtime wiring.

## 2. Goal

Introduce a deep `CandidateCollector` module that owns candidate discovery and
ordering behind a small interface, while preserving external redaction behavior
byte-for-byte during the migration.

Target responsibilities after the refactor:

- `RedactionPipeline`: public orchestration. It keeps `redact`, `redact_many`,
  mapping application, leak scanning, sample/base mapping seeding, admin DB
  pre-accepted mappings, LLM review orchestration, and final `RedactionResult`.
- `CandidateCollector`: discovery module. It owns detector imports, sentence
  segmentation, offset rewriting, rule/HanLP/china-admin candidate ordering,
  LLM exact candidate materialization, dedupe, and review-eligibility predicates.
- `LinearRuleEngine`: acceptance/expansion module. It takes ordered candidates
  plus LLM analysis context, applies reject/calibrate verdicts before overlap
  resolution, confirms entities, and emits deterministic mappings.
- `LegalEntityAuditor`: LLM prompt/orchestration module. Transport/model cleanup
  is explicitly out of scope.
- `postprocess`: fixed mapping cleanup/merge module. It remains separate.

## 3. Scope

### 3.1 In Scope

- Add characterization tests before moving production discovery logic.
- Add `legal_redactor/candidate_collector.py` with inert types first, then move
  discovery-only helpers and implement parity collection.
- Choose Design B for the LLM ownership contradiction: `CandidateCollector.collect`
  accepts `llm_analysis`; non-primary review mode may call the collector twice
  through the same module seam, once with empty analysis for review selection and
  once with audited analysis for final candidate materialization.
- Keep admin DB detections as pipeline-owned pre-accepted mappings plus
  `admin_spans`, not collector candidates.
- Preserve the current china-admin double-source behavior until parity evidence
  supports a later cleanup.
- Wire review-candidate prepass first, then engine pre-collected candidate input,
  then final pipeline cutover, then delete the old internal collection path and
  unused `detector_registry`.
- Update durable architecture docs after runtime responsibilities match the new
  module shape.

### 3.2 Out of Scope

- No prompt redesign.
- No model switch.
- No change to fixed MLX Qwen3.5 9B default.
- No Ollama or multi-backend LLM adapter refactor.
- No remote API, MCP, case manifest, or UI redesign unless a touched boundary
  needs a regression test.
- No recognition-quality tuning unrelated to moving seams.
- No legacy strategy, compatibility aliases, detector/filter aliases, pipeline
  postprocess re-exports, Browser `/api/save-to-local`, or pruned
  `PipelineConfig` restoration.
- No public detector plugin/registry seam.

### 3.3 Key Deliverables

| # | Path | Type | Notes |
|---|---|---|---|
| 1 | `tests/test_linear_engine.py` or focused pipeline tests | tests | Offline linear characterization, order, alias, admin, LLM review invariants |
| 2 | `tests/test_china_admin.py`, `tests/test_web_app.py`, related focused tests | tests | Admin/HanLP/Web fallback invariants |
| 3 | `legal_redactor/candidate_collector.py` | code | New discovery module and data types |
| 4 | `legal_redactor/pipeline.py` | code | Orchestration cutover and review selection |
| 5 | `legal_redactor/linear_engine.py` | code | Acceptance-only interface; old collection deleted |
| 6 | `legal_redactor/detector_registry.py` and tests | code deletion | Delete or absorb privately; no unused extension point remains |
| 7 | `docs/LINEAR_REFACTOR.md` and README if needed | docs | Durable module responsibility update |
| 8 | `docs/planning/legal-redactor-workflow-efficiency/milestones/candidate-collection-architecture/*` | planning | This FFCS spec set and Gate evidence |

## 4. Decisions

| # | Decision | Rationale | Signoff | Evidence |
|---|---|---|---|---|
| D-01 | `RedactionPipeline.redact` remains public entry | Issue #8 makes orchestration the stable public module interface. | v1.0 | issue #8 lines 31-40 |
| D-02 | `CandidateCollector` owns discovery | Discovery/order/offset quirks need locality behind one module seam. | v1.0 | issue #8 lines 31, 39, 135 |
| D-03 | Design B resolves LLM ownership | Audit-derived `linear_llm_exact` candidates are discovery artifacts; keeping them in engine would leave collection quirks there. | v1.0 | AdversarialRisk R1/R10, ImplementationFeasibility delta |
| D-04 | Engine keeps verdicts before overlap | Reject/calibrate changes candidate spans and must precede overlap resolution before acceptance. | v1.0 | `legal_redactor/linear_engine.py` lines 100-107, 239-282 |
| D-05 | Admin DB remains pipeline span gate | Admin DB currently pre-accepts mappings and gates HanLP/china rules; collector candidates would change precedence. | v1.0 | `legal_redactor/pipeline.py` lines 512-565 |
| D-06 | China-admin double-source preserved | The filtered pipeline seed plus engine full-text redetect is current behavior; unifying it is product change. | v1.0 | `pipeline.py` lines 534-540 and `linear_engine.py` lines 156-163 |
| D-07 | Review selection stays orchestration-owned | Cap-80 and dedupe by `(type,text)` are review policy; collector module may expose pure predicates only. | v1.0 | `pipeline.py` lines 712-727 |
| D-08 | `detector_registry` deleted, not wired | A tested unused extension point is the attractive wrong seam identified by issue #8. | v1.0 | issue #8 lines 20, 105-108, 140 |
| D-09 | Characterization before moves | Ordering, offsets, review candidates, and fallback behavior are product behavior. | v1.0 | issue #8 lines 46-63, 141-143 |
| D-10 | No legacy compatibility shims | Current state explicitly removed legacy strategy and aliases; this milestone must not restore them. | v1.0 | user directive and issue #8 lines 13, 139 |
| D-11 | Non-visual route | This is backend architecture/process work; no UI/game/motion/brand deliverable. | v1.0 | design confidence route, score 0 |
| D-12 | Medium risk, complex size | Legal entity leaks are high-impact, but no money/permission/data migration/API contract redesign is introduced. | v1.0 | selector matrix + issue #8 scope |

## 5. CandidateCollector Interface Contract

The planned seam is deliberately small:

```python
@dataclass(frozen=True)
class CandidateCollectionContext:
    text: str
    profile: RedactionProfile
    sample_blacklist: set[str]
    seed_candidates: list[Candidate]          # span-filtered china rules, heuristic locations, HanLP candidates
    llm_analysis: dict[str, Any]
    llm_primary_discovery: bool
    use_semantic_rules: bool
    use_china_admin_rules: bool

@dataclass(frozen=True)
class CandidateCollectionResult:
    candidates: list[Candidate]               # post-dedupe, pre-verdict, pre-overlap

class CandidateCollector:
    def collect(self, context: CandidateCollectionContext) -> CandidateCollectionResult: ...
```

Important interface facts:

- Admin DB accepted mappings and `admin_spans` stay outside this context.
- `seed_candidates` combines only candidates that already survived pipeline
  span/profile/sample gating: span-filtered china-admin rules, heuristic
  locations, and HanLP candidates.
- LLM exact candidate materialization belongs to `CandidateCollector` because it
  is source discovery with offset/single-occurrence/window logic.
- LLM reject/calibrate verdict application remains in `LinearRuleEngine` because
  it transforms the acceptance candidate set before overlap resolution.
- Review selection is pipeline-owned; pure predicates may live in
  `candidate_collector.py` for locality, but cap/dedupe policy remains with the
  orchestrator.

## 6. Acceptance Direction

- Every wiring commit must preserve serialized `RedactionResult.redaction_map`
  and `redacted_text` for the characterization suite.
- Audit-derived entities, calibrate span rewrites, admin precedence,
  HanLP-suppression, fail-open/fail-closed LLM behavior, review-candidate
  selection, same-surname numbering, and organization alias masks are blocking
  parity contracts.
- Implementation is not authorized until Gate 0a accepts this spec and Gate 0b
  accepts the Step 0 POC evidence.

## 7. Primary Surfaces

- `legal_redactor/pipeline.py`
- `legal_redactor/linear_engine.py`
- `legal_redactor/candidate_resolution.py`
- `legal_redactor/llm.py`
- `legal_redactor/detector_registry.py`
- `legal_redactor/detectors.py`
- `legal_redactor/china_admin_rules.py`
- `legal_redactor/admin_division.py`
- `legal_redactor/hebei_admin.py`
- `tests/test_linear_engine.py`
- `tests/test_sample_integration.py`
- `tests/test_china_admin.py`
- `tests/test_web_app.py`
- `tests/test_postprocess.py`
- `tests/test_cases.py`
- `tests/test_status.py`
- `docs/LINEAR_REFACTOR.md`
