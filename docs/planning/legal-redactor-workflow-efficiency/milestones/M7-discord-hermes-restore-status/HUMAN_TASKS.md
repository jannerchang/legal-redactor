# M7-discord-hermes-restore-status · discord-hermes-restore-status · HUMAN_TASKS · 用户介入项

> **依据**:[README.md](README.md) + [EXECUTION_PLAN.md](EXECUTION_PLAN.md) + /Users/jannerchang/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.0.123/templates/gate.schema.md §四
> **节奏**:实装期填 · §A 物理无法 + §B 评审拍板 · 不混 AI 自决项
> **强约束**:不把 AI 自己能判断的设计选型塞进本文件 · §B 评审拍板项必须 Gate 0a 内消化完
> **版本**:v1.1 · 2026-06-29

---

## §A · 物理无法(用户必做 · AI 无法替代)

### A.1 · 环境准备

- 无新增本地开发依赖。M7 build should use the existing Python/FastAPI/MCP
  test stack with synthetic local cases.

### A.2 · API key / 凭证注入

- [ ] α-2.1 · Optional live Office API smoke requires
  `LEGAL_REDACTOR_API_TOKEN` or local `api_token`. Detection: M3 status reports
  token presence and `GET /health` over localhost/private IP. Fallback: mocked
  API tests and safe missing-token diagnostics satisfy Gate proof.
- [ ] α-2.2 · Optional Home Mac Hermes MCP smoke requires
  `LEGAL_REDACTOR_MCP_CONFIG`, `LEGAL_REDACTOR_API_URL`, and
  `LEGAL_REDACTOR_API_TOKEN` on the Home Mac. Detection: MCP `initialize` and
  `tools/list` smoke. Fallback: local JSON-RPC tests with monkeypatched Office
  API responses.
- [ ] α-2.3 · Optional Discord live smoke requires existing Discord bot token
  and command channel only if the user wants to verify redacted-only send
  behavior. Fallback: M7 does not post restored output to Discord; local tests
  prove no restored-output send path is added.

### A.3 · 第三方依赖 / CLI

- 无新增. FFCS Gate review continues to use `.claude/ffcs.local.md`
  `codex,grok` reviewer policy.

### A.4 · 跨平台前置

- [ ] α-4.1 · Optional Office/Home private-network live smoke requires both Macs
  reachable over private network such as Tailscale. Detection: `GET /health`
  from Home Mac to Office API private address. Fallback: local mocked
  `office_unreachable` and config-missing tests.

### A.5 · webhook / 通知通道

- 无新增. M7 must not add webhook or restored-output Discord posting.

### A.6 · 拍板 / Trust

- 无新增 trust decision at spec time. Private API binding address and token
  rotation remain operator setup tasks, not product design blockers.

## §B · 评审拍板(评审组介入 · Gate 0a 内消化完 · 不带进执行期)

### B.1 · Gate 0a 评审拍板项(spec 阶段)

- H-0.1 · Safe response schema signoff · `β review-signoff` · `urgency: before_step_1` · `expected_input: codex+grok+chair artifact PASS or documented blocker` · `blocking: true`
- H-0.2 · Privacy boundary signoff · `β review-signoff` · `urgency: before_step_1` · `expected_input: confirm remote defaults omit restored text, maps, originals, tokens, samples, and absolute paths` · `blocking: true`
- H-0.3 · Effective profile upshift signoff · `β review-signoff` · `urgency: before_step_1` · `expected_input: accept strict effective profile for M7 high-risk restore surfaces` · `blocking: true`

### B.2 · Gate 0b 评审拍板项(POC 实测后)

- H-0b.1 · POC feasibility signoff · `β review-signoff` · `urgency: before_step_1` · `expected_input: E-1 through E-5 non-blocking or fallback recorded` · `blocking: true`

### B.3 · Step N 末 · Gate 2 / DoD 闭环评审拍板项

- H-7.1 · Gate 2 signoff · `β review-signoff` · `urgency: gate_2_signoff` · `expected_input: codex+grok+chair artifact PASS or documented blocker` · `blocking: true`

### B.4 · 跨模块签字项

- H-S.1 · Office API status/restore response schema affects Hermes MCP callers · Gate 0a signs schema; Gate 2 verifies implementation.
- H-S.2 · Last restore metadata affects case archive and Web status · Gate 0a signs content-free metadata; Gate 2 verifies tests and sensitive audit.
- H-S.3 · MCP error/result shape affects Hermes tool callers · Gate 0a signs safe error normalization; Gate 2 verifies mocked network behavior.

### B.5 · 本 milestone 完成出口拍板

- H-7.E.1 · M7 Gate 2 PASS · 主审 `codex+grok` 合议签字.
- H-7.E.2 · POST_GA observation doc remains linked because M7 is high risk.
- H-7.E.3 · Next command after spec PASS is `/ffcs:build M7-discord-hermes-restore-status`.

### B.6 · 断路上抛拍板项(实装期触发时记 · 不预设)

- H-B.1 · If remote status cannot be useful without returning restored text or
  absolute Office paths, stop and upthrow with safe alternatives.
- H-B.2 · If live credentials become mandatory to prove local behavior, stop and
  preserve mocked Gate proof plus optional live-smoke instructions.
- H-B.3 · If preserving API compatibility requires leaking content/path data,
  stop and ask for an explicit breaking-change decision.

## §C · 签字状态

### Gate 0a · 六件套规划评审

- 评审池:`codex,grok`
- 状态:✅ PASS
- 主审:`.ff-state/reviews/M7-discord-hermes-restore-status-gate0a/chair-signoff.json`

### Gate 0b · POC 放行

- 状态:✅ PASS
- 主审签字条件:E-1 through E-5 all non-blocking or fallback recorded
- 主审:`.ff-state/reviews/M7-discord-hermes-restore-status-gate0b/chair-signoff.json`

### Checkpoint 1 · Step 1+ 自验

- 状态:⏳ 待 `/ffcs:build`
- 自验:AI 自验 · 不需用户介入

### Gate 2 · DoD 闭环

- 状态:⏳ 待 `/ffcs:build`
- 主审签字:focused/full tests, privacy audit, safe response artifacts, and review artifacts

### POST_GA · 上线观察

- 状态:⏳ 待 Gate 2 PASS 后建档
- 观察重点:remote privacy, Office/Home smoke, status usefulness, no Discord restored-output leak
