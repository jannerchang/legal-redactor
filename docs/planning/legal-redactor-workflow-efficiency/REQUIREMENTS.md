---
domain: legal-redactor-workflow-efficiency
created: 2026-06-27
command: ffcs:need
status: split
risk: medium
complexity: medium-high
---

# legal-redactor workflow efficiency requirements

## 1. Goal

The intended operator is a lawyer or another authorized legal-service professional.
AI assists with redaction, organization, summaries, and legal-document drafts; it does
not provide a final legal opinion or produce a judicial decision. The operator remains
responsible for authorization, confidentiality, source verification, and professional review.

Improve the real operating workflow for `legal-redactor`, not only recognition
accuracy. The target is to make daily use simpler, lower configuration and
deployment friction, keep runtime cost controlled, and make sample-driven rule
improvement faster and safer across the full chain:

```text
document input -> redaction -> mapping review -> sample learning -> case archive
-> Discord/Hermes collaboration -> controlled restore
```

The user should not need to understand FFCS, Python internals, model serving,
MCP, Tailscale, or Discord API details to run the normal workflow. Agents can
perform setup and checks, while the product surface should show clear status and
next action.

## 2. Current Workflow Observed

The current repository already has these usable surfaces:

- `./start.sh` starts the Web UI and delegates MLX model startup to
  `scripts/start_mlx9b_server.sh`.
- The Web UI accepts pasted text, file uploads, `.docx` and `.pdf`, and supports
  batch redaction with a unified mapping table.
- The redaction result page allows mapping edits and can save correction diffs
  to `samples/_auto.sample.json`.
- Case persistence stores redacted files and encrypted maps under a local case
  folder through `legal_redactor/cases.py`.
- Discord integration can request thread creation and send redacted attachments
  when local Discord credentials exist.
- Office restore API in `legal_redactor/remote_api.py` exposes private status,
  bind, and restore endpoints.
- Home Mac Hermes can call `legal_redactor/mcp_adapter.py` tools to restore a
  draft by Discord thread id.
- Gold-set evaluation exists through CLI flags such as `--eval-gold` and
  `--eval-report`.

The main friction is not a missing algorithm only. It is the number of small
decisions and hidden states across startup, optional case fields, local JSON
config, model health, sample safety, Discord binding, and restore readiness.

## 3. Assumptions

- Office Mac remains the authority for originals, redaction maps, case manifests,
  and restored output.
- Home Mac/Hermes should only receive non-sensitive status and should call Office
  Mac for restore by thread id.
- Redaction maps, original documents, and restored full text stay off Discord by
  default.
- The current default local model remains
  `mlx-community/Qwen3.5-9B-MLX-4bit` until benchmark evidence justifies a
  change.
- Rules and regex keep handling segmentation, structured formats, and final
  replacement. The local LLM handles whole-sentence/entity reasoning and review
  of low-confidence candidates.
- Sensitive sample data must remain local and must not be committed or uploaded.

## 4. User Stories

1. As a daily user, I can open one local entrypoint and see whether Web, MLX,
   Office API, Discord token, and Hermes MCP are ready.
2. As a daily user, I can upload or paste legal documents without deciding model
   options or deployment internals.
3. As a daily user, I can save a redaction to the correct case folder without
   manually re-entering case root, case folder, and Discord thread URL every
   time.
4. As a daily user, I can review the mapping table quickly by seeing only what
   needs attention and why the system chose each mapping.
5. As a daily user, I can save corrections as samples and immediately see what
   future behavior the sample is expected to teach.
6. As an optimizer, I can start from the newest confirmed error samples and run a
   focused regression check before changing rules.
7. As a lawyer using Hermes, I can bind a collaboration thread to a matter and later
   restore a legal-document draft without exposing maps or original text to Discord.
8. As an operator, I can diagnose startup or restore failures in under one
   minute without guessing whether the problem is Web, MLX, Office API, MCP,
   token, or network.

## 5. Target End-to-End Flow

1. User opens the local Web UI through the normal launcher.
2. A status panel shows:
   - Web app ready.
   - MLX model ready, degraded, or wrong-port occupant.
   - Case root available.
   - Discord send/create-thread configured or missing token.
   - Office restore API ready or not started.
   - Hermes MCP config check result when available.
3. User inputs documents by paste, upload, or selecting a case folder.
4. The app suggests case root, case folder, Discord thread URL, and source
   location from existing manifest and file names.
5. Redaction runs with current hybrid engine:
   - rules and regex for structured discovery and final replacement;
   - local LLM for sentence/entity reasoning;
   - pure-rule fallback when MLX is unavailable.
6. User reviews a mapping table optimized for action:
   - keep confirmed rows out of the way;
   - highlight additions, deletes, and low-confidence rows;
   - preserve `map_reason`;
   - show restore-risk warnings before saving a risky correction.
7. The lawyer saves output to the matter archive and may send only an authorized,
   redacted attachment to a controlled collaboration thread.
8. Hermes later calls MCP with the thread id and a legal-document draft.
9. The local workstation resolves the manifest, restores text with the local map,
   writes restored output under `restored/`, and returns only status/path and
   unresolved placeholder counts for lawyer review.

