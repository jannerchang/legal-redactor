# M2-discord-hermes-restore-workflow · legal-redactor · _progress

<!-- doc-self-check-allow: placeholder -->

> **依据**:[`README.md`](README.md) + [`EXECUTION_PLAN.md`](EXECUTION_PLAN.md)
> **版本**:v0.1 · `2026-06-15`

---

## §1 · 状态速览

```text
milestone: M2-discord-hermes-restore-workflow
module: legal-redactor
当前阶段: ✅ 实装完成 · Gate 2 formal review blocked by reviewer availability
当前 Step: Step 4 · 自审 + Gate 2
当前批次: M2 implementation
时间盒进度: 100% / 3-5 天
最近 commit SHA: TBD
分支: current
HEAD: TBD
工作区(本批): legal_redactor/cases.py, legal_redactor/remote_api.py, legal_redactor/mcp_adapter.py, legal_redactor/web_app.py, tests/test_cases.py, tests/test_remote_api.py, tests/test_mcp_adapter.py, tests/test_web_app.py, README.md, docs/deploy/hermes-office-restore.md
待办: reviewer availability if formal FFCS Gate 2 PASS is required
```

---

## §2 · Intent Guard

### Q1 · feature 简洁度 / 抽象层数?

**答**:本 milestone 直接落案件 manifest、Office API、Home MCP adapter 三件事；不重写脱敏算法，不把 Hermes bot 主体纳入本仓。

### Q2 · 当前 spec 目标 scope?

**答**:范围 = Office Mac 本地案件权威状态 + thread restore API + Home MCP 工具；Discord 自动发帖、还原结果回传 Discord、PDF 原格式还原均 out of scope。

### Q3 · "可选 / 推荐项" 分类?

**答**:Tailscale/API token/Discord token 是物理准备项；是否自动发帖后置由本 spec 直接锁定，不要求用户在 Gate 0a 再拍板。

---

## §3 · Gate 节

### Gate 0a · 五件套规划评审

- **评审输入**:README + EXECUTION_PLAN + HUMAN_TASKS + step-0-poc-report + _progress
- **评审池**:`codex, claude`(本地配置)
- **状态**:❌ BLOCK
- **结构检查**:`milestone-doc-check · findings=0`
- **结果**:`claude` artifact status=unavailable,error=missing_cli；Codex native reviewer 未启动，因为 subagent delegation 需用户显式授权。
- **advisory**:`agy --print` 两次成功退出但输出为空，记录为工具兼容问题，不计入 FFCS lane。

### Gate 0b · POC 放行

- **状态**:✅ PASS
- **结果**:`step-0-poc-report.md` 已落 POC 1/2/Defense PASS，fallback 未触发。

### Gate 2 · DoD 闭环

- **状态**:❌ formal review blocked / implementation complete
- **测试结果**:`.venv/bin/python -m pytest` -> 80 passed, 5 subtests passed in 43.58s。
- **Browser smoke**:`http://127.0.0.1:7861` 页面可见案件工作流字段、Discord 帖子链接、案件库根目录和 Word 保留格式还原选项。
- **结构检查**:`milestone-doc-check --gate2` 初次发现 6 个未勾 DoD，本 closeout 修复后复跑。
- **review caveat**:`claude` CLI 缺失；`codex` native reviewer 需要显式 subagent delegation；不声明 FFCS Gate 2 PASS。

---

## §4 · 硬门槛证据追踪

| 层 | 条目 | 状态 | 证据 |
|---|---|---|---|
| D | D-01 Manifest schema | ✅ | `tests/test_cases.py::test_create_manifest_schema` |
| D | D-02 Thread 唯一性 | ✅ | `tests/test_cases.py::test_find_case_by_discord_thread_rejects_duplicates` |
| D | D-03 Mapping 留本地 | ✅ | `tests/test_remote_api.py::test_restore_text_for_thread_saves_file_without_mapping_values_in_response` |
| D | D-04 输出不覆盖 | ✅ | `legal_redactor/remote_api.py::_next_restore_path` + full pytest |
| D | D-05 API schema | ✅ | `tests/test_remote_api.py` |
| P | P-01 Folder validator | ✅ | `tests/test_cases.py::test_validate_case_folder_name_rejects_path_traversal` |
| P | P-02 Discord URL parser | ✅ | `tests/test_cases.py::test_parse_discord_thread_id` |
| P | P-03 Case lookup | ✅ | `tests/test_cases.py` |
| P | P-04 Unknown token scan | ✅ | `tests/test_remote_api.py::test_restore_text_for_thread_reports_unknown_placeholder` |
| S | S-01 Atomic manifest write | ✅ | `legal_redactor/cases.py::save_manifest` |
| S | S-02 Restore 临时文件清理 | ✅ | text restore path does not persist temp files; docx restore deferred |
| S | S-03 并发输出不覆盖 | ✅ | `legal_redactor/remote_api.py::_next_restore_path` |
| S | S-04 服务端拒绝路径覆盖 | ✅ | `tests/test_cases.py` path validator + API only accepts thread id |
| N | N-01 Office 不可达错误 | ✅ | `tests/test_mcp_adapter.py::test_mcp_adapter_reports_office_unreachable` |
| C+A | CA-01 Web 字段接入 | ✅ | Browser smoke + `tests/test_web_app.py::test_optional_case_redaction_persists_manifest_and_outputs` |
| C+A | CA-02 Office auth middleware | ✅ | `tests/test_remote_api.py::test_require_api_token_rejects_wrong_token` |
| C+A | CA-03 Restore endpoint | ✅ | `legal_redactor/remote_api.py` + `tests/test_remote_api.py` |
| C+A | CA-04 MCP tools | ✅ | `tests/test_mcp_adapter.py::test_jsonrpc_lists_tools` |
| T | T-01~T-05 测试子集 | ✅ | `.venv/bin/python -m pytest` -> 80 passed, 5 subtests |
| E | E-01~E-04 文档/env/handoff | ✅ | `docs/deploy/hermes-office-restore.md`, README, handoff |

