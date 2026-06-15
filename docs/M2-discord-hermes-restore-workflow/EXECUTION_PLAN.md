# M2-discord-hermes-restore-workflow · legal-redactor · 执行计划

> **依据**:[`README.md`](README.md) + [`REQUIREMENTS.md`](REQUIREMENTS.md)
> **格式**:七层硬门槛 + 决策表 + Step 顺序 + 时间盒 + 跨模块签字 + 文档维护扫
> **版本**:v0.1 · `2026-06-15`

---

## §1 · 七层硬门槛(本 milestone 特化)

### D 层 · 数据与契约

- [ ] **D-01 · Manifest schema**: `manifest.json` 含 `schema_version/case_folder/discord_thread_id/mapping_file/redacted_files/restored_dir`。证据:`tests/test_cases.py` schema case + `code_path_read`。
- [ ] **D-02 · Thread 唯一性**: 同一 `discord_thread_id` 在 case root 下只能匹配一个案件。证据:`tests/test_cases.py` duplicate case。
- [ ] **D-03 · Mapping 留本地**: API/MCP 响应不得返回 mapping 内容。证据:`tests/test_remote_api.py` response assertion。
- [ ] **D-04 · 输出不覆盖**: restored 输出使用 timestamp 或 collision-safe filename。证据:`tests/test_remote_api.py` double restore。
- [ ] **D-05 · API schema**: restore/status API 输入输出字段固定，错误码覆盖 missing map、unknown thread、duplicate thread、unauthorized。证据:`tests/test_remote_api.py`。

### P 层 · 纯函数

- [ ] **P-01 · Folder validator**: 拒绝绝对路径、`..`、空名和路径分隔符。证据:`tests/test_cases.py`。
- [ ] **P-02 · Discord URL parser**: 从 Discord thread URL 提取 `thread_id`，失败时返回清晰错误。证据:`tests/test_cases.py`。
- [ ] **P-03 · Case lookup**: `discord_thread_id -> manifest` 只返回唯一结果。证据:`tests/test_cases.py`。
- [ ] **P-04 · Unknown token scan**: restore 后返回未解析占位符列表。证据:`tests/test_remote_api.py`。

### S 层 · 服务并发与文件安全

- [ ] **S-01 · Atomic manifest write**: manifest 写入使用临时文件 + replace。证据:`code_path_read`。
- [ ] **S-02 · Restore 临时文件清理**: `.docx` 或上传草稿处理后删除临时文件。证据:`tests/test_remote_api.py`。
- [ ] **S-03 · 并发输出不覆盖**: 同案多次还原产生不同输出。证据:`tests/test_remote_api.py`。

### N 层 · 网络/通知

- [ ] **N-01 · Office 不可达错误**: MCP adapter 对连接失败返回结构化错误，不吞异常。证据:`tests/test_mcp_adapter.py`。

### C+A 层 · API + UI + Adapter

- [ ] **CA-01 · Web 字段接入**: 脱敏 Web 表单支持 case folder 与 Discord thread URL。证据:`tests/test_web_app.py`。
- [ ] **CA-02 · Office auth middleware**: Office API 校验 bearer token。证据:`tests/test_remote_api.py`。
- [ ] **CA-03 · Restore endpoint**: `POST /cases/by-discord-thread/{thread_id}/restore-text` 可用。证据:`tests/test_remote_api.py`。
- [ ] **CA-04 · MCP tools**: `restore_judgment_from_thread` 和 `get_case_status_by_thread` 暴露。证据:`tests/test_mcp_adapter.py`。

### T 层 · 测试

- [ ] **T-01 · Case 单测**: `.venv/bin/python -m pytest tests/test_cases.py`。
- [ ] **T-02 · API 单测**: `.venv/bin/python -m pytest tests/test_remote_api.py`。
- [ ] **T-03 · MCP 单测**: `.venv/bin/python -m pytest tests/test_mcp_adapter.py`。
- [ ] **T-04 · Restore 回归**: `.venv/bin/python -m pytest tests/test_restore.py`。
- [ ] **T-05 · Web 回归**: `.venv/bin/python -m pytest tests/test_web_app.py`。

### E 层 · 环境与文档

- [ ] **E-01 · Env 文档**: `LEGAL_REDACTOR_API_URL`、`LEGAL_REDACTOR_API_TOKEN`、case root 配置写入部署文档。
- [ ] **E-02 · 双 Mac Runbook**: Home Mac Hermes MCP + Office Mac API 启动步骤写入 `docs/deploy/hermes-office-restore.md`。
- [ ] **E-03 · 日志策略**: 文档和代码均说明不记录原文/还原正文/mapping values。
- [ ] **E-04 · Handoff 更新**: `.ff-state/handoff/current.*` 指向 `/ffcs:build M2-discord-hermes-restore-workflow` 或阻断原因。

---

## §2 · 决策表(D-XX)

