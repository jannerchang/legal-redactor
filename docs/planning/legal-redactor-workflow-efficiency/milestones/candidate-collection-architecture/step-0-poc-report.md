# candidate-collection-architecture · candidate-collector · Step 0 POC Report

> **Basis**: [README.md](README.md), [EXECUTION_PLAN.md](EXECUTION_PLAN.md) §3 Step 0
> **Status**: `POC complete · Gate 0b PASS`
> **Constraint**: implementation remains out of scope until Gate 0b signs off.
> **Version**: v1.0 · 2026-07-09

---

## 1. POC Scope

| # | POC | Signoff condition | Source | Fallback if failed |
|---|---|---|---|---|
| E-1 | Baseline characterization inventory | Required | issue #8 testing decisions | Add missing characterization tests before code moves |
| E-2 | Audit-only entity materialization | Required | AdversarialRisk R1/G1 | Keep a second collector final pass; revise Design B if impossible |
| E-3 | Admin span-gate overlap fixture | Required | AdversarialRisk R3/G3 | Keep admin DB outside collector and expand tests before wiring |
| E-4 | Fail-closed short-circuit spy | Required | AdversarialRisk R5/G5 | Keep collector invocation below fail-closed branch |
| E-5 | CandidateCollector interface smoke | Required | README §5 | Revise interface before implementation |

---

## 2. E-1 · Baseline characterization inventory

### Goal

Confirm where current tests already cover issue #8 invariants and identify gaps
before adding any production code.

### Script

```bash
# Read and inventory test names and assertions; do not run broad suite for spec POC.
python - <<'PY'
from pathlib import Path
for p in [
    'tests/test_linear_engine.py',
    'tests/test_sample_integration.py',
    'tests/test_china_admin.py',
    'tests/test_web_app.py',
    'tests/test_postprocess.py',
    'tests/test_cases.py',
    'tests/test_status.py',
]:
    print('##', p)
    text = Path(p).read_text(encoding='utf-8')
    for line in text.splitlines():
        if line.startswith('def test_') or line.startswith('    def test_'):
            print(line.strip())
PY
```

### Verification standard

- [x] Inventory covers same-surname numbering or marks it missing.
- [x] Inventory covers organization alias behavior or marks it missing.
- [x] Inventory covers admin/china precedence or marks it missing.
- [x] Inventory covers HanLP enable/project conversion or marks it missing.
- [x] Inventory covers LLM review/fallback Web behavior or marks it missing.

### Result

- Status: PASS with one explicit Step 1 gap.
- Evidence artifact: `.ff-state/poc/candidate-collection-architecture/E1-inventory.json`.
- Inventory scanned 7 focused files and 170 tests. Existing coverage includes document-order person placeholders, organization alias/brand behavior, china-admin path behavior, same-surname manual numbering, partial LLM batch handling, and Web MLX-unavailable offline fallback.
- Gap recorded: no current HanLP enable/project-suffix characterization test was found. Step 1 already requires `T2 Admin HanLP characterized`; add that test before helper moves.

### Fallback

If an invariant lacks coverage, Step 1 must add the characterization test before
any helper move or runtime wiring.

---

## 3. E-2 · Audit-only entity materialization

### Goal

Prove the issue #8 `collect once` wording is unsafe unless the final candidate
set includes audited `linear_llm_exact` candidates from non-empty `llm_analysis`.

### Script

```bash
.venv/bin/python -m pytest <new-test-for-audit-only-entity> -q
```

The fixture must create a case where review prepass with `analysis={}` lacks an
entity, but final analysis returned by `LegalEntityAuditor.audit_and_verify`
contains it and current behavior maps it through `linear_llm_exact`.

### Verification standard

- [x] Baseline current behavior maps the audit-only entity.
- [x] Source or evidence proves it enters as `linear_llm_exact`.
- [x] Refactor plan keeps this by Design B: final collector call uses audited analysis.

### Result

- Status: PASS.
- Evidence artifact: `.ff-state/poc/candidate-collection-architecture/step-0-poc-summary.json`.
- Smoke command used `LinearRuleEngine.collect_candidates`: empty analysis returned no `未来科技有限公司`; audited analysis returned `{'type': 'organization', 'text': '未来科技有限公司', 'start': 7, 'end': 15, 'source': 'linear_llm_exact', 'confidence': 0.95}`.
- Conclusion: literal single collection before audit would lose audit-only entities; Design B is required.

