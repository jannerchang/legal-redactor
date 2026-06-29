# M7-discord-hermes-restore-status · discord-hermes-restore-status · Step 0 · POC Report

> **依据**:[README.md](README.md) + [EXECUTION_PLAN.md](EXECUTION_PLAN.md) §3 Step 0 + [../../REQUIREMENTS.md](../../REQUIREMENTS.md) §6.6
> **状态**:`executed · Gate 0b PASS`
> **约束**:任一 POC 失败必走 fallback · 不允许悬空
> **版本**:v1.1 · 2026-06-29

---

## 一、POC 范围(5 项 + 防护栏)

| # | POC | 主审签字条件 | 来源 | fallback 优先级(失败时降级用) |
|---|---|---|---|---|
| E-1 | Current API/status gap | Confirm current Office API/case helpers can support README §4.1 safe restore status, identify fields that need hardening, and prove duplicate thread lookup must fail closed. | README D-01/D-02/D-05 | Extend existing GET status and POST restore responses; if route split is needed, add a new private status route while preserving old behavior where safe |
| E-2 | MCP safe error shape | Confirm MCP adapter can normalize missing config, unreachable Office, and HTTP errors without raw body leakage. | README D-02/D-04 | Parse structured JSON detail; if body parse fails, return status/code only |
| E-3 | Path/content scrub | Confirm absolute paths and restored-text canaries are detectable in current outputs and can be removed from remote defaults. | README D-03/D-04/D-06 | Return file name plus case-relative path; keep Office-local full path only inside server logs/internal helpers if needed |
| E-4 | Local Web preview boundary | Confirm existing `/restore/preview` is local-only and separate from remote API/MCP defaults. | README D-06 | Keep preview route unchanged; add only safe status rendering to result/case panels |
| E-5 | Restore timing metadata | Confirm request/completion timestamps and content-free metadata are enough to produce `discord_thread_to_restored_ms` or null with reason. | README D-05/D-07 | Store metadata sidecar under `restored/`; if timestamps absent, return null/deferred reason |
| D | Defense · sensitive boundary | Confirm docs/review material use synthetic canaries only and no samples/maps/restored text are included. | README D-03/D-04 | No fallback; sensitive content must not enter docs, artifacts, commits, or PRs |

## 二、POC E-1 · Current API/status gap

### 目标

- Inspect current `manifest_safe_summary()`, `restore_text_for_thread()`, and
  `case_status_by_thread()` behavior.
- Confirm missing manifest, duplicate thread, missing map, latest restored, and
  unresolved count can be separated.
- Identify current fields that must change before remote status is safe.
- Confirm `find_case_by_thread()` does not silently select a latest case when
  multiple candidate roots bind the same Discord thread.

### planned script

```bash
nl -ba legal_redactor/cases.py | sed -n '286,381p'
nl -ba legal_redactor/remote_api.py | sed -n '63,166p'
.venv/bin/python -m pytest tests/test_remote_api.py -q
```

### 验证标准

- [x] Existing API tests pass before M7 build changes.
- [x] Current response fields are cataloged.
- [x] Any absolute-path or restored-text exposure is recorded as a build hardening item.
- [x] Missing map/status gaps have explicit fallback design.
- [x] Cross-root duplicate bindings are recorded as `duplicate_thread` build
  hardening if current code silently selects by `updated_at`.

### 实测结果

- **状态**:`修订 · 非阻塞`
- **证据**:`.ff-state/logs/M7-spec-poc-E1-2026-06-29.log`
- `.venv/bin/python -m pytest tests/test_remote_api.py -q` passed with
  `6 passed`.
- Current status route can resolve a case by Discord thread and return the
  existing public manifest summary.
- Current restore response still returns `restored_file` as an Office-local
  absolute path and returns `unresolved_placeholders` as a list. Build must
  replace the remote default with README §4.1 safe metadata:
  `restored_filename`, `restored_relative_path`, and
  `unresolved_placeholder_count`.
- Current `find_case_by_thread()` searches candidate roots and selects the
  newest `updated_at` match. Build must fail closed with `duplicate_thread`
  when more than one case/root binds the same Discord thread.
- Missing map/status fallback remains implementable through the existing
  `CaseError`/FastAPI error envelope path plus README §4.1 codes.

### Fallback 决议

- ① Extend existing status response with a nested `restore` object.
- ② Add a new private `restore-status` helper/route only if extending the
  current route would create ambiguous compatibility behavior.
- ③ If latest restore count cannot be recovered from existing files, add
  content-free metadata on future restores and mark old cases as `unknown`.
- ④ If existing multi-root lookup picks the newest case, change build scope to
  fail closed with `duplicate_thread` before status/restore uses any map.

