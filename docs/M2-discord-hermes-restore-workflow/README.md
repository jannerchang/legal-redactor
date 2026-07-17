---
milestone-id: M2-discord-hermes-restore-workflow
module: legal-redactor
version: v0.1
created: 2026-06-15
complexity: medium
risk: medium
---

# M2-discord-hermes-restore-workflow · legal-redactor · 模块门面

> **状态**:`起草中`
> **依据**:[`REQUIREMENTS.md`](REQUIREMENTS.md) + [`READINESS.md`](READINESS.md)
> **复杂度**:`medium`
> **风险档**:`medium`
> **时间盒**:`3-5 天`
> **上游**:`M1-legal-redactor`
> **下游**:`M3-discord-auto-posting`(建议)
> **版本**:v0.1 · `2026-06-15`

---

## 一、依据(上游)

- [`REQUIREMENTS.md`](REQUIREMENTS.md) · Office Mac 案件文件夹、Discord thread 绑定、Hermes 还原请求工作流。
- [`READINESS.md`](READINESS.md) · Tailscale/API token/Discord bot token 等准备项。
- [`../M1-legal-redactor/README.md`](../M1-legal-redactor/README.md) · 现有统一标准脱敏、映射表和 `.docx` 原格式还原约束。

---

## 二、目标(为什么做)

律师在本地脱敏客户或项目材料后，可以把已获授权的脱敏材料发送到受控协作帖子，供 Hermes 辅助整理事实、生成摘要并起草诉状、答辩状、代理意见等法律文书；需要恢复委托人或当事人真实信息时，Hermes 通过本地 MCP adapter 调用工作站，工作站根据 thread 找到本地 manifest 和映射表，自动还原法律文书草稿并保存到对应项目目录。AI 草稿必须由律师独立复核，不构成法律意见或裁判结论。

完成定义:

- 案件 manifest 能绑定 `case_folder` 与 `discord_thread_id`。
- 本地工作站能根据 `discord_thread_id` 定位唯一项目并使用本地映射表还原法律文书草稿。
- Home Mac MCP adapter 提供现有的 `restore_judgment_from_thread` 兼容工具和 `get_case_status_by_thread`；前者在公开说明中泛指法律文书草稿还原。
- 映射表、原始材料和还原后正文默认不离开本地工作站。
- 路径穿越、重复 thread 绑定、缺映射表和未知占位符都有测试覆盖。

---

## 三、范围(做什么)

### 3.1 In Scope

- 案件目录结构与 `manifest.json` schema。
- Web 脱敏流程新增案件文件夹名与 Discord thread URL 输入。
- 脱敏输出和加密映射表保存到案件目录。
- Office Mac FastAPI restore-by-thread API。
- Home Mac stdio MCP adapter，供 Hermes 调用还原和状态查询。
- 安全边界: bearer token、case root path guard、日志脱敏、临时文件清理。

### 3.2 Out of Scope

- 自动把脱敏文件发到 Discord 帖子，留给 `M3-discord-auto-posting`，除非用户先提供 bot token 并要求合并。
- 自动把还原后的法律文书发回 Discord，默认只保存在本地工作站。
- PDF 原格式还原。
- 自动识别案号作为主键。案号识别只能作为建议，主键仍由用户手填。
- Hermes/Discord bot 主体改造。M2 只提供本地 MCP adapter 和 API 契约。

### 3.3 关键交付物清单

| # | 文件路径 | 类型 | 备注 |
|---|---|---|---|
| 1 | `legal_redactor/cases.py` | 代码 | 案件 manifest、路径校验、thread lookup |
| 2 | `legal_redactor/remote_api.py` | 代码 | Office Mac restore/status API |
| 3 | `legal_redactor/mcp_adapter.py` | 代码 | Home Mac stdio MCP adapter |
| 4 | `legal_redactor/web_app.py` | 代码 | 脱敏表单接入 case folder + Discord URL |
| 5 | `tests/test_cases.py` | 测试 | manifest、路径、重复 thread |
| 6 | `tests/test_remote_api.py` | 测试 | restore-by-thread API |
| 7 | `tests/test_mcp_adapter.py` | 测试 | MCP 工具 schema + HTTP forwarding |
| 8 | `docs/deploy/hermes-office-restore.md` | 文档 | 双 Mac 部署、env、Hermes 配置 |

---

## 四、决策表(D-XX · 锁定项 / 可选项)

