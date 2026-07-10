# candidate-collection-architecture · candidate-collector · HUMAN_TASKS

> **Basis**: [README.md](README.md), [EXECUTION_PLAN.md](EXECUTION_PLAN.md)
> **Scope**: physical impossibilities and Gate signoffs only; AI-self-decided process choices stay out of this file.
> **Version**: v1.0 · 2026-07-09

---

## §A · Physical Impossibilities

### A.1 · Environment

- [x] α-1.1 · No new local tool, credential, remote host, browser, Discord, Hermes, Office API, or MLX setup is required for the spec phase.
- [ ] α-1.2 · Build phase needs existing project test environment only: `.venv/bin/python -m pytest ...` must be runnable locally. If `.venv` is missing, recreate from existing project instructions; no new dependency is introduced by this spec.

### A.2 · Credentials

- [x] α-2.1 · No API key or external credential is required for this milestone spec.
- [x] α-2.2 · LLM live service credentials are not required for characterization tests; tests must use fakes/mocks for HanLP and LLM paths where needed.

### A.3 · Third-party dependencies

- [x] α-3.1 · No new third-party runtime dependency is approved.
- [x] α-3.2 · HanLP model download is explicitly not required; HanLP tests use fakes/mocks.

### A.4 · Visual evidence

- [x] α-7.1 · Not applicable. Design route is non-visual with `visual_skip_reason=non-visual backend architecture refactor`.

---

## §B · Review Signoff

### B.1 · Gate 0a spec signoff

- [ ] H-0.1 · CandidateCollector Design B · `β review-signoff` · `urgency: before_step_0b` · `expected_input: accept/reject Design B` · `blocking: true`
  - **context**: Design B means `CandidateCollector.collect` takes `llm_analysis` and owns `linear_llm_exact` materialization. Non-primary mode can collect through the same module twice: empty analysis for review selection, audited analysis for final candidates.
  - **why human/review signoff**: resolves the issue #8 contradiction between literal `collect once` wording and collector ownership of LLM-primary collection differences.
- [ ] H-0.2 · Admin DB span-gate contract · `β review-signoff` · `urgency: before_step_1` · `expected_input: accept/reject admin DB outside collector candidates` · `blocking: true`
  - **context**: Admin DB detections stay pre-accepted mappings plus `admin_spans`; collector consumes only already span-filtered seed candidates.
- [ ] H-0.3 · Registry deletion · `β review-signoff` · `urgency: before_step_7` · `expected_input: delete vs private absorb` · `blocking: true`
  - **default**: delete `detector_registry.py` and its tests unless implementation proves a private adapter reduces code without exposing a seam.

### B.2 · Gate 0b POC signoff

- [ ] H-0.B.1 · POC E-1/E-5 conclusions · `β review-signoff` · `urgency: before_step_1` · `expected_input: PASS/fallback/revise spec` · `blocking: true`
  - **context**: If audit-only, admin span, fail-closed, or interface smoke POC fails, return to spec before implementation.

### B.3 · Gate 2 signoff

- [ ] H-7.1 · Candidate collection cutover · `β review-signoff` · `urgency: gate_2_signoff` · `expected_input: PASS/block/absorb/defer/reject` · `blocking: true`
  - **context**: Gate 2 requires byte-identical characterization, focused suite, old seam deletion, docs closeout, and no legacy compatibility relapse.

### B.4 · Cross-module signoff

- [x] H-S.1 · No external API/DB/event/field/error/permission contract changes are introduced by this milestone spec.
- [ ] H-S.2 · Internal module seam signoff is covered by H-0.1 through H-0.3 and Gate 2 review.

---

## §C · Signoff Status

### Gate 0a · Spec review

- Review pool: resolved from `.claude/ffcs.local.md` (`codex`, `grok`; timeout-skippable lanes per config)
- Status: PASS
- Artifacts: `.ff-state/reviews/candidate-collection-architecture-gate0a/artifacts/codex-r0.json`, `.ff-state/reviews/candidate-collection-architecture-gate0a/artifacts/grok-r0.json`
- Chair signoff: PASS (`codex` PASS, `grok` PASS; BLOCKER 0, HIGH 0)

### Gate 0b · POC release

- Status: PASS
- Artifacts: `.ff-state/reviews/candidate-collection-architecture-gate0b/artifacts/codex-r0.json`, `.ff-state/reviews/candidate-collection-architecture-gate0b/artifacts/grok-r1.json`
- Chair signoff: PASS (`codex` PASS, `grok` PASS; BLOCKER 0, HIGH 0)

### Gate 2 · DoD closeout

- Status: pending build
- Artifacts: pending
- Chair signoff: pending