## 三、POC E-2 · MCP safe error shape

### 目标

- Inspect direct MCP calls and JSON-RPC wrappers.
- Confirm missing `api_url`, missing token, unreachable Office, and HTTP errors
  can be represented without raw body text.
- Confirm `tools/list` remains stable.

### planned script

```bash
nl -ba legal_redactor/mcp_adapter.py | sed -n '1,226p'
.venv/bin/python -m pytest tests/test_mcp_adapter.py -q
```

### 验证标准

- [x] Direct adapter tests pass before M7 build changes.
- [x] `tools/list` contains restore/status/bind tools.
- [x] Current raw HTTP body relay is either absent or recorded as a hardening item.
- [x] Missing config/unreachable Office are safe structured errors.

### 实测结果

- **状态**:`修订 · 非阻塞`
- **证据**:`.ff-state/logs/M7-spec-poc-E2-2026-06-29.log`
- `.venv/bin/python -m pytest tests/test_mcp_adapter.py -q` passed with
  `6 passed`.
- `tools/list` already exposes `restore_judgment_from_thread`,
  `get_case_status_by_thread`, and `bind_discord_thread_to_case`.
- Missing `api_url` and missing token already return deterministic structured
  errors.
- Current `urllib.error.HTTPError` handling relays raw HTTP `body`. Build must
  parse a structured Office `detail` when possible and otherwise return only
  safe `office_api_error` code/status/message/next_action.

### Fallback 决议

- ① Parse Office JSON error bodies and keep only `code`, `status`, and safe
  `message`.
- ② If parsing fails, return `office_api_error` with HTTP status and no body.
- ③ Keep direct missing-config errors local and deterministic.

## 四、POC E-3 · Path/content scrub

### 目标

- Create synthetic canary strings for restored text, original text, token-like
  values, and local absolute paths.
- Confirm README §4.1 remote response schema can omit all forbidden values while still
  returning useful status.
- Confirm docs can describe path as file name or case-relative path.

### planned script

```bash
rg -n "restored_file|case_root|source_dir|restored_text|original|api_token|Authorization|/Users|/Volumes" \
  legal_redactor/cases.py legal_redactor/remote_api.py legal_redactor/mcp_adapter.py legal_redactor/web_app.py \
  docs/deploy/hermes-office-restore.md README.md tests/test_remote_api.py tests/test_mcp_adapter.py
```

### 验证标准

- [x] Current leak-prone fields are cataloged.
- [x] Build schema has an explicit allowed-field list in README §4.1.
- [x] Forbidden canaries are included in planned tests.

### 实测结果

- **状态**:`非阻塞`
- **证据**:`.ff-state/logs/M7-spec-poc-E3-2026-06-29.log`
- Grep cataloged current path/content-sensitive surfaces in `remote_api.py`,
  `mcp_adapter.py`, `cases.py`, `web_app.py`, README/deploy docs, and focused
  tests.
- Current leak-prone symbols include `restored_file`, `case_root`,
  `source_dir`, `restored_text`, token/authorization headers, and Office-local
  path handling. These are already covered by README §4.1 and EXECUTION_PLAN
  D2-D4/P2/P4/P6/S1-S2/N1-N2/T1-T2/T7.
- Hits in tests and docs are synthetic canaries or explicit safety wording, not
  real sample or restored content.

### Fallback 决议

- ① Return only `restored_filename` and `restored_relative_path`.
- ② Keep Office-local absolute path out of JSON and available only by inspecting
  the Office case folder directly.
- ③ If a caller needs a full path, require a later explicit local-only mode with
  separate signoff.

## 五、POC E-4 · Local Web preview boundary

### 目标

- Confirm existing Web restore preview path is local-only and uses user-supplied
  map/doc input on the Office browser session.
- Identify where a safe restore-status panel can appear without duplicating
  remote API content.
- Keep remote API/MCP defaults metadata-only.

### planned script

```bash
nl -ba legal_redactor/web_app.py | sed -n '1644,1786p'
rg -n "restore/preview|restored-output|case_workflow_public|latest_restored|unresolved" tests/test_web_app.py legal_redactor/web_app.py
```

### 验证标准

- [x] Existing preview route is documented as local-only.
- [x] Safe status rendering does not include restored text.
- [x] Any added Web status uses safe summary fields only.

### 实测结果

- **状态**:`非阻塞`
- **证据**:`.ff-state/logs/M7-spec-poc-E4-2026-06-29.log`
- Existing `/restore/preview` is a local Office Web route that accepts local
  text/file plus map input and renders local restored text/downloads in the
  browser.
