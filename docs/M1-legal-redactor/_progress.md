# M1-legal-redactor · legal-redactor · _progress

> **依据**:[`README.md`](README.md) + [`EXECUTION_PLAN.md`](EXECUTION_PLAN.md)
> **版本**:v0.1 · `2026-06-10`

## §1 · 状态速览

```text
milestone: M1-legal-redactor
module: legal-redactor
当前阶段: 实装中
当前 Step: Step 2 · 最新样本误判过滤
当前批次: recent-errors -> detector filters -> regression
时间盒进度: 45% / 3 天
最近 commit SHA: ae4cde2
分支: main
HEAD: ae4cde2
工作区: FFCS init + M1 spec docs + latest-sample detector optimization + existing user changes
待办: Gate 0a review lane 仍需补齐；代码优化已完成并通过全量测试
```

## §2 · Intent Guard

### Q1 · feature 简洁度 / 抽象层数?

**答**:本 milestone 固化现有单一路径，不引入新抽象层，不新增产品档位。实现期只允许基于测试失败或最新样本证据做小范围修补。

### Q2 · 当前 spec 目标 scope?

**答**:范围是统一标准脱敏、全量还原、Word 原格式还原、最新样本闭环的工程化基线。不重写 linear engine，不引入云端 API，不改变产品主方向。

### Q3 · "可选 / 推荐项" 分类?

**答**:pytest 子集、grep 留痕、文档同步由主 agent 自决；没有需要用户拍板的产品选项。真实外部凭证不存在，Ollama 不可用也不阻塞。

## §3 · Gate 节

### Gate 0a · 五件套规划评审

- **评审输入**:README + EXECUTION_PLAN + HUMAN_TASKS + step-0-poc-report + _progress
- **评审池**:`codex, claude`
- **状态**:❌ BLOCK
- **结果**:`claude` lane unavailable(`missing_cli`); `codex` native subagent lane 未启动，因为当前工具政策要求用户明确授权 sub-agent spawn，不能伪造 PASS。
- **artifact**:`.ff-state/reviews/M1-legal-redactor-gate0a/artifacts/claude-r0.json`
- **commit SHA**:`ae4cde2`

### Gate 0b · POC 放行

- **状态**:不适用，medium complexity

### Checkpoint 1 · Step 1 ~ N-1 自验

- Step 1:待运行测试基线
- Step 2:待失败证据
- Step 3:待回归验证

### Gate 2 · DoD 闭环

- **状态**:⏳ 待 Step 末自审

## §4 · 硬门槛证据追踪

| 层 | 条目 | 状态 | 证据 |
|---|---|---|---|
| D | D1 映射表全量还原契约 | ✅ | `.venv/bin/python -m pytest tests/test_restore.py tests/test_sample_integration.py` -> 10 passed |
| D | D2 Word 还原格式契约 | ⏳ | `legal_redactor/restore.py`, `scripts/restore_docx.py` |
| D | D3 样本时间戳契约 | ✅ | `.venv/bin/python -m pytest tests/test_restore.py tests/test_sample_integration.py` -> 10 passed |
| D | D4 隐私边界契约 | ⏳ | `README.md` 隐私章节 |
| P | P1 长词优先还原 | ⏳ | restore 单测待补/验证 |
| P | P2 最新误识别闭环 | ⏳ | CLI recent-errors 待跑 |
| P | P3 法律引用保留 | ⏳ | pipeline/hebei 测试待跑 |
| S | S1 批量统一映射一致 | ⏳ | pipeline batch 测试待跑 |
| CA | CA1 CLI 入口一致 | ⏳ | `__main__.py` / `cli.py` |
| CA | CA2 Web restore 入口一致 | ⏳ | `web_app.py` |
| T | T1 restore 单测 | ✅ | 2 restore tests passed in combined run |
| T | T2 samples 单测 | ✅ | 8 sample integration tests passed in combined run |
| T | T3 pipeline/web 回归 | ⏳ | 待跑 |
| E | E1 README 同步 | ⏳ | `README.md` |
| E | E2 FFCS docs 留底 | ✅ | `docs/M1-legal-redactor/` |
| E | E3 本地状态忽略 | ✅ | `.gitignore` |

## §5 · Step 执行日志

