# M4-guided-intake-case-binding · guided-intake-case-binding · 执行计划

> **依据**:[README.md](README.md), [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §6.2
> **格式**:七层硬门槛 + 决策表 + Step 顺序 + 时间盒 + 跨模块签字 + 服务端权威重算 + 文档维护扫
> **schema 引用**:/Users/example/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.0.111/templates/gate.schema.md
> **更新节奏**:Step 进 / 出时同步本文件 + [_progress.md](_progress.md)
> **版本**:v1.0 · 2026-06-29

---

## §1 · 七层硬门槛

| id | title | description | evidence_required | pass_condition | block_severity | typical_count |
|---|---|---|---|---|---|---:|
| D1 | State vocabulary fixed | Define a stable case workflow state set: `not_saved`, `saved_local`, `bound_thread`, `sent_discord`, `waiting_hermes`, `attach_failed`. | code_path_read, unit_test_count | Tests prove all public case workflow responses use only the allowed states. | BLOCKER | 1 |
| D2 | Manifest authority | Case folder, thread URL/id, mapping path, and redacted file records come from local manifest or raw local facts. | code_path_read, unit_test_count | Existing manifest data is read before save/attach and returned as authoritative status. | BLOCKER | 1 |
| D3 | Raw input only | New/changed Web APIs accept raw facts and explicit confirmation fields only, not final workflow decision fields. | api_route_inventory, unit_test_count | Submitting forged decision fields such as `state`, `status`, `bound`, `sent`, or `conflict_result` returns `INVALID_INPUT`/HTTP 400 and does not update local state. | BLOCKER | 1 |
| D4 | Conflict contract | Different existing manifest/thread binding is reported as conflict and not overwritten silently. | unit_test_count, integration_test_count | Conflict tests fail unless overwrite requires explicit confirmation. | BLOCKER | 1 |
| D5 | Suggestion evidence | Case suggestions return evidence and confidence/ambiguity signals, not only a guessed path. | unit_test_count | Filename/source-folder/manifest match evidence appears in JSON or rendered warning. | HIGH | 1 |
| D6 | Manual override kept | User can still type case root/folder/thread manually and see when the typed value overrides a suggestion. | integration_test_count | Web tests cover manual override and warning rendering. | HIGH | 1 |
| D7 | Privacy boundary | Suggestions/statuses never expose originals, map contents, restored full text, or sample data. | unit_test_count, grep_stdout | Tests inject sensitive text/map-like values and assert they are not in case state output. | BLOCKER | 1 |
| D8 | Outbound metadata allowlist | Discord/Hermes outbound messages include only request id, sanitized case folder/title/cause, and redacted attachment metadata. | integration_test_count, grep_stdout | Create-thread and attach tests assert `case_root`, `source_dir`, local absolute paths, originals, maps, restored text, and samples are absent from outbound Discord payloads. | BLOCKER | 1 |
| P1 | Suggestion scorer | Implement a pure helper that scores candidate case directories from uploaded filenames and optional selected source folder. | unit_test_count | Strong, no match, and ambiguous candidates are deterministic. | BLOCKER | 1 |
| P2 | Manifest reader | Add a safe manifest summary helper that tolerates missing/invalid manifests without crashing intake. | unit_test_count | Missing/invalid manifest returns state/error detail while preserving redaction flow. | HIGH | 1 |
| P3 | Thread binding checker | Normalize Discord thread URL/id and detect duplicate or conflicting bindings under a case root. | unit_test_count | Duplicate and conflict cases produce explicit codes. | BLOCKER | 1 |
| P4 | State reducer | Compute the public workflow state from local save result, manifest, thread URL, attach response, and Hermes pending result. | unit_test_count | Reducer maps raw outcomes to the fixed D1 vocabulary. | BLOCKER | 1 |
| P5 | M3 readiness reuse | Reuse or reference M3 status/config diagnostics only for readiness hints; do not duplicate startup probes in M4. | code_path_read | No second MLX/Web/Office/MCP status implementation appears in M4 code. | MEDIUM | 1 |
| S1 | Authoritative recompute | Server recomputes binding/workflow state and rejects forged decision fields from clients. | integration_test_count | API tests show forged `state`, `status`, `bound=true`, `sent=true`, or `conflict_result` fields return `INVALID_INPUT`/HTTP 400. | BLOCKER | 1 |
| S2 | Bounded filesystem search | Case suggestion search remains bounded by depth/entry count and ignores dot/cache/runtime folders. | unit_test_count, code_path_read | Tests or code read prove search cannot scan unbounded roots indefinitely. | HIGH | 1 |
| N1 | Hermes passive wait | Waiting for Hermes thread creation remains a `waiting_hermes` state and does not retry forever on the server. | integration_test_count | `/api/discord/attach-bound-thread` can return `waiting_hermes` without side effects beyond the request. | HIGH | 1 |
| N2 | Redacted-only Discord | Discord attach/send paths send redacted attachment only and never send map JSON/original text. | integration_test_count, grep_stdout | Tests assert Discord post receives redacted content and not map/original payload. | BLOCKER | 1 |
| N3 | Create-thread privacy | Hermes create-thread command does not leak local absolute paths or source directories to Discord. | integration_test_count, grep_stdout | Tests assert outbound command content omits `case_root`, `source_dir`, `/Users/`, `/Volumes/`, maps, originals, restored full text, and samples. | BLOCKER | 1 |
| C1 | Suggest API shape | `/api/suggest-case-location` returns status, candidate case root/folder, evidence, ambiguity/conflict fields, and safe manifest summary. | integration_test_count | Web test verifies JSON shape for ok/ambiguous/conflict/not_found. | BLOCKER | 1 |
| C2 | Intake prefill UX | The first-screen intake fields can prefill case root/folder/thread from strong suggestions without overwriting manual typed values silently. | integration_test_count | Render or JS-facing test covers prefill preservation behavior. | HIGH | 1 |
| C3 | Result state panel | Redaction result page displays the current case workflow state and next action near local save/Discord controls. | integration_test_count | HTML contains state label and action for saved/bound/waiting/failure outcomes. | HIGH | 1 |
| C4 | Conflict warning | Conflict/ambiguous state renders a visible warning and requires explicit user confirmation before overwrite. | integration_test_count | Test proves conflicting thread URL is not silently overwritten. | BLOCKER | 1 |
| T1 | Case unit tests | Extend `tests/test_cases.py` for scorer, manifest summary, conflict detector, and state reducer. | unit_test_count | `.venv/bin/python -m pytest tests/test_cases.py` passes. | BLOCKER | 1 |
| T2 | Web integration tests | Extend `tests/test_web_app.py` for suggest API, result state rendering, forged decision-field rejection, manual override, Hermes wait, create-thread payload privacy, and Discord attach. | integration_test_count | `.venv/bin/python -m pytest tests/test_web_app.py` passes. | BLOCKER | 1 |
| T3 | Focused suite | Run focused M4 suite including M3 status tests when shared Web status context is touched. | unit_test_count, integration_test_count | Focused suite passes or failures block Gate 2. | BLOCKER | 1 |
| T4 | Browser smoke | Record a paste/upload-to-case smoke plan or evidence for saved/bound/waiting paths. | doc_anchor | Build closeout records smoke command/browser path or skip reason. | MEDIUM | 1 |
| T5 | Full regression | Run full pytest before Gate 2 if shared `web_app.py` or `cases.py` behavior changes broadly. | unit_test_count | Full pytest passes or scoped failure is documented and justified. | HIGH | 1 |
| E1 | Operator docs | Update docs only if user-facing case workflow status meanings change. | doc_anchor | Docs explain states without exposing secrets or requiring Discord credentials. | MEDIUM | 1 |
| E2 | M7 handoff | Record what M7 can reuse: thread binding state, manifest status, and conflict semantics. | doc_anchor | M4 closeout points M7 to authoritative state helpers. | HIGH | 1 |
| E3 | Sensitive data audit | Before any GitHub delivery, inspect tracked files for maps/originals/samples created during tests. | grep_stdout | Delivery checklist confirms no sensitive case/sample artifacts are tracked. | BLOCKER | 1 |

## §2 · 决策表

| # | 决策 | 影响范围 | 来源 | 状态 |
|---|---|---|---|---|
| D-01 | Keep existing Web intake route. | Web form, result page | README D-01 | 锁 |
| D-02 | Local manifest remains authority. | `cases.py`, M7 restore | README D-02 | 锁 |
| D-03 | Use fixed state vocabulary. | Web API/UI/tests | README D-03 | 锁 |
| D-04 | Server recomputes binding/state. | Web API/service helpers | README D-04 | 锁 |
| D-05 | Block silent overwrite of different thread binding. | Manifest update, Discord attach | README D-05 | 锁 |
| D-06 | Manual override stays possible. | Intake form and suggestion JS | README D-06 | 锁 |
| D-07 | Keep Discord scope redacted-only and no restore status. | Discord/Hermes path, M7 | README D-07 | 锁 |
| D-08 | Allowlist outbound Discord/Hermes metadata. | Hermes create-thread and Discord attach | README D-08 | 锁 |

### §2 附录 · 决策详情

| # | rationale | signoff_version | evidence_link |
|---|---|---|
| D-01 | Existing form already handles paste/upload/batch and carries case fields; improving it is cheaper than a second flow. | v1.0 | `legal_redactor/web_app.py` index form |
| D-02 | Requirements say Office Mac local storage owns originals, maps, manifests, and restored output. | v1.0 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §3 |
| D-03 | Requirements enumerate the exact states the user needs to distinguish. | v1.0 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §6.2 |
| D-04 | Status/state/ownership are authoritative-decision keywords; client-submitted state must not be trusted. | v1.0 | `/Users/example/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.0.111/templates/authoritative-recompute.md` |
| D-05 | Split signoff explicitly forbids silent wrong manifest/thread selection. | v1.0 | [../../SPLIT.md](../../SPLIT.md) Signoff Needs |
| D-06 | Requirements preserve manual override when suggestion is ambiguous. | v1.0 | [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §6.2 |
| D-07 | M7 owns restore readiness/status; M4 only prepares correct binding. | v1.0 | [../../SPLIT.md](../../SPLIT.md) Milestone Overview |
| D-08 | Current create-thread code can append `case_root` and `source_dir`; M4 must prevent local path leakage before signing the workflow state. | v1.0 | `legal_redactor/web_app.py` `_case_creation_command` |

## §3 · Step 顺序

### Step 0 · POC + 防护栏

**时间盒**:`0.5 day`

1. Run `milestone-doc-check.mjs --dir` before Gate 0a.
2. Confirm current suggestion API states and current manifest conflict behavior.
3. Record whether live Discord credentials are needed; default is mocked tests.

### Step 1 · case helpers/state model

**时间盒**:`2 days`

- Add suggestion evidence/scoring helpers in `legal_redactor/cases.py` or a
  small local helper boundary used by `cases.py`.
- Add manifest summary and conflict detection helpers.
- Add a pure state reducer for public workflow state.

**Checkpoint 1**:

- `tests/test_cases.py` covers scorer, conflicts, missing/invalid manifest, and
  pure state reducer behavior.

### Step 2 · Web API/UI integration

**时间盒**:`2 days`

- Extend `/api/suggest-case-location` response shape.
- Keep manual typed fields from being overwritten silently.
- Render state labels/warnings on the first redaction result screen.
- Reject forged workflow decision fields with `INVALID_INPUT`/HTTP 400.

**Checkpoint 2**:

- `tests/test_web_app.py` covers API shape, rendered state/warning output, and
  forged decision-field rejection.

### Step 3 · Discord/Hermes attach states

**时间盒**:`1.5 days`

- Convert existing pending/success/error results into M4 state vocabulary.
- Preserve the user-visible Hermes request path and Discord redacted attachment
  path, but enforce the outbound metadata allowlist so `case_root`,
  `source_dir`, and local absolute paths are not posted to Discord.
- Do not add restore status or restored-output posting.

**Checkpoint 3**:

- Web tests cover `waiting_hermes`, `sent_discord`, `attach_failed`, and
  create-thread payload privacy.

### Step 4 · tests + docs + Gate 2

**时间盒**:`1.5-2 days`

- Run focused tests:

```bash
.venv/bin/python -m pytest tests/test_cases.py tests/test_web_app.py tests/test_status.py
```

- Run full pytest if changes touch shared Web behavior beyond M4 helpers.
- Update `_progress.md` and docs with validation/smoke evidence.
- Run FFCS Gate 2 review with effective `codex + grok` policy.

## §4 · 时间盒细分

| Step | 估时 | 起止 commit | 备注 |
|---|---|---|---|
| Step 0 · POC + 防护栏 | 0.5 day | not committed | Current API/conflict readback + doc-check |
| Step 1 · case helpers/state model | 2 days | not committed | Pure helpers first |
| Step 2 · Web API/UI integration | 2 days | not committed | Existing form/result page |
| Step 3 · Discord/Hermes attach states | 1.5 days | not committed | Redacted-only attach state |
| Step 4 · tests + docs + Gate 2 | 1.5-2 days | not committed | Review proof and handoff |
| **总计** | **6-8 days** | | |

## §5 · 跨模块签字规则

| 跨模块变更 | 影响下游 | D-XX 决策 | owner_signoffs | 测试覆盖 |
|---|---|---|---|---|
| Case workflow state vocabulary | M7 restore status should reuse it | D-03, D-07 | project-local owner accepted by this spec | `tests/test_cases.py`, `tests/test_web_app.py` |
| Manifest conflict semantics | M7 thread restore and Office API lookup | D-02, D-05 | project-local owner accepted by this spec | `tests/test_cases.py` |
| Suggest API shape | Web intake and future browser smoke | D-04, D-06 | project-local owner accepted by this spec | `tests/test_web_app.py` |
| Outbound metadata allowlist | M7 restore and Hermes command privacy | D-07, D-08 | project-local owner accepted by this spec | `tests/test_web_app.py` |

No external owner or live credential signoff is required for Gate 0a. Live
Discord/Hermes smoke remains optional and can be mocked for build tests.

## §6 · 服务端权威重算

M4 includes status/state/ownership/归属 decisions and exposes HTTP routes. The
build must inject authoritative recompute gates instead of trusting browser
state:

- D3 requires client APIs to accept raw facts and explicit confirmation fields
  only, not final state/status/bound/sent/conflict decision fields.
- D4 requires different manifest/thread binding to be detected server-side.
- S1 requires tests proving forged decision fields are rejected with
  `INVALID_INPUT`/HTTP 400.
- C1/C3/C4 require the public state/warning to be rendered from server-computed
  facts.
- D8/N3 require outbound Discord/Hermes messages to be built from an explicit
  allowlist and to exclude `case_root`, `source_dir`, local absolute paths,
  originals, maps, restored full text, and samples.

## §7 · 文档维护扫

- [x] `_progress.md` updated with Gate 0a result and validation/effective profile.
- [x] README and execution plan remain linked from upstream split docs.
- [x] M7 README or handoff records reusable state/conflict semantics after build.
- [x] Restore/deploy docs updated only if operator-facing state names change.
- [x] `.gitignore` remains protective for pid/log/runtime files and sensitive sample/case output.

## §8 · 出口 checklist

- [x] Five-file spec set complete.
- [x] `milestone-doc-check.mjs --dir` passes before Gate 0a.
- [x] Gate 0a review passes with effective policy artifacts.
- [x] `_progress.md` records grep trace, Intent Guard, profile, complexity, and next `/ffcs:build`.
- [x] Handoff target points to `/ffcs:build M4-guided-intake-case-binding`.
- [x] Case helpers/state model implemented and tested.
- [x] Web API/UI integration implemented and tested.
- [x] Discord/Hermes attach states and outbound allowlist implemented and tested.
- [x] Focused suite and full pytest passed.
- [x] Gate 2 review-repair passes with effective policy artifacts:
  `codex-r1` PASS, `grok-r1` PASS, chair signoff PASS
  (`decision=pass_defer`), `evaluateGateProof all_pass=true`.
