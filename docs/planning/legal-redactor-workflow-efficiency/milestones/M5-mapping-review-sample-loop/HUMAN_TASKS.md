# M5-mapping-review-sample-loop · mapping-review-sample-loop · HUMAN_TASKS · 用户介入项

> **依据**:[README.md](README.md) + [EXECUTION_PLAN.md](EXECUTION_PLAN.md) + /Users/jannerchang/.codex/plugins/cache/forge-flow-marketplace/ffcs/1.0.123/templates/gate.schema.md §四
> **节奏**:实装期填 · §A 物理无法 + §B 评审拍板 · 不混 AI 自决项
> **强约束**:不把 AI 自己能判断的设计选型塞进本文件 · §B 评审拍板项必须 Gate 0a 内消化完
> **版本**:v1.0 · 2026-06-29

---

## §A · 物理无法(用户必做 · AI 无法替代)

### A.1 · 环境准备

- 继承 M3/M4 本地 Python/Web/pytest 基线 · 无新增工具、凭证、远端主机、Discord token、Hermes token 或外部 API 要求。

### A.2 · API key / 凭证注入

- 无新增。M5 build and tests must use synthetic sample values and must not require live sensitive sample data.

### A.3 · 第三方依赖 / CLI

- 无新增。FFCS Gate review continues to use the configured `codex,grok` reviewer policy from `.claude/ffcs.local.md`.

### A.4 · 跨平台前置

- 无新增。Browser smoke is local to the existing Web UI unless Gate 2 discovers a platform-specific issue.

### A.5 · webhook / 通知通道

- 无新增。M5 sample-save flow must not send sample details to Discord, Hermes, webhook, or MCP surfaces.

### A.6 · 拍板 / Trust

- 无新增 trust decision at spec time.

## §B · 评审拍板(评审组介入 · Gate 0a 内消化完 · 不带进执行期)

### B.1 · Gate 0a 评审拍板项(spec 阶段)

- None. Current decisions can be inferred from requirements, code, and prior M3/M4 handoff. The exact filter control style is reversible build detail and does not need user approval.

### B.2 · Gate 0b 评审拍板项(POC 实测后)

- None expected. If POC E-1 through E-3 finds that the current result page cannot preserve mapping context without a separate route, Gate 0b must either approve a fallback in the existing result page or upthrow before build.

### B.3 · Step N 末 · Gate 2 / DoD 闭环评审拍板项

- H-7.1 · Gate 2 signoff · `β review-signoff` · `urgency: gate_2_signoff` · `expected_input: codex+grok+chair artifact PASS or documented blocker` · `blocking: true`

### B.4 · 跨模块签字项

- H-S.1 · Sample-save summary schema affects M6 regression measurement · Gate 0a/Gate 0b 主审已签字; final implemented schema remains Gate 2 evidence.
- H-S.2 · Case context preservation affects M4/M7 workflow continuity · Gate 0a/Gate 0b 主审已签字; implementation proof remains Gate 2 evidence.

### B.5 · 本 milestone 完成出口拍板

- H-7.E.1 · M5 Gate 2 PASS · 主审 `codex+grok` 合议签字.
- H-7.E.2 · POST_GA observation doc remains linked because M5 is complex.
- H-7.E.3 · Next command after spec PASS is `/ffcs:build M5-mapping-review-sample-loop`.

### B.6 · 断路上抛拍板项(实装期触发时记 · 不预设)

- H-B.1 · If sample summary cannot avoid sensitive-data exposure while meeting requirements, stop and upthrow with options.
- H-B.2 · If current result page cannot support filters/context preservation without a new page-level architecture, stop and upthrow with POC evidence.

## §C · 签字状态

### Gate 0a · 五件套规划评审

- 评审池:`codex,grok`
- 状态:✅ PASS
- 主审:`.ff-state/reviews/M5-mapping-review-sample-loop-gate0a/chair-signoff.json`
- 合议结果:`pass_defer` · build/Gate 2 followups retained

### Gate 0b · POC 放行

- 状态:✅ PASS
- 主审签字条件:E-1 through E-3 all non-blocking or fallback recorded
- 主审:`.ff-state/reviews/M5-mapping-review-sample-loop-gate0b/chair-signoff.json`

### Checkpoint 1 · Step 1+ 自验

- 状态:✅ 完成
- 自验:focused/full pytest, browser smoke, sensitive sample audit, and docs closeout complete.

### Gate 2 · DoD 闭环

- 状态:✅ PASS
- 主审签字:
  - `.ff-state/reviews/M5-mapping-review-sample-loop-gate2/artifacts/codex-r1.json` · PASS
  - `.ff-state/reviews/M5-mapping-review-sample-loop-gate2/artifacts/grok-r1.json` · PASS
  - `.ff-state/reviews/M5-mapping-review-sample-loop-gate2/chair-signoff.json` · PASS · `pass_defer`
  - machine proof `all_pass=true`, `peer_all_pass=true`, `failed=[]`

### POST_GA · 上线观察

- 状态:✅ 计划已建档；提醒调度保持 opt-in disabled
- 观察重点:sample-save safety, context preservation, M6 handoff usefulness