| # | 决策主题 | 取值 | rationale | signoff_version | evidence_link |
|---|---|---|---|---|---|
| `M2-discord-hermes-restore-workflow.D-01` | 案件主键来源 | 用户手填 `case_folder` | 用户明确担心案号识别失败；手填名称最稳定，识别只能辅助 | `v1.0` | `REQUIREMENTS.md#goal` |
| `M2-discord-hermes-restore-workflow.D-02` | Discord 绑定源 | `manifest.json` 保存 `discord_thread_id` | 还原时不让 Hermes 猜案号，Office Mac manifest 是本地权威 | `v1.0` | `REQUIREMENTS.md#manifest-contract` |
| `M2-discord-hermes-restore-workflow.D-03` | 映射表位置 | 永远留在 Office Mac | 映射表含原文恢复能力，不给 Hermes/Discord | `v1.0` | `REQUIREMENTS.md#security-and-privacy-requirements` |
| `M2-discord-hermes-restore-workflow.D-04` | 远程形态 | Home MCP adapter -> Office HTTP API | 跨两台 Mac，stdio MCP 不能直接跨机；adapter 隔离 Hermes 与 Office API | `v1.0` | `REQUIREMENTS.md#proposed-architecture` |
| `M2-discord-hermes-restore-workflow.D-05` | 首版输出 | 还原结果保存 Office Mac，返回路径/状态 | 避免误把还原后真实姓名发回 Discord | `v1.0` | `READINESS.md#initial-scope-recommendation` |
| `M2-discord-hermes-restore-workflow.D-06` | Discord 自动发帖 | 推迟到后续 milestone | 需要 bot token 和权限验证，避免阻塞核心还原链路 | `v1.0` | `READINESS.md#decision-checklist` |

### 4.1 可选项(待用户拍板)

- 无 Gate 0a 必须用户拍板项。Tailscale、API token、Discord bot token 属于执行期物理准备项，见 [`HUMAN_TASKS.md`](HUMAN_TASKS.md) §A。

---

## 五、七层硬门槛 / 选型

七层条数预估:

| 层 | 预估条数 | 备注 |
|---|---|---|
| D | 5 | manifest schema、thread 唯一性、mapping 留本地、输出命名、API schema |
| P | 4 | folder validator、Discord URL parser、lookup、unresolved token detector |
| S | 3 | atomic manifest write、并发输出不覆盖、临时文件清理 |
| N | 1 | Office API 不可达时 MCP 明确失败 |
| C+A | 4 | Web 表单、Office API、MCP tools、auth middleware |
| T | 5 | case/API/MCP/restore/web 回归 |
| E | 4 | env、部署文档、日志策略、handoff |

---

## 六、依赖图

```text
M1-legal-redactor
        |
        v
M2-discord-hermes-restore-workflow
        |
        +--> M3-discord-auto-posting
        +--> Hermes Discord bot workflow
```

---

## 七、上下游依赖

### 7.1 上游

- M1 提供统一映射表、`restore_text`、`restore_docx`、Web restore 入口。
- M2 不修改脱敏/还原算法语义，只编排案件目录、API 和 MCP adapter。

### 7.2 下游

- M3 可在 M2 manifest 和 case API 基础上实现 Discord 自动发帖。
- Hermes bot 可根据 M2 MCP adapter 暴露的工具调用还原。

---

## 八、风险 + 缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 绑定错 Discord thread | 还原用错映射表 | manifest 唯一 thread 检查 + Web UI 显示绑定摘要 |
| Office Mac 离线 | Hermes 无法还原 | MCP 返回明确 `office_unreachable`，用户稍后重试 |
| 未知占位符 | 法律文书草稿局部无法还原 | 返回 `unresolved_placeholders`，保存结果并标注 |
| 路径穿越 | 写出项目根目录 | folder validator + tempfile project root 测试 |
| 还原正文泄露到 Discord | 隐私风险 | D-05 默认只保存在本地工作站，不自动回传 |

---

## 九、时间盒

| Step | 估时 | 备注 |
|---|---|---|
| Step 0 · POC + 防护栏 | 0.5 天 | API/MCP 最小链路 smoke |
| Step 1 · Case manifest | 1 天 | schema、路径校验、lookup |
| Step 2 · Office API + Web 接入 | 1.5 天 | restore-by-thread、表单字段、保存目录 |
| Step 3 · Home MCP adapter | 1 天 | stdio tool + HTTP forwarding |
| Step 4 · 测试/文档/Gate 2 | 1 天 | pytest + deploy doc |
| **总计** | **3-5 天** | |

---

## 十、本 milestone 五件套清单

| 件 | 文件 | 说明 |
|---|---|---|
| 1 · README | [本文件](README.md) | 模块门面 |
| 2 · EXECUTION_PLAN | [EXECUTION_PLAN.md](EXECUTION_PLAN.md) | 七层硬门槛 + Step 顺序 |
| 3 · HUMAN_TASKS | [HUMAN_TASKS.md](HUMAN_TASKS.md) | 外部凭证与物理准备 |
| 4 · step-0-poc-report | [step-0-poc-report.md](step-0-poc-report.md) | POC smoke 计划 |
| 5 · _progress | [_progress.md](_progress.md) | Gate、grep、自检留痕 |
