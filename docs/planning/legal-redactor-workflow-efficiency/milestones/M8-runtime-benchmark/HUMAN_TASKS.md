# M8-runtime-benchmark · human tasks

> **Basis**: [README.md](README.md), [EXECUTION_PLAN.md](EXECUTION_PLAN.md)
> **Status**: no blocking human tasks at spec start
> **Version**: v1.0 · 2026-07-03

---

## A. Current Blocking Tasks

None.

M8 can be built and reviewed with synthetic M6 reports, local tests, and the
existing public Supreme People's Court sample documents already present under
`samples/`. Live Rapid-MLX installation or live endpoint timing is useful later
but not required for Gate 0a, Gate 0b, or Gate 2.

## B. Manual Followups If Live Runtime Benchmarking Is Desired

| # | Task | Needed When | Owner | Blocking? |
|---|---|---|---|---|
| H-01 | Provide or install a Rapid-MLX candidate runtime command. | The operator wants a live Rapid-MLX run rather than synthetic/report-only comparison. | human/operator | no |
| H-02 | Approve any default runtime/model switch. | A later benchmark report shows a candidate is faster and non-regressing. | human/product owner | yes for switching defaults, no for M8 report |
| H-03 | Provide real gold-set/report paths for an operational benchmark run. | Operator wants local production-like numbers. | human/operator | no |

## C. Boundaries

- Do not paste raw legal document text, sample entries, mappings, restored text,
  tokens, or absolute Office paths into this file.
- Existing public Supreme People's Court documents under `samples/` are approved
  as M8 benchmark/test inputs, but should be referenced by path/category rather
  than pasted into planning, reports, or review artifacts.
- Do not store live benchmark outputs here unless they are sanitized by the M8
  benchmark report writer.
- A missing live Rapid-MLX install is not a blocker for M8 if synthetic tests and
  M6-report comparison pass.