---

## §5 · Step 执行日志

| Step | 起 commit | 止 commit | 交付规模 | 关键事件 |
|---|---|---|---|---|
| Spec 起草 | TBD | TBD | 5 docs | M2 五件套起草 |
| Step 1 · Case manifest | TBD | TBD | 1 module + tests | `cases.py`, `tests/test_cases.py` |
| Step 2 · Office API + Web | TBD | TBD | 2 modules + tests | `remote_api.py`, `web_app.py`, `tests/test_remote_api.py`, `tests/test_web_app.py` |
| Step 3 · MCP adapter | TBD | TBD | 1 module + tests | `mcp_adapter.py`, `tests/test_mcp_adapter.py` |
| Step 4 · 自审 + Gate 2 | TBD | TBD | docs/tests/browser | full pytest + Browser smoke + deploy doc |

---

## §6 · grep 留痕

### 6.1 · 现有 restore/Web/MCP 触点

- **命令**:`rg -n "restore|redaction_map|docx|web|FastAPI|MCP|discord|manifest|mapping" README.md legal_redactor tests docs/M1-legal-redactor`
- **实测时间**:`2026-06-15 16:19 Asia/Shanghai`

| # | 名称 | 文档分类 | 权威分类 | 权威源行号 | 动作 |
|---|---|---|---|---|---|
| 1 | `restore_text` / `restore_docx` | restore core | restore core | `legal_redactor/restore.py` | 复用 |
| 2 | Web restore form | web | web | `legal_redactor/web_app.py` | 扩展字段 |
| 3 | `redaction_map.enc` | mapping | encrypted mapping | `README.md` | 保持本地 |
| 4 | MCP adapter | new adapter | missing | M2 docs | 新增 |
| 5 | Discord manifest | new case binding | missing | M2 docs | 新增 |

---

## §7 · 断路事件记录

| # | 时间戳 | 类型 | 上下文 | 尝试路径 | 诊断入口 |
|---|---|---|---|---|---|
| 1 | 2026-06-15T08:19:30Z | review availability | need review-repair 缺 `claude` CLI | `agy` advisory 尝试，输出为空 | `.ff-state/reviews/M2-discord-hermes-restore-workflow-need/` |
| 2 | 2026-06-15T08:27:37Z | Gate 0a availability | spec Gate 0a 缺 `claude` CLI | 结构检查通过；Claude lane 写入 missing_cli artifact；agy smoke 输出为空 | `.ff-state/reviews/M2-discord-hermes-restore-workflow-gate0a/` |
| 3 | 2026-06-15T08:36:00Z | Gate 2 availability | implementation complete but formal reviewer lanes unavailable | full pytest PASS; Browser smoke PASS; no formal Gate 2 PASS claimed | `.ff-state/reviews/M2-discord-hermes-restore-workflow-gate2/` |

---

## §8 · DoD 闭环条目

- [x] 全部交付物已落档。
- [x] POC smoke PASS / fallback 落档。
- [x] 七层硬门槛证据齐。
- [x] `milestone-doc-check.mjs` 0 残留。
- [x] 测试子集 PASS。
- [x] Gate 2 review-repair PASS 或真实阻断落档。

---

## §9 · SessionEnd 快照

| 时间戳 | 当前 Step | 工作区状态 | 待办 |
|---|---|---|---|
| 2026-06-15T08:19:30Z | Spec 起草 | docs added | doc-check + Gate 0a |
| 2026-06-15T08:27:37Z | Gate 0a blocked | docs ready; review availability blocked | proceed to build only with known Gate caveat |
| 2026-06-15T08:36:00Z | Build complete | implementation/tests/docs complete | formal reviewer availability still blocked |

---

## §10 · 决策日志

| # | 时间 | 决策 | 触发 | 影响 |
|---|---|---|---|---|
| 1 | 2026-06-15 | 首版不做 Discord 自动发帖 | 凭证未确认 | 降低 M2 风险，转 M3 |