## 6. Workstreams

### 6.1 Startup, Service Control, and Diagnostics

Requirements:

- Provide one visible status path for Web, MLX, Office API, MCP, Discord config,
  and case root.
- Add a startup diagnosis output that distinguishes:
  - Web dependency missing;
  - MLX binary missing;
  - model cache missing;
  - `127.0.0.1:18080` occupied by the wrong service;
  - MLX model present but not the expected model id;
  - Office API not started;
  - MCP missing `api_url` or `api_token`;
  - Discord command channel/token not configured.
- Keep `./start.sh` as the default path and avoid reintroducing a model picker.
- Add a cheap pure-rule fallback indicator so the user knows the workflow can
  continue with lower recognition support.
- Prefer local config validation that reports bad JSON instead of silently
  returning empty config.
- Keep launchctl or Desktop launcher behavior documented as an operational
  detail, not a requirement for normal manual use.

Implementation surfaces:

- `start.sh`
- `scripts/start_mlx9b_server.sh`
- `legal_redactor/local_config.py`
- `legal_redactor/web_app.py`
- `docs/deploy/hermes-office-restore.md`

### 6.2 Guided Intake and Case Binding

Requirements:

- Reduce case fields the user must fill manually.
- When source file names or a selected source folder match an existing case,
  auto-suggest case root, folder, manifest, and Discord thread URL.
- Show one explicit save state:
  - not saved to case;
  - saved to local case;
  - bound to Discord thread;
  - sent redacted attachment to Discord;
  - waiting for Hermes thread creation;
  - attach failed with reason.
- Keep manual override possible when the suggestion is ambiguous.
- Prevent automatic overwrite of a different manifest/thread binding without a
  clear warning.

Implementation surfaces:

- `legal_redactor/web_app.py`
- `legal_redactor/cases.py`
- `tests/test_web_app.py`
- `tests/test_cases.py`

### 6.3 Mapping Review and Sample Learning

Requirements:

- Make mapping review faster than reading a full table.
- Preserve per-row reason fields such as `map_reason` through edit, save, and
  sample workflows.
- Add action-focused table views or filters:
  - low confidence;
  - added manually;
  - modified;
  - deleted as false positive;
  - restore-risk rows;
  - sample-reused rows.
- When saving samples, show a summary of:
  - what changed;
  - which entries become lookup samples;
  - which entries become delete blacklist candidates;
  - which entries were suppressed as too risky;
  - suggested regression tests to run next.
- Keep safeguards already present for short person deletes and one-character
  province abbreviations.
- Do not let sample saving refresh the page in a way that drops review context.

Implementation surfaces:

- `legal_redactor/web_app.py`
- `legal_redactor/_samples.py`
- `tests/test_sample_integration.py`
- `samples/_auto.sample.json` as local data only, not committed sample evidence.

### 6.4 Recognition and Regression Measurement

Requirements:

- Measure recognition improvements with both model/rule metrics and workflow
  metrics.
- Keep precision, recall, and F1 from gold-set evaluation.
- Add or expose workflow-oriented metrics:
  - manual corrections per document;
  - false-positive deletes;
  - missing entity adds;
  - restore unresolved placeholder count;
  - time from document input to saved case;
  - time from Discord thread to restored output.
- Always verify newest sample provenance before using samples to tune rules.
- Keep the hybrid architecture explicit:
  - rules and regex for structured discovery, segmentation, and final
    replacement;
  - LLM for full-sentence reasoning and low-confidence entity review.
- Prefer focused rule changes with regression tests over broad prompt changes
  unless sample evidence shows the rule layer cannot solve the issue.

Implementation surfaces:

- `legal_redactor/pipeline.py`
- `legal_redactor/llm.py`
- `legal_redactor/_samples.py`
- `legal_redactor/eval` or current CLI eval paths
- `tests/test_pipeline.py`
- `tests/test_llm_config.py`
- `tests/test_sample_integration.py`

### 6.5 Runtime Cost and Deployment Simplicity

Requirements:

- Keep the default deployment cheap and local:
  - one Web service;
  - one local MLX server;
  - optional Office API only when Hermes restore is needed;
  - optional Discord bot token only when sending or creating threads.
- Avoid requiring larger models, cloud services, or multiple model choices
  before there is benchmark evidence.
- Evaluate Rapid-MLX or other runtime changes only through an A/B benchmark:
  - same documents;
  - same sample set;
  - same gold set;
  - same Web workflow timing;
  - compare first-token latency, total redaction time, memory, error rate, and
    manual correction count.
- Treat runtime acceleration as useful only if it reduces total workflow time or
  unlocks more reliable local inference, not merely because tokens per second
  are higher.
- Preserve pure-rule mode for emergency use and cheap deployment.

Implementation surfaces:

- `scripts/start_mlx9b_server.sh`
- `legal_redactor/llm.py`
- CLI eval commands
- future benchmark script under `scripts/` or `docs/planning/...`

### 6.6 Discord, Hermes, Archive, and Restore

Requirements:

