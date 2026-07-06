# M9-rapid-mlx-live-benchmark · Step 0 · POC Report

> **Basis**: [README.md](README.md), [EXECUTION_PLAN.md](EXECUTION_PLAN.md) §3
> **Status**: Draft · Gate 0b pending
> **Constraint**: any failing POC must record fallback; no unresolved POC failure can pass Gate 0b
> **Version**: v1.0 · 2026-07-06

---

## 1. POC Scope

| # | POC | Signoff condition | Source | Fallback |
|---|---|---|---|---|
| E-1 | Baseline MLX identity | Required | README D-04 | Record insufficient baseline evidence |
| E-2 | Rapid-MLX availability | Required | README D-06 | Record insufficient candidate evidence |
| E-3 | Synthetic chat probe | Required | README D-03 | Use mocked probe tests plus live model identity only |
| E-4 | Public SPC sample metadata | Required | user directive 2026-07-03 | Use synthetic fixtures only |
| D | Defense · milestone doc check | Required | FFCS spec/build contracts | Must pass before Gate 0a/0b/2 |

## 2. E-1 · Baseline MLX Identity

### Goal

- Confirm `127.0.0.1:18080` responds to `/v1/models`.
- Confirm the expected model id is exposed.
- Distinguish `mlx_lm.server` from Rapid-MLX when possible.

### Script

```bash
lsof -nP -iTCP:18080 -sTCP:LISTEN
curl -sS --max-time 5 http://127.0.0.1:18080/v1/models
ps -p <pid> -o pid,ppid,command=
```

### Validation

- [x] `/v1/models` contains `mlx-community/Qwen3.5-9B-MLX-4bit`.
- [x] Process command identifies `mlx_lm.server`.

### Result

PASS · 2026-07-06:

- `lsof` showed PID `97450` listening on `127.0.0.1:18080`.
- `/v1/models` returned a model list containing
  `mlx-community/Qwen3.5-9B-MLX-4bit`.
- `ps -p 97450 -o pid,ppid,command=` identified
  `/Users/jannerchang/.local/bin/mlx_lm.server --model mlx-community/Qwen3.5-9B-MLX-4bit ... --port 18080`.

### Fallback

- If baseline is unavailable, M9 may still write a report but must set
  recommendation to `insufficient_evidence`.

## 3. E-2 · Rapid-MLX Availability

### Goal

- Confirm whether `rapid-mlx` is installed.
- Confirm whether a Rapid-MLX server is already running or can be launched on a
  separate local port.
- Preserve unavailability as evidence.

### Script

```bash
command -v rapid-mlx
rapid-mlx ps
rapid-mlx info qwen3.5-9b-4bit
```

### Validation

- [x] `rapid-mlx` CLI exists.
- [x] `rapid-mlx ps` can classify no running server.
- [x] `rapid-mlx info qwen3.5-9b-4bit` resolves the intended Qwen 9B model alias.

### Result

PASS · 2026-07-06:

- `command -v rapid-mlx` returned `/Users/jannerchang/.local/bin/rapid-mlx`.
- `rapid-mlx ps` reported no Rapid-MLX servers running.
- `rapid-mlx info qwen3.5-9b-4bit` resolved
  `mlx-community/Qwen3.5-9B-4bit`.

### Fallback

- If a managed Rapid-MLX server cannot launch during build validation, M9 report
  records candidate unavailability and avoids runtime preference.

## 4. E-3 · Synthetic Chat Probe

### Goal

- Confirm live endpoint speed can be measured with synthetic prompt text.
- Avoid storing prompt or completion bodies in artifacts.

### Script

```bash
curl -sS --max-time 120 http://127.0.0.1:18080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"mlx-community/Qwen3.5-9B-MLX-4bit","messages":[{"role":"user","content":"Return exactly OK."}],"max_tokens":4,"stream":false}'
```

### Validation

- [x] Baseline endpoint responds to OpenAI-compatible chat completions.
- [x] Build implementation stores timing/status/counts only.

### Result

PASS · 2026-07-06:

- Baseline endpoint returned HTTP 200 and `model:
  mlx-community/Qwen3.5-9B-MLX-4bit` for a synthetic prompt.
- The raw response body is not tracked; it is used only to prove endpoint shape
  before implementing sanitized timing probes.

### Fallback

- If live chat probe fails later, tests can still validate sanitizer/report
  behavior and the live report records insufficient speed evidence.

## 5. E-4 · Public SPC Sample Metadata

### Goal

- Confirm public Supreme People's Court sample files are present.
- Keep artifacts to relative paths/categories only.

### Script

```bash
find samples -maxdepth 1 -type f \( -name '*最高*' -o -name '0[123]_*' \) | sort
```

### Validation

- [x] Approved input files are discoverable.
- [x] M9 reports do not include raw sample text.

### Result

PASS · 2026-07-06:

- The grouped `find` command returned the same four approved public inputs used
  by M8: three `0[123]_` construction-dispute text files and one Supreme
  People's Court `.docx` sample under `samples/`.

### Fallback

- Use synthetic M6/M8 fixtures only if public sample paths are unavailable.

## 6. Defense · Doc Check

### Script

```bash
node /Users/jannerchang/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.1.14/lib/milestone-doc-check.mjs --dir docs/planning/legal-redactor-workflow-efficiency/milestones/M9-rapid-mlx-live-benchmark
```

### Validation

- [x] Structural check exits 0 before Gate 0a.
- [ ] Gate 2 structural check exits 0 before final closeout.

### Result

Gate 0a structural check PASS · 2026-07-06:

```text
milestone-doc-check · dir=docs/planning/legal-redactor-workflow-efficiency/milestones/M9-rapid-mlx-live-benchmark · gate2=false · files_scanned=5 · findings=0
OK · 0 findings
```