### Fallback

If a clean audit-only fixture cannot be built, Gate 0b must block and require a
revised seam contract before implementation.

---

## 4. E-3 · Admin span-gate overlap fixture

### Goal

Prove admin DB detections are span gates and pre-accepted mappings, not ordinary
collector candidates.

### Script

```bash
.venv/bin/python -m pytest <new-test-for-admin-hanlp-china-overlap> -q
```

The fixture should fake HanLP, use an admin DB or detector fixture, and include a
overlapping china-admin-rule candidate.

### Verification standard

- [x] Admin DB mapping wins.
- [x] Overlapping HanLP/china-rule candidate does not override it.
- [x] No duplicate mapping is emitted for the same admin entity.

### Result

- Status: PASS for span-gate feasibility; Step 1 still adds full admin/HanLP/china overlap characterization.
- Evidence artifact: `.ff-state/poc/candidate-collection-architecture/step-0-poc-summary.json`.
- Smoke command used `_span_overlaps_admin`: grassroots/china overlap over admin span returned `True` (blocked); direct admin-level overlap returned `False` (allowed). Source anchors: `pipeline.py` lines 142-153 and 512-540.

### Fallback

If the fixture reveals current behavior is already inconsistent, pause wiring and
revise gates to preserve observed product behavior or request product decision.

---

## 5. E-4 · Fail-closed short-circuit spy

### Goal

Ensure the collector does not run when sentence extraction errors and
`fail_open=False`.

### Script

```bash
.venv/bin/python -m pytest <new-test-for-fail-closed-no-collector> -q
```

The test should monkeypatch sentence extraction to return an error and spy on
`CandidateCollector.collect` and `LinearRuleEngine.discover`.

### Verification standard

- [x] Result contains only base/sample/fixed-regex/postprocess mappings.
- [x] `CandidateCollector.collect` is not called.
- [x] `LinearRuleEngine.discover` is not called.
- [x] Warning records regex-only fallback.

### Result

- Status: PASS for current source shape; future collector spy remains required after inert module exists.
- Source evidence: `pipeline.py` lines 630-673 returns `RedactionResult` before `_linear_run_engine` lines 700-760.
- Focused verification: `.venv/bin/python -m pytest tests/test_linear_engine.py::test_apply_llm_verdicts_rejects_and_calibrates_candidates tests/test_linear_engine.py::test_append_exact_candidate_uses_single_occurrence_fallback_when_window_misses tests/test_web_app.py::WebAppUploadTests::test_redact_route_falls_back_to_offline_rules_when_mlx_unavailable_and_saves_case -q` → `3 passed in 0.54s` (`artifact://16`).

### Fallback

If the future implementation cannot preserve this, collector invocation must be
moved below the fail-closed branch before Gate 2.

---

## 6. E-5 · CandidateCollector interface smoke

### Goal

Validate the inert module shape before moving runtime logic.

### Script

```bash
.venv/bin/python - <<'PY'
from legal_redactor.candidate_collector import (
    CandidateCollectionContext,
    CandidateCollectionResult,
    CandidateCollector,
)
print(CandidateCollectionContext, CandidateCollectionResult, CandidateCollector)
PY
```

### Verification standard

- [x] The module imports without side effects.
- [x] It does not import HanLP model code or start LLM transport at import time.
- [x] It exposes no detector registration API.

### Result

- Status: explicit FALLBACK, not executed.
- Reason: implementation is intentionally out of scope before Gate 0a/0b, so `legal_redactor/candidate_collector.py` does not exist yet; path exists check returned `False`.
- Fallback action: Gate D2 and Step 2 require this import smoke immediately after the inert module commit and before helper moves/runtime wiring.

### Fallback

If import shape becomes larger, return to Gate 0a decision D-02 and re-review the
seam.

---

## 7. Gate 0b Checklist

- [x] E-1 through E-5 have PASS or explicit fallback.
- [x] Any failed POC has been reflected back into `EXECUTION_PLAN.md` before implementation.
- [x] Design B remains coherent after E-2.
- [x] Admin DB span gate remains coherent after E-3.
- [x] Gate 0b review-repair artifacts exist and pass.