| # | 决策 | 影响范围 | 来源 | 状态 |
|---|---|---|---|---|
| `M2-discord-hermes-restore-workflow.D-01` | 案件主键由用户手填 | Web/cases | 用户需求 | 锁 |
| `M2-discord-hermes-restore-workflow.D-02` | Manifest 绑定 Discord thread | cases/API | 需求文档 | 锁 |
| `M2-discord-hermes-restore-workflow.D-03` | Mapping 留 Office Mac | API/MCP | 隐私边界 | 锁 |
| `M2-discord-hermes-restore-workflow.D-04` | Home MCP adapter 转发 Office API | MCP/API | 双 Mac 架构 | 锁 |
| `M2-discord-hermes-restore-workflow.D-05` | 首版只保存 Office Mac | API/Discord | 防泄露 | 锁 |
| `M2-discord-hermes-restore-workflow.D-06` | Discord 自动发帖后置 | 下游 | 凭证未就绪 | 锁 |

### §2 附录 · 决策详情(D-XX 全字段)

详见 [`README.md`](README.md) §四。

---

## §3 · Step 顺序

### Step 0 · POC + 防护栏

**时间盒**:`0.5 天`

```text
Step 0.1 · Office API smoke
   - 验证 FastAPI app 可本地启动并校验 bearer token
   - 验证临时 case root 能 restore text

Step 0.2 · MCP adapter smoke
   - 验证 stdio tool schema 可列出
   - 验证 HTTP forwarding 可 mock
```

### Step 1 · Case manifest

**时间盒**:`1 天`

- 新增 `legal_redactor/cases.py`。
- 实现 folder validator、Discord URL parser、manifest load/save、thread lookup。
- 添加 `tests/test_cases.py`。

Checkpoint:

- `tests/test_cases.py` PASS。
- D-01/D-02/P-01/P-02/P-03/S-01 有证据。

### Step 2 · Office API + Web 接入

**时间盒**:`1.5 天`

- 新增 `legal_redactor/remote_api.py`。
- Web redaction 表单接入 case folder + Discord thread URL。
- 脱敏输出保存至案件目录，mapping 保存至 `mapping/redaction_map.enc`。
- restore-by-thread text endpoint。

Checkpoint:

- `tests/test_remote_api.py` PASS。
- `tests/test_web_app.py` 关键回归 PASS 或记录依赖缺失 fallback。

### Step 3 · Home MCP adapter

**时间盒**:`1 天`

- 新增 `legal_redactor/mcp_adapter.py`。
- 暴露 `restore_judgment_from_thread`、`get_case_status_by_thread`。
- 使用 `LEGAL_REDACTOR_API_URL` 和 `LEGAL_REDACTOR_API_TOKEN`。

Checkpoint:

- `tests/test_mcp_adapter.py` PASS。
- N-01/CA-04 有证据。

### Step 4 · 自审 + Gate 2

**时间盒**:`1 天`

- 跑 case/API/MCP/restore/Web 测试子集。
- 写 `docs/deploy/hermes-office-restore.md`。
- 更新 README 中使用说明。
- Gate 2 review-repair。

---

## §4 · 时间盒细分

| Step | 估时 | 起止 commit | 备注 |
|---|---|---|---|
| Step 0 · POC + 防护栏 | 0.5 天 | TBD | API/MCP smoke |
| Step 1 · Case manifest | 1 天 | TBD | cases.py + tests |
| Step 2 · Office API + Web | 1.5 天 | TBD | remote_api.py + web_app.py |
| Step 3 · MCP adapter | 1 天 | TBD | mcp_adapter.py |
| Step 4 · 自审 + Gate 2 | 1 天 | TBD | tests + docs |
| **总计** | **3-5 天** | | |

---

## §5 · 跨模块签字规则

| 跨模块变更 | 影响下游 | D-XX 决策 | owner_signoffs | 测试覆盖 |
|---|---|---|---|---|
| Office API restore/status contract | Home MCP adapter / Hermes | D-04/D-05 | user-owner | `tests/test_remote_api.py` + `tests/test_mcp_adapter.py` |
| Manifest schema | Discord auto-posting follow-up | D-02 | user-owner | `tests/test_cases.py` |

本项目为个人本地系统，外部 owner 不适用；用户即 owner。Gate 0a/Build final 需明确 API contract 未泄露 mapping values。

---

## §6 · 服务端权威重算

本 milestone 涉及 authorization、permission、routing、status 等关键字，不能信任客户端:

- [ ] D-05 · 客户端只传 `discord_thread_id` 和 draft，不传 `case_folder` 决策结果；Office API 服务端根据 manifest 权威查找案件。
- [ ] S-04 · 若 restore-by-thread 请求试图覆盖 case path 或 output path，API 拒绝并返回 `INVALID_INPUT`。

---

## §7 · 文档维护扫

- [ ] `_progress.md` 完整。
- [ ] README/部署文档更新双 Mac 使用方式。
- [ ] HUMAN_TASKS 中凭证准备项保持最新。
- [ ] `.gitignore` 不提交 token、case root、mapping。

---

## §8 · 出口 checklist

- [ ] 全部交付物已落档。
- [ ] Step 0 POC smoke 完成或 fallback 落档。
- [ ] 七层硬门槛证据齐。
- [ ] `milestone-doc-check.mjs --dir docs/M2-discord-hermes-restore-workflow` 0 残留。
- [ ] 测试子集 PASS。
- [ ] Gate 2 review-repair 达成或记录真实阻断。
