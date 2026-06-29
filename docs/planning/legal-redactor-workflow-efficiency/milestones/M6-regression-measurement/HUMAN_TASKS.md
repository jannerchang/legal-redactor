# M6-regression-measurement · regression-measurement · HUMAN_TASKS · 用户介入项

> **依据**:[README.md](README.md) + [EXECUTION_PLAN.md](EXECUTION_PLAN.md) + /Users/jannerchang/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.0.123/templates/gate.schema.md §四
> **节奏**:实装期填 · §A 物理无法 + §B 评审拍板 · 不混 AI 自决项
> **强约束**:不把 AI 自己能判断的设计选型塞进本文件 · §B 评审拍板项必须 Gate 0a 内消化完
> **版本**:v1.0 · 2026-06-29

---

## §A · 物理无法(用户必做 · AI 无法替代)

### A.1 · 环境准备

- 无新增。M6 build should use the existing local Python/Web/pytest stack and
  synthetic fixtures.

### A.2 · API key / 凭证注入

- 无新增。M6 does not require Discord, Hermes, Office API, or external model
  credentials.

### A.3 · 第三方依赖 / CLI

- 无新增。FFCS Gate review continues to use the configured `codex,grok`
  reviewer policy from `.claude/ffcs.local.md`.

### A.4 · 跨平台前置

- 无新增。CLI/report tests should run locally without network or live sample
  data.

### A.5 · webhook / 通知通道

- 无新增。Regression reports must not send sample details, maps, originals, or
  restored full text to Discord, Hermes, webhook, or MCP surfaces.

### A.6 · 拍板 / Trust

- 无新增 trust decision at spec time.

## §B · 评审拍板(评审组介入 · Gate 0a 内消化完 · 不带进执行期)

### B.1 · Gate 0a 评审拍板项(spec 阶段)

- H-0.1 · Report schema signoff · `β review-signoff` · `urgency: before_step_1` · `expected_input: codex+grok+chair artifact PASS or documented blocker` · `blocking: true`
- H-0.2 · Privacy boundary signoff · `β review-signoff` · `urgency: before_step_1` · `expected_input: confirm report default output omits raw sample/map/original/restored text` · `blocking: true`

### B.2 · Gate 0b 评审拍板项(POC 实测后)

- H-0b.1 · POC feasibility signoff · `β review-signoff` · `urgency: before_step_1` · `expected_input: E-1 through E-5 non-blocking or fallback recorded` · `blocking: true`

### B.3 · Step N 末 · Gate 2 / DoD 闭环评审拍板项

- H-7.1 · Gate 2 signoff · `β review-signoff` · `urgency: gate_2_signoff` · `expected_input: codex+grok+chair artifact PASS or documented blocker` · `blocking: true`

### B.4 · 跨模块签字项

- H-S.1 · Regression report schema affects M8 runtime benchmark · Gate 0a signs the schema; final implemented schema remains Gate 2 evidence.
- H-S.2 · M5 sample-summary aggregation affects M6 metrics · Gate 0a signs privacy/shape assumptions; implementation proof remains Gate 2 evidence.

### B.5 · 本 milestone 完成出口拍板

- H-7.E.1 · M6 Gate 2 PASS · 主审 `codex+grok` 合议签字.
- H-7.E.2 · POST_GA observation doc remains linked because M6 is complex.
- H-7.E.3 · Next command after spec PASS is `/ffcs:build M6-regression-measurement`.

### B.6 · 断路上抛拍板项(实装期触发时记 · 不预设)

- H-B.1 · If a useful report cannot be generated without exposing raw sample
  contents, stop and upthrow with privacy-safe alternatives.
- H-B.2 · If existing gold evaluator cannot be reused without breaking current
  CLI commands, stop and upthrow with compatibility options.

## §C · 签字状态

### Gate 0a · 五件套规划评审

- 评审池:`codex,grok`
- 状态:✅ PASS
- 主审:`.ff-state/reviews/M6-regression-measurement-gate0a/chair-signoff.json`

### Gate 0b · POC 放行

- 状态:✅ PASS
- 主审签字条件:E-1 through E-5 all non-blocking or fallback recorded
- 主审:`.ff-state/reviews/M6-regression-measurement-gate0b/chair-signoff.json`

### Checkpoint 1 · Step 1+ 自验

- 状态:⏳ 待 `/ffcs:build`
- 自验:AI 自验 · 不需用户介入

### Gate 2 · DoD 闭环

- 状态:⏳ 待 `/ffcs:build`
- 主审签字:focused/full tests, privacy audit, report artifact, and review artifacts

### POST_GA · 上线观察

- 状态:⏳ 待 Gate 2 PASS 后建档
- 观察重点:report privacy, metric usefulness, M8 handoff usefulness