- Keep Office Mac as the authority for:
  - case manifest;
  - redaction map;
  - source materials;
  - restored output.
- Improve operator visibility for:
  - manifest exists;
  - thread id bound;
  - mapping exists;
  - Office API reachable;
  - MCP tool list reachable;
  - last restore path;
  - unresolved placeholder count.
- Do not return restored full text through MCP or Discord by default.
- Allow restore preview in local Web when the user wants to inspect output
  before final archive.
- Keep Discord auto-posting scoped to redacted artifacts unless the user later
  approves a separate restored-output workflow.

Implementation surfaces:

- `legal_redactor/cases.py`
- `legal_redactor/remote_api.py`
- `legal_redactor/mcp_adapter.py`
- `legal_redactor/web_app.py`
- `docs/deploy/hermes-office-restore.md`
- `tests/test_remote_api.py`
- `tests/test_mcp_adapter.py`

## 7. Data Flow

| Step | Input | Local authority | External surface | Output |
|---|---|---|---|---|
| Intake | text/doc/docx/pdf/files | Web process | none | parsed documents |
| Redaction | parsed text | pipeline + map | optional local MLX | redacted docs + map |
| Review | redacted text + map | Web page state | none | edited map |
| Sample save | original map + edited map | local `samples/` | none | correction entries |
| Case archive | redacted docs + encrypted map | Office Mac case root | none | manifest/redacted/map |
| Discord send | redacted output | Office Mac | Discord thread | redacted attachment only |
| Hermes restore | thread id + draft | Home MCP -> Office API | private network | restored file path/status |
| Local restore | redacted doc + map | Office Mac | none | restored text/docx |

## 8. Boundaries

In scope:

- Workflow simplification around existing Web, CLI, MLX, case archive, Discord,
  Hermes, and restore surfaces.
- Better diagnostics and local config validation.
- Sample learning UX and regression evidence.
- Optional runtime benchmark design.

Out of scope:

- Rewriting the whole redaction engine.
- Uploading maps, originals, or restored full text to Discord or cloud storage.
- Requiring the user to understand FFCS Gate terminology.
- Making AGY or Grok mandatory FFCS Gate reviewers before separate reviewer
  transport smoke tests prove they produce valid artifacts.
- Changing the default model without benchmark evidence.
- Changing Word restore semantics in a way that risks document structure.

## 9. Testing Plan

Minimum regression set for implementation milestones:

```bash
.venv/bin/python -m pytest \
  tests/test_web_app.py \
  tests/test_cases.py \
  tests/test_remote_api.py \
  tests/test_mcp_adapter.py \
  tests/test_sample_integration.py \
  tests/test_pipeline.py \
  tests/test_llm_config.py
```

Additional proof for runtime and deployment changes:

- `GET http://127.0.0.1:18080/v1/models` returns the expected MLX model id.
- `GET /health` for Web and Office API.
- MCP JSON-RPC `tools/list` exposes the three legal-redactor tools.
- Browser smoke for paste, upload, mapping edit, sample save, case save, and
  Discord section visibility.
- Gold-set eval before and after sample/rule changes.
- Newest-sample provenance check before sample-driven optimization.

## 10. Success Metrics

- Normal redaction startup diagnosis is understandable within one minute.
- A new case can be redacted and saved with fewer manual fields than today.
- Mapping review prioritizes actionable rows instead of requiring full-table
  scanning.
- Sample save tells the user what behavior will change in future runs.
- Every sample-driven rule change has a focused regression test or gold eval.
- Discord/Hermes restore has one visible status path from thread id to restored
  file path.
- Default deployment does not require paid cloud inference or a larger local
  model.
- Sensitive originals, maps, and restored full text remain local/private.

## 11. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Over-automation binds the wrong case/thread | Restore may use the wrong map | require visible binding summary and warning on conflicts |
| Sample delete entries suppress true entities | Lower recall and unsafe redaction | keep short-person and narrow-delete guards, run regression |
| Runtime benchmark focuses on tokens/sec only | Faster model does not simplify workflow | measure total workflow time and correction count |
| Config validation becomes noisy | User ignores warnings | group status by action needed and keep defaults working |
| Discord/Hermes flow leaks sensitive output | Privacy breach | default to path/status only, no restored full text in MCP response |
| FFCS reviewer config is brittle | Formal review cannot pass | separate product workflow from reviewer setup, record Gate blocker |

## 12. Recommended Next Command

This need has more than three workstreams and touches Web, samples, runtime,
case archive, Office API, MCP, and docs. The recommended next FFCS command is:

```text
/ffcs:split legal-redactor-workflow-efficiency
```

The split should produce small milestones, likely:

1. Startup/status/config diagnostics.
2. Guided intake and case binding.
3. Mapping review and sample learning UX.
4. Regression dashboard and newest-sample optimization loop.
5. Discord/Hermes restore status hardening.
6. Optional runtime A/B benchmark.

## 13. Split Output

The requirement has been split into milestone skeletons under
[milestones/](milestones/) and summarized in [SPLIT.md](SPLIT.md).

Recommended first spec:

```text
/ffcs:spec M3-startup-status-diagnostics
```
