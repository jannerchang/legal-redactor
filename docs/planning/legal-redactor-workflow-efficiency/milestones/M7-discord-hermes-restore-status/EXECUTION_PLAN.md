# M7-discord-hermes-restore-status · discord-hermes-restore-status · 执行计划

> **依据**:[README.md](README.md), [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §6.6, [../../SPLIT.md](../../SPLIT.md)
> **格式**:七层硬门槛 + 决策表 + Step 顺序 + 时间盒 + 跨模块签字 + 服务端权威重算 + 文档维护扫
> **schema 引用**:/Users/jannerchang/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.0.123/templates/gate.schema.md
> **更新节奏**:Step 进 / 出时同步本文件 + [_progress.md](_progress.md)
> **版本**:v1.1 · 2026-06-29

---

## §1 · 七层硬门槛

| id | title | description | evidence_required | pass_condition | block_severity | typical_count |
|---|---|---|---|---|---|---:|
| D1 | Office authority | Office Mac remains the source of truth for manifests, maps, originals, and restored output. | code_path_read, unit_test_count | Remote status/restore resolves through local manifest/map only and never accepts caller-supplied map content. | BLOCKER | 1 |
| D2 | Safe remote schema | Implement the README §4.1 signed response contract for status success, restore success, API errors, MCP direct results, JSON-RPC tool results, allowed codes, nullability, and forbidden fields. | unit_test_count, doc_anchor | Tests fail if required fields disappear, if `unresolved_placeholders` arrays appear in remote defaults, or if remote response needs restored text/map values to diagnose status. | BLOCKER | 1 |
| D3 | No path leakage | Remote API/MCP/Discord defaults do not expose `case_root`, `source_dir`, `/Users/`, `/Volumes/`, or absolute Office paths. | unit_test_count, grep_stdout | Tests inject absolute paths and assert only file name or case-relative path leaves the Office API. | BLOCKER | 1 |
| D4 | No content leakage | Remote API/MCP/Discord defaults do not expose restored full text, original text, redaction map values, samples, debug traces, or tokens. | unit_test_count, grep_stdout | Canary restored text/map/original/token values are absent from response JSON, HTML status, logs captured by tests, and docs. | BLOCKER | 1 |
| D5 | Status vocabulary | Use README §4.1 codes for manifest, binding, mapping, restore, Office reachability, MCP config, auth, and API errors. | unit_test_count, doc_anchor | Missing manifest, unbound thread, cross-root duplicate thread, missing map, no restore yet, unreachable Office, missing MCP config, auth errors, and successful restore produce distinct codes. | BLOCKER | 1 |
| D6 | Restore metadata | Persist last restore metadata as counts/timestamps/file identifiers only; do not store content or placeholder lists in metadata exposed remotely. | unit_test_count, code_path_read | Metadata round-trip returns filename, relative path, replacement count, `unresolved_placeholder_count`, and timing without restored text or `unresolved_placeholders` arrays. | HIGH | 1 |
| D7 | Timing contract | Record `discord_thread_to_restored_ms` when request/complete timestamps exist; otherwise return `null` with a reason. | unit_test_count | Synthetic tests cover integer timing, missing timestamp null, and no negative duration. | HIGH | 1 |
| D8 | Local preview boundary | Restored text preview/download is local Office Web only; private API/MCP defaults stay metadata-only. | integration_test_count | Web preview route can render restored text locally, but MCP/API tests prove remote JSON omits it. | BLOCKER | 1 |
| D9 | Binding conflict safe | M7 reuses M4 conflict semantics and does not overwrite a different manifest/thread binding. | unit_test_count, integration_test_count | Conflict tests fail closed before restore/status bind writes. | BLOCKER | 1 |
| D10 | No recognition drift | M7 does not change redaction recognition rules, sample learning, prompts, startup, or model defaults. | grep_stdout | Diff/readback proves recognition/runtime files are untouched except status integration docs if needed. | BLOCKER | 1 |
| P1 | Status builder pure | Add a pure helper that builds README §4.1 restore status from case path, manifest, mapping existence, and restore metadata. | unit_test_count | Helper covers manifest present/missing, mapping present/missing, latest restore present/missing, count-only unresolved placeholders, and safe next actions. | BLOCKER | 1 |
| P2 | Path scrubber pure | Add a pure path sanitizer for Office-local restored output paths. | unit_test_count | Absolute paths become case-relative paths or file names; path traversal and roots are not emitted. | BLOCKER | 1 |
| P3 | Metadata helper pure | Add pure read/write helpers for last restore metadata payloads. | unit_test_count | Metadata stores schema version, filename, relative path, counts, timestamps, duration, and no content fields. | HIGH | 1 |
| P4 | Error normalizer pure | Normalize Office API and MCP errors into safe `code`, `status`, `message`, and `next_action` fields. | unit_test_count | Raw HTTP response bodies and token/path/text canaries do not appear in normalized errors. | BLOCKER | 1 |
| P5 | Timing helper pure | Compute restore timing from explicit request/completion timestamps. | unit_test_count | Valid timestamps produce non-negative milliseconds; missing or malformed evidence returns null with reason. | MEDIUM | 1 |
| P6 | Response scrubber pure | Add an assertion/helper that rejects README §4.1 forbidden fields and values in remote payloads. | unit_test_count | Tests fail for `restored_text`, `draft_text`, `original`, `masked`, `mapping`, `redaction_map`, `unresolved_placeholders`, `case_root`, `source_dir`, token/body-like keys, and absolute paths. | BLOCKER | 1 |
| S1 | Status route behavior | Extend or add private status route behavior for Discord thread id using README §4.1. | integration_test_count | GET status returns safe status for found, not found, cross-root duplicate, missing-map, latest-restored, and no-restored cases; `find_case_by_thread` must fail closed with `duplicate_thread` instead of selecting newest. | BLOCKER | 1 |
| S2 | Restore route behavior | Harden restore-by-thread POST to save restored output locally and return only README §4.1 safe metadata. | integration_test_count | POST restore writes the file under `restored/`, writes metadata, returns `unresolved_placeholder_count` not `unresolved_placeholders`, and omits text/map/absolute path. | BLOCKER | 1 |
| S3 | Bounded writes | Restore metadata writes are atomic, case-local, and do not overwrite unrelated artifacts. | unit_test_count | Multiple restore calls produce deterministic latest metadata without deleting prior restored text files. | HIGH | 1 |
| S4 | Safe auth errors | Missing/wrong API token and missing config produce safe errors without echoing tokens or config values. | integration_test_count | 401/500 errors contain codes only and no secret values. | BLOCKER | 1 |
| S5 | No silent bind overwrite | Bind/status/restore paths refuse conflicting thread bindings. | integration_test_count | Tests cover existing different thread id and duplicate thread id. | BLOCKER | 1 |
| N1 | MCP status tool | `get_case_status_by_thread` returns safe restore status and next action. | integration_test_count | JSON-RPC and direct adapter tests cover success, missing config, Office unreachable, and Office API error. | BLOCKER | 1 |
| N2 | MCP restore tool | `restore_judgment_from_thread` returns README §4.1 safe restore metadata only. | integration_test_count | MCP result omits restored text, map values, placeholder arrays, absolute paths, raw HTTP body, and tokens. | BLOCKER | 1 |
| N3 | No Discord posting | M7 does not add restored-output Discord posting or webhook notification. | grep_stdout, unit_test_count | New code has no Discord send path for restored text and docs mark future posting as separate approval. | BLOCKER | 1 |
| CA1 | Private route inventory | Document and test Office API routes used by Home Mac/Hermes. | api_route_inventory, integration_test_count | Route inventory includes `/health`, status by thread, bind thread, restore by thread, any new status path, and README §4.1 response envelopes. | HIGH | 1 |
| CA2 | Local Web status | Local Web shows safe restore readiness/status for bound cases without restored text in status panel. | integration_test_count | HTML contains mapping/latest restore/unresolved count labels but not canary text or local absolute paths. | HIGH | 1 |
| CA3 | MCP tool inventory | JSON-RPC `tools/list` and deploy docs expose expected tools and descriptions without content-leaking examples. | integration_test_count | `tools/list` and `docs/deploy/hermes-office-restore.md` contain restore/status/bind tools and no sample/map/restored text. | MEDIUM | 1 |
| CA4 | Operator smoke commands | Docs include local mocked tests and optional live Office/Home smoke commands. | doc_anchor | Runbook distinguishes required local tests from optional credential/private-network smoke. | MEDIUM | 1 |
| T1 | API tests | Add focused API tests for README §4.1 status success, restore success, error envelope, duplicate thread fail-closed behavior, and privacy. | integration_test_count | `.venv/bin/python -m pytest tests/test_remote_api.py` passes and asserts no `unresolved_placeholders`, content, token, body, or absolute path in remote JSON. | BLOCKER | 1 |
| T2 | MCP tests | Add focused MCP tests for tools/list, missing config, unreachable Office, safe error, JSON-RPC wrapping, and restore response privacy. | integration_test_count | `.venv/bin/python -m pytest tests/test_mcp_adapter.py` passes and asserts no raw HTTP body, placeholder arrays, content, token, or absolute path in MCP result strings. | BLOCKER | 1 |
| T3 | Case tests | Add safe summary and restore metadata tests. | unit_test_count | `tests/test_cases.py` covers metadata/path/count behavior. | BLOCKER | 1 |
| T4 | Web tests | Add local Web status/preview-boundary tests if `web_app.py` changes. | integration_test_count | Web tests prove status panel is safe and preview remains local. | HIGH | 1 |
| T5 | Focused suite | Run API/MCP/case/Web/status focused suite. | unit_test_count | Focused suite passes before Gate 2. | BLOCKER | 1 |
| T6 | Full suite | Run full pytest before delivery because API/MCP/case helpers are shared. | unit_test_count | `.venv/bin/python -m pytest` passes or any unrelated pre-existing failure is diagnosed. | BLOCKER | 1 |
| T7 | Sensitive audit | Audit tracked files/diffs for maps, originals, samples, restored text, tokens, and generated local artifacts. | grep_stdout | Git/tracked audit shows no sensitive local case/sample/restored artifacts are staged or tracked. | BLOCKER | 1 |
| E1 | Deploy docs | Update restore runbook with safe schema, status meanings, bind/status/restore tool inventory, route inventory, and smoke commands. | doc_anchor | `docs/deploy/hermes-office-restore.md` matches implemented fields and lists `bind_discord_thread_to_case`, `get_case_status_by_thread`, and `restore_judgment_from_thread`. | HIGH | 1 |
| E2 | README docs | Update README remote restore section if commands/response fields change. | doc_anchor | User-facing docs explain Office authority and no restored text in MCP. | MEDIUM | 1 |
| E3 | Progress closeout | `_progress.md` records Gate artifacts, profile upshift, POC, validation, and DoD evidence. | doc_anchor | Closeout complete before handoff. | BLOCKER | 1 |
| E4 | POST_GA observation | Keep high-risk observation plan for restore privacy and cross-machine smoke. | doc_anchor | POST_GA doc exists and is linked. | MEDIUM | 1 |
| E5 | Next handoff | Handoff points to `/ffcs:build M7-discord-hermes-restore-status` after Gate 0a/0b PASS. | doc_anchor | Runtime handoff updated only at true command boundary. | BLOCKER | 1 |

## §2 · 决策表

| # | 决策 | 影响范围 | 来源 | 状态 |
|---|---|---|---|---|
| D-01 | Office Mac remains authority. | Cases/API/MCP/Web/docs | README D-01 | 锁 |
| D-02 | Remote schema is metadata-only. | API/MCP/tests/docs | README D-02 | 锁 |
| D-03 | No absolute path leakage. | API/MCP/Discord/Web | README D-03 | 锁 |
| D-04 | Fixed status/error vocabulary. | API/MCP/operator docs | README D-04 | 锁 |
| D-05 | Last restore metadata is content-free. | Cases/API/status | README D-05 | 锁 |
| D-06 | Restored text preview is local-only. | Web/API/MCP | README D-06 | 锁 |
| D-07 | Binding conflicts fail closed. | Cases/API/MCP | README D-07 | 锁 |
| D-08 | Live smoke is optional. | Validation/HUMAN_TASKS | README D-08 | 锁 |
| D-09 | Reuse M3/M4 helpers. | Status/case workflow | README D-09 | 锁 |
| D-10 | Do not change recognition defaults. | Pipeline/model/runtime | README D-10 | 锁 |

### §2 附录 · 决策详情

| # | rationale | signoff_version | evidence_link |
|---|---|---|
| D-01 | Office-local authority is the core privacy and correctness boundary. | v1.0 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §3, §6.6 |
| D-02 | Remote users need diagnosis and file identity, not content. | v1.0 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §6.6 |
| D-03 | M4 already signed path scrub requirements for Discord/Hermes. | v1.0 | [../M4-guided-intake-case-binding/README.md](../M4-guided-intake-case-binding/README.md) D-08 |
| D-04 | Separate states are required to diagnose restore failures quickly. | v1.0 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §4 story 8 |
| D-05 | Status after a restore needs counts/timing without storing or exposing content. | v1.0 | `legal_redactor/remote_api.py:107-129` |
| D-06 | Local Web restore preview already exists and should not become a remote content API. | v1.0 | `legal_redactor/web_app.py:1712-1786` |
| D-07 | Wrong binding can restore with the wrong map, so conflicts must fail closed. | v1.0 | `legal_redactor/cases.py:232-283` |
| D-08 | External credentials and private network are outside deterministic local Gate proof. | v1.0 | [../../READINESS.md](../../READINESS.md) §3 |
| D-09 | M3/M4 already implemented status and case-state foundations. | v1.0 | M3/M4 README and `_progress.md` closeout |
| D-10 | Restore status has no reason to mutate recognition/runtime behavior. | v1.0 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §6.5 |

## §3 · Step 顺序

### Step 0 · POC + 防护栏

**时间盒**:`1 day`

1. Run `milestone-doc-check.mjs --dir` before Gate 0a.
2. POC E-1: inspect current case/API restore status surface against README §4.1 and verify cross-root duplicates fail closed instead of selecting newest.
3. POC E-2: inspect MCP adapter JSON-RPC and direct tools for safe error handling.
4. POC E-3: prove absolute path/content scrub requirements with synthetic canaries.
5. POC E-4: inspect local Web restore preview and decide the local-only boundary.
6. POC E-5: verify restore timing metadata can be captured without content.
7. Update `step-0-poc-report.md`, then run Gate 0b review before build.

**POC writeback(v1.1)**:

- E-1 confirmed the existing API tests pass, but current restore responses
  still expose `restored_file` absolute paths and `unresolved_placeholders`
  lists. Step 2 must replace those remote defaults with README §4.1 safe
  metadata and count-only unresolved placeholders.
- E-1 confirmed current cross-root thread lookup selects the newest match.
  Step 2 must fail closed with `duplicate_thread` before any status/restore
  operation uses a case map.
- E-2 confirmed MCP adapter tests pass and tool inventory is stable, but
  current HTTPError handling relays raw `body`. Step 3 must normalize Office
  API errors to safe code/status/message/next_action only.
- E-3 through E-5 confirmed the path/content scrub, local Web preview boundary,
  and timing metadata design are feasible without returning restored text,
  original text, map values, tokens, placeholder arrays, or absolute Office
  paths remotely.

### Step 1 · restore status data contract

**时间盒**:`2 days`

- Add safe restore-status schema and pure helpers in `cases.py` or a small local module.
- Add content-free last-restore metadata helpers.
- Add tests before or alongside implementation for safe summary, path scrubber,
  metadata round-trip, timing, and forbidden-field sanitizer.

**Checkpoint 1**:

- `tests/test_cases.py` covers restore status helper behavior and metadata safety.

### Step 2 · Office API hardening

**时间盒**:`2 days`

- Extend existing status by thread and restore by thread behavior to implement README §4.1.
- Preserve bearer auth.
- Convert restore responses from absolute-path/content-risk payloads to safe
  metadata-only payloads.
- Normalize missing map/manifest/duplicate/conflict errors.

**Checkpoint 2**:

- `tests/test_remote_api.py` covers success, missing manifest, unbound thread,
  missing map, cross-root duplicate thread, auth errors, timing metadata,
  count-only unresolved placeholders, and privacy canaries.

### Step 3 · MCP + Web integration

**时间盒**:`2 days`

- Normalize MCP adapter errors and remove raw HTTP body relay.
- Confirm JSON-RPC tools/list and tools/call return safe status.
- Add local Web restore-status rendering where useful; keep restored text
  visible only through existing local preview/download behavior.

**Checkpoint 3**:

- `tests/test_mcp_adapter.py` and relevant `tests/test_web_app.py` cases pass.

### Step 4 · docs + validation + Gate 2

**时间盒**:`2-3 days`

- Update README and deploy docs, including the deploy runbook's MCP tool list
  and the README §4.1 response schema.
- Run focused tests:

```bash
.venv/bin/python -m pytest \
  tests/test_cases.py \
  tests/test_remote_api.py \
  tests/test_mcp_adapter.py \
  tests/test_web_app.py \
  tests/test_status.py
```

- Run full pytest because shared API/case helpers are touched.
- Run privacy/sensitive audit over tracked files and diff.
- Run FFCS Gate 2 review with effective `codex + grok` policy.

## §4 · 时间盒细分

| Step | 估时 | 起止 commit | 备注 |
|---|---:|---|---|
| Step 0 · POC + 防护栏 | 1 day | not committed | Status schema, MCP errors, privacy scrub, timing metadata |
| Step 1 · data contract | 2 days | not committed | Case helpers and tests |
| Step 2 · Office API | 2 days | not committed | Private route behavior and safe payloads |
| Step 3 · MCP + Web | 2 days | not committed | Tool normalization and local status rendering |
| Step 4 · docs + Gate 2 | 2-3 days | not committed | Focused/full tests, audit, review |
| **总计** | **7-10 days** | | |

## §5 · 跨模块签字规则

| 跨模块变更 | 影响下游 | D-XX 决策 | owner_signoffs | 测试覆盖 |
|---|---|---|---|---|
| Office API status/restore response schema | Home Mac Hermes MCP adapter and docs | D-02, D-03, D-04 | project-local owner accepted by this spec | `tests/test_remote_api.py`, `tests/test_mcp_adapter.py` |
| Last restore metadata schema | Case archive status and Web display | D-05, D-07 | project-local owner accepted by this spec | `tests/test_cases.py`, `tests/test_remote_api.py` |
| MCP tool result/error shape | Hermes tool callers | D-02, D-04, D-08 | project-local owner accepted by this spec | `tests/test_mcp_adapter.py` |
| Local Web restore-status display | Web result/case workflow panel | D-06, D-09 | project-local owner accepted by this spec | `tests/test_web_app.py` |

Live Office/Home/Discord credentials remain optional HUMAN_TASKS items, not
Gate 0a blockers.

## §6 · 服务端权威重算

M7 touches status, state, ownership, authorization, and routing, so
authoritative recompute applies.

- Status and restore decisions are recomputed on the Office server from thread
  id, local manifest, local map, local restore metadata, and bearer auth.
- Clients may submit only raw facts such as `discord_thread_id`, `draft_text`,
  `case_folder`, and `discord_thread_url`; they may not submit `restore_state`,
  `mapping_present`, `replacement_count`, `unresolved_placeholder_count`, or
  final path fields.
- If browser/API payloads contain forged workflow/status decision fields, the
  build should reject or ignore them according to existing M4 `INVALID_INPUT`
  behavior and cover the decision in tests.
- MCP adapter must not trust caller-provided status or restored path; it calls
  Office API and returns normalized Office-computed results.
- Cross-root duplicates are server-computed from all candidate case roots and
  must return `duplicate_thread`; a caller cannot choose the winning case by
  sending timestamps, path hints, or status fields.

## §7 · 文档维护扫

- [x] README expanded from placeholder to M7 spec door.
- [x] EXECUTION_PLAN includes D/P/S/N/C+A/T/E hard gates.
- [x] HUMAN_TASKS separates optional live credentials from Gate proof.
- [x] step-0-poc-report includes E-1 through E-5 and fallback design.
- [x] `_progress.md` records profile upshift, complexity, grep trace, and Gate status.
- [x] POST_GA observation plan exists because M7 is high risk.
- [x] Gate 0a PASS recorded.
- [x] Gate 0b PASS recorded after POC.

## §8 · 出口 checklist

- [x] Six-file spec set drafted.
- [x] M7 safe response schema and decisions are explicit.
- [x] Privacy boundary covers text, maps, samples, tokens, placeholder arrays, and absolute paths.
- [x] `milestone-doc-check.mjs --dir` passes before Gate 0a.
- [x] Gate 0a review passes with effective policy artifacts.
- [x] Step 0 POC E-1 through E-5 is executed and recorded.
- [x] Gate 0b review passes or records non-blocking POC findings.
- [x] `_progress.md` records next `/ffcs:build M7-discord-hermes-restore-status`.
