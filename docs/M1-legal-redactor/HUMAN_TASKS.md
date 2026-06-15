# M1-legal-redactor · legal-redactor · HUMAN_TASKS

> **依据**:[`README.md`](README.md) + [`EXECUTION_PLAN.md`](EXECUTION_PLAN.md)
> **版本**:v0.1 · `2026-06-10`

## §A · 物理无法(用户必做 · AI 无法替代)

### A.1 · 环境准备

- [ ] α-1.1 · Python venv 可用 · 检测:`test -x .venv/bin/python && .venv/bin/python --version` · fallback:`用项目 README 安装依赖`
- [ ] α-1.2 · 本地 LLM 可选 · 检测:`ollama list` · fallback:`LLM 不可用时自动纯规则运行，不阻塞本 milestone`

### A.2 · API key / 凭证注入

- 无。项目默认本地运行，不需要外部 API key。

### A.3 · 第三方依赖 / CLI

- [ ] α-3.1 · `python-docx` 可导入 · 检测:`.venv/bin/python -c "import docx"` · fallback:`.venv/bin/pip install -r requirements.txt`

## §B · 评审拍板(评审组介入 · Gate 0a 内消化完)

### B.1 · Gate 0a 评审拍板项(spec 阶段)

- 无。当前 spec 没有需要用户拍板的产品分歧。

### B.2 · Gate 0b 评审拍板项

- 不适用。中等复杂度，无强制 Step 0 POC。

### B.3 · Step N 末 · Gate 2 / DoD 闭环评审拍板项

- [ ] H-7.1 · Gate 2 review signoff · `β review-signoff` · `urgency: gate_2_signoff` · `expected_input: FFCS review artifacts PASS` · `blocking: true`

### B.4 · 跨模块签字项

- 无。无跨服务/API/DB/event 契约变更。

### B.5 · 本 milestone 完成出口拍板

- [ ] H-7.E.1 · 本 milestone Gate 2 PASS · 主审合议签字。

### B.6 · 断路上抛拍板项

- 实装期触发同根因 3 次失败、时间盒超时或真实样本证据冲突时 append。

## §C · 签字状态

### Gate 0a · 五件套规划评审

- 评审池:`codex, claude` from `.claude/ffcs.local.md`
- 状态:❌ BLOCK
- 主审:Codex host orchestrator
- 合议结果:`claude` artifact unavailable because `claude` CLI is not on PATH; `codex` native subagent review was not started without explicit user authorization.
- artifact:`.ff-state/reviews/M1-legal-redactor-gate0a/artifacts/claude-r0.json`

### Gate 0b · POC 放行

- 状态:不适用

### Checkpoint 1 · Step 1+ 自验

- 状态:⏳ 待 Step 1

### Gate 2 · DoD 闭环

- 状态:⏳ 待 Step 末自审
