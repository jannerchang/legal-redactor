# M9-rapid-mlx-live-benchmark · human tasks

> **Basis**: [README.md](README.md), [EXECUTION_PLAN.md](EXECUTION_PLAN.md)
> **Status**: no blocking human tasks at spec start
> **Version**: v1.0 · 2026-07-06

---

## A. Current Blocking Tasks

None.

M9 can produce a local live benchmark report with the existing `mlx_lm.server`
baseline, the installed Rapid-MLX CLI when it can be started, and existing
privacy-safe M8/M6 report inputs. If Rapid-MLX cannot be started in this
headless run, the report must record insufficient evidence instead of blocking
on manual setup.

## B. Manual Followups

| # | Task | Needed When | Owner | Blocking? |
|---|---|---|---|---|
| H-01 | Approve any default runtime/model switch. | M9 shows Rapid-MLX is faster with no quality regression and the operator wants to change defaults. | human/product owner | yes for switching defaults, no for M9 report |
| H-02 | Provide private gold-set/report paths. | The operator wants production-private accuracy evidence beyond public/sample or synthetic M6 reports. | human/operator | no |
| H-03 | Install or repair Rapid-MLX if unavailable. | Local Rapid-MLX CLI/server cannot be launched by the worker. | human/operator | no; report records insufficient evidence |

## C. Boundaries

- Do not paste raw legal document text, prompt bodies, completion bodies, sample
  entries, mappings, restored text, tokens, or absolute Office paths into this
  file.
- Existing public Supreme People's Court documents under `samples/` are approved
  benchmark inputs only by relative path/category/hash metadata.
- Do not store live benchmark outputs here unless they are sanitized by the M9
  report writer.
- A default runtime switch is outside this module's automatic merge scope.