| Step | 起 commit | 止 commit | 交付规模 | 关键事件 |
|---|---|---|---|---|
| Spec · 五件套 | working tree | working tree | 5 docs | `/ffcs:spec M1-legal-redactor`; Gate 0a blocked by missing mandatory reviewer |
| Step 1 · 证据基线 | working tree | working tree | tests | `samples recent-errors --limit 30` 指向 `两种意见完整版.docx`; 关键回归 32 passed |
| Step 2 · 最新样本过滤 | working tree | working tree | 3 files | 扩展误人名/误机构过滤；LLM/兜底地名候选复用 false-location guard；全量测试 66 passed, 5 subtests passed |

## §6 · grep 留痕

### 6.1 · 产品流程 / restore / sample 字段

- **命令**:`rg -n "restore|restore_all|redaction_map|load_redaction_map_auto|docx|samples|recent-errors|linear|strategy|统一标准|全部还原|--profile|--restore-all" README.md legal_redactor scripts tests docs/LINEAR_REFACTOR.md`
- **实测时间**:`2026-06-10`

| # | 名称 | 文档分类 | 权威分类 | 权威源行号 | 动作 |
|---|---|---|---|---|---|
| 1 | 统一标准脱敏 | product-flow | product-flow | `README.md:47`, `README.md:77` | 保留 |
| 2 | Word 一键还原 | restore-docx | restore-docx | `README.md:93`, `scripts/restore_docx.py:15` | 保留 |
| 3 | `load_redaction_map_auto` | map-loader | map-loader | `legal_redactor/io.py:96` | 保留 |
| 4 | `restore_docx` | restore-docx | restore-docx | `legal_redactor/restore.py:21`, `web_app.py:974` | 保留 |
| 5 | `load_recent_error_samples` | sample-recency | sample-recency | `legal_redactor/_samples.py:199`, `cli.py:106` | 保留 |
| 6 | `created_at/updated_at/last_source` | sample-fields | sample-fields | `legal_redactor/_samples.py:110`, `legal_redactor/_samples.py:118` | 保留 |
| 7 | `strategy="legacy"` | compatibility | compatibility | `README.md:139`, `docs/LINEAR_REFACTOR.md:27` | 保留为回归入口 |

## §7 · 断路事件记录

| # | 时间戳 | 类型 | 上下文 | 尝试路径 | 诊断入口 |
|---|---|---|---|---|---|
| 1 | 2026-06-10 | Gate 0a reviewer unavailable | `claude` CLI missing; `codex` native subagent requires explicit user authorization under current tool policy | ran `review-runner.mjs run --reviewer claude ...`; runner returned `status=unavailable`, `error=missing_cli` | `.ff-state/reviews/M1-legal-redactor-gate0a/artifacts/claude-r0.json` |

## §8 · DoD 闭环条目

- [ ] 全部交付物已落档。
- [ ] 七层硬门槛证据齐。
- [ ] 关键 pytest 子集通过。
- [ ] 主审 Gate 2 review PASS。
- [ ] `_progress.md` DoD 闭环完成。

## §9 · SessionEnd 快照

| 时间戳 | 当前 Step | 工作区状态 | 待办 |
|---|---|---|---|
| 2026-06-10 | Step 2 | optimized filters for latest `两种意见完整版.docx` recent-errors; full tests passed | install/enable Claude CLI or authorize native Codex subagent review, then rerun Gate 0a |

## §10 · 决策日志

| # | 时间 | 决策 | 触发 | 影响 |
|---|---|---|---|---|
| 1 | 2026-06-10 | medium complexity | brownfield repo with CLI/Web/docx/sample surfaces | no POST_GA doc required |
| 2 | 2026-06-10 | filter construction/plumbing false names | latest recent-errors contained `水采暖`/`水配管`/`水管道`/`安装费` as person deletes | detector false-person rules now reject these domain phrases |
| 3 | 2026-06-10 | filter pure testing-service company cores | latest recent-errors contained `检测技术服务有限公司` as organization delete | organization core rules reject no-brand industry company names |
| 4 | 2026-06-10 | guard LLM location candidates | latest recent-errors included `重新确认` without location suffix | `LinearRuleEngine.accept_location` now reuses false-location guard |
| 5 | 2026-06-10 | restrict bare organization brand aliases | latest recent-errors contained bare brands such as `石家庄誉烁`/`盛信昊阳` derived from full company names | full company names still redact; bare brand aliases require explicit `以下简称/简称/下称`; `品牌公司` aliases still redact |