- Current case workflow panel renders case/thread/workflow state metadata and
  is the lowest-risk placement for future safe restore-status labels.
- The local preview route can remain unchanged; M7 build should add only safe
  status rendering outside the remote API/MCP defaults.

### Fallback 决议

- ① Leave preview route unchanged and update docs only.
- ② Add safe status labels near the case workflow panel if current rendering has
  the necessary manifest summary.
- ③ If UI placement risks scope creep, keep M7 Web work to docs/tests around
  existing local preview boundary.

## 六、POC E-5 · Restore timing metadata

### 目标

- Confirm a restore request can capture start/end timestamps without storing
  draft/restored text in metadata.
- Confirm metadata can include `replacement_count`,
  `unresolved_placeholder_count`, `restored_filename`, `restored_relative_path`,
  `requested_at`, `completed_at`, and `duration_ms`.
- Confirm old cases without metadata produce `null` timing with reason.

### planned script

```bash
nl -ba legal_redactor/remote_api.py | sed -n '102,129p'
nl -ba legal_redactor/cases.py | sed -n '336,357p'
```

### 验证标准

- [x] Synthetic helper can compute non-negative duration.
- [x] Metadata schema has no content fields.
- [x] Existing cases without metadata are not treated as failed restores.

### 实测结果

- **状态**:`非阻塞`
- **证据**:`.ff-state/logs/M7-spec-poc-E5-2026-06-29.log`
- Current restore path writes restored text locally and returns count/path
  fields, but it does not yet persist content-free restore metadata.
- Synthetic timing proof produced `synthetic_duration_ms=1250`.
- Missing timestamp proof returned `None` with `timing_reason=missing_timestamp`.
- Build should store metadata only for new restores and treat old cases without
  metadata as `metadata_unknown`/`timing_reason=metadata_missing`, not as a
  restore failure.

### Fallback 决议

- ① Add metadata only for new restores; report old latest file timing as
  `unknown`.
- ② If metadata write fails after restored file write, return restore success
  with `metadata_status=failed` and safe error code.
- ③ If timing cannot be trusted, return `null` with `timing_reason`.

## 七、Defense · sensitive boundary

### 目标

- Keep all POC and review material synthetic.
- Prove no sample/map/original/restored content is introduced into tracked files.
- Record optional live smoke as HUMAN_TASKS rather than Gate blockers.

### planned script

```bash
git status --short
git ls-files samples data output '*.json' '*.log'
rg -n "张三|李四|secret-token|restored full text|/Users/.+legal-redactor-cases" \
  docs/planning/legal-redactor-workflow-efficiency/milestones/M7-discord-hermes-restore-status \
  tests/test_remote_api.py tests/test_mcp_adapter.py
```

### 验证标准

- [x] Only synthetic canaries appear in docs/tests.
- [x] No tracked real sample/map/restored artifacts are added.
- [x] Any live credential/private-network checks remain optional.

### 实测结果

- **状态**:`非阻塞 · PASS`
- **证据**:`.ff-state/logs/M7-spec-poc-defense-2026-06-29.log`
- `git ls-files samples data output '*.json' '*.log'` showed only example
  config files under `config/`.
- Canary grep hits are limited to synthetic focused tests and docs describing
  forbidden fields/values.
- No tracked real sample, map, original, restored output, token, or generated
  local case artifact was added by the M7 spec POC.

### Fallback 决议

- No fallback. If real sensitive content enters docs/review artifacts, remove it
  before review and audit tracked files again.

## 八、出口 Gate 0b checklist

- [x] step-0-poc-report.md 中 E-1 ~ E-5 每条标记 `非阻塞 / 阻塞 / 修订`
- [x] 阻塞项已上抛 + 用户裁决或返回 Gate 0a 调整 spec
- [x] 修订项已回写 [EXECUTION_PLAN.md](EXECUTION_PLAN.md) 对应章节
- [x] 全部 POC 实测结果落档(PASS / FAIL + fallback 决议)
- [x] Defense 节 PASS
- [x] 主审 `codex+grok` Gate 0b PASS · 进 `/ffcs:build`

### Gate 0b 签字

- `codex-r0`:PASS · `.ff-state/reviews/M7-discord-hermes-restore-status-gate0b/artifacts/codex-r0.json`
- `grok-r0`:PASS · `.ff-state/reviews/M7-discord-hermes-restore-status-gate0b/artifacts/grok-r0.json`
- `chair`:PASS `pass_defer` · `.ff-state/reviews/M7-discord-hermes-restore-status-gate0b/chair-signoff.json`
- `proof`:PASS · `.ff-state/logs/M7-spec-gate0b-proof-2026-06-29.log` · `all_pass=true · peer_all_pass=true · failed=[]`
