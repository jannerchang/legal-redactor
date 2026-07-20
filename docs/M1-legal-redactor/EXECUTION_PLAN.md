# M1-legal-redactor · legal-redactor · 执行计划

> **依据**:[`README.md`](README.md) + [`../../README.md`](../../README.md) + [`../LINEAR_REFACTOR.md`](../LINEAR_REFACTOR.md)
> **格式**:七层硬门槛 + 决策表 + Step 顺序 + 时间盒
> **schema 引用**:[`gate.schema.md`](/Users/example/Downloads/forge-flow-ffcs-1.0.74/plugins/ffcs/templates/gate.schema.md)
> **版本**:v0.1 · `2026-06-10`

## §1 · 七层硬门槛(本 milestone 特化)

### D 层 · 数据与契约

- [ ] **D1 · 映射表全量还原契约**
  - description: `restore_text()`、`preview_restore()`、`restore_docx()` 均忽略旧 `restore_all=False` 的局部还原语义，恢复全部 mapping entries。
  - evidence_required: `code_path_read`, `unit_test_count`
  - pass_condition: `tests/test_restore.py` 证明 `restore_all=False` 仍全量还原。
  - block_severity: BLOCKER

- [ ] **D2 · Word 还原格式契约**
  - description: `.docx` 还原必须写出 `.restored.docx`，覆盖正文、表格、页眉、页脚。
  - evidence_required: `code_path_read`, `unit_test_count`
  - pass_condition: 临时 docx 回读后所有占位符被替换，输出扩展名仍为 `.docx`。
  - block_severity: BLOCKER

- [ ] **D3 · 样本时间戳契约**
  - description: `samples/_auto.sample.json` entries 保留 `created_at/first_seen_at/updated_at/last_seen_at/source/last_source`，最新错误检索不得只信任被污染的 `updated_at`。
  - evidence_required: `code_path_read`, `unit_test_count`
  - pass_condition: `load_recent_error_samples()` 测试覆盖 legacy file timestamp 和 per-entry timestamp。
  - block_severity: HIGH

- [ ] **D4 · 隐私边界契约**
  - description: 默认本地运行，不把文书原文上传外部网络；LLM 不可用时降级纯规则。
  - evidence_required: `doc_anchor`, `grep_stdout`
  - pass_condition: README 隐私章节存在，测试不依赖外部云 API。
  - block_severity: HIGH

### P 层 · 纯函数与局部规则

- [ ] **P1 · 长词优先还原**
  - description: overlapping placeholder 替换必须按位置和长词优先，避免短 placeholder 抢先替换。
  - evidence_required: `code_path_read`, `unit_test_count`
  - pass_condition: 相关 restore 单测覆盖 overlapping 或等价风险。
  - block_severity: HIGH

- [ ] **P2 · 最新误识别闭环**
  - description: 新规则优化必须从 `load_recent_error_samples()` / `samples recent-errors` 开始。
  - evidence_required: `grep_stdout`, `unit_test_count`
  - pass_condition: CLI 输出含 `updated_at type original source`，测试覆盖排序和 provenance。
  - block_severity: HIGH

- [ ] **P3 · 法律引用保留**
  - description: 规则调整不得破坏法律条文、案号结构和最高法案号保留策略。
  - evidence_required: `unit_test_count`, `grep_stdout`
  - pass_condition: pipeline/hebei/admin/case-number 相关测试通过。
  - block_severity: BLOCKER

### S 层 · 服务并发 / 一致性

- [ ] **S1 · 批量统一映射一致**
  - description: 批量文书使用同一个 unified redaction map，不让同一实体在多个文书中生成不同 placeholder。
  - evidence_required: `unit_test_count`, `code_path_read`
  - pass_condition: `tests/test_pipeline.py` batch cases 通过。
  - block_severity: HIGH

### N 层 · 通知回调

- 本地法律文书工具无通知回调，本 milestone 不适用。

### C+A 层 · CLI / API / UI

- [ ] **CA1 · CLI 入口一致**
  - description: `python -m legal_redactor` 与 `legal_redactor/cli.py` 的 restore 行为保持一致。
  - evidence_required: `code_path_read`, `unit_test_count`
  - pass_condition: 两个入口都调用 `load_redaction_map_auto()` + `restore_docx()` / `restore_text()`。
  - block_severity: HIGH

- [ ] **CA2 · Web restore 入口一致**
  - description: Web restore 对 `.docx` 默认保留 Word 格式，并提供 `.restored.docx` 下载。
  - evidence_required: `code_path_read`, `unit_test_count`
  - pass_condition: `web_app.py` restore 分支和 web tests 覆盖。
  - block_severity: HIGH

### T 层 · 测试与 CI

- [ ] **T1 · restore 单测**
  - evidence_required: `unit_test_count`
  - pass_condition: `.venv/bin/python -m pytest tests/test_restore.py`
  - block_severity: BLOCKER

- [ ] **T2 · samples 单测**
  - evidence_required: `unit_test_count`
  - pass_condition: `.venv/bin/python -m pytest tests/test_sample_integration.py`
  - block_severity: BLOCKER

- [ ] **T3 · pipeline/web 关键回归**
  - evidence_required: `unit_test_count`
  - pass_condition: `.venv/bin/python -m pytest tests/test_pipeline.py tests/test_web_app.py`
  - block_severity: HIGH

- [ ] **T4 · 全量测试可跑**
  - evidence_required: `unit_test_count`
  - pass_condition: `.venv/bin/python -m pytest`
  - block_severity: MEDIUM

### E 层 · 环境与文档

- [ ] **E1 · README 同步**
  - evidence_required: `doc_anchor`
  - pass_condition: README 描述统一标准、Word 一键还原、隐私边界。
  - block_severity: HIGH

- [ ] **E2 · FFCS docs 留底**
  - evidence_required: `doc_anchor`
  - pass_condition: `docs/M1-legal-redactor/` 五件套存在。
  - block_severity: MEDIUM

- [ ] **E3 · 本地状态忽略**
  - evidence_required: `grep_stdout`
  - pass_condition: `.gitignore` 忽略 `.ff-state/`、`.claude/`、`.codex/`。
  - block_severity: MEDIUM

## §2 · 决策表(D-XX)

| # | 决策 | 影响范围 | 来源 | 状态 |
|---|---|---|---|---|
| M1-legal-redactor.D-01 | 统一标准脱敏 + 全量还原 | CLI / Web / docs | README + memory | 锁 |
| M1-legal-redactor.D-02 | Word 还原保留 `.docx` 结构 | restore / scripts / Web | README + code | 锁 |
| M1-legal-redactor.D-03 | 最新样本优化先验证 provenance | samples / detectors / pipeline | memory + `_samples.py` | 锁 |
| M1-legal-redactor.D-04 | 全流程本地隐私边界 | LLM / IO / docs | README | 锁 |

### §2 附录 · 决策详情(D-XX 全字段)

| # | rationale | signoff_version | evidence_link |
|---|---|---|---|
| M1-legal-redactor.D-01 | 用户明确偏好单一路径；README 已写统一标准；旧兼容参数不应重新暴露 | v0.1 | `README.md:47`, `tests/test_restore.py:17` |
| M1-legal-redactor.D-02 | 法律文书含表格和页眉页脚，文本还原会破坏 Word 使用场景 | v0.1 | `README.md:93`, `legal_redactor/restore.py:21` |
| M1-legal-redactor.D-03 | 历史 timestamp 污染导致“最新样本”不可只看 updated_at | v0.1 | `legal_redactor/_samples.py:199`, memory recent-error optimization |
| M1-legal-redactor.D-04 | 法律文书和映射表包含敏感原文，默认必须本地化 | v0.1 | `README.md:148` |

## §3 · Step 顺序

### Step 1 · 证据基线

**时间盒**:`0.5 天`

- 运行 grep 自检，确认 CLI/Web/restore/sample 权威路径。
- 运行 restore + samples 测试子集。
- 记录当前失败，不做无证据重构。

**Checkpoint 1**:
- `_progress.md §6` 有 grep 留痕。
- 测试输出贴到 `_progress.md §4`。

### Step 2 · 小范围修复

**时间盒**:`1 天`

- 若 restore/docx 测试失败，只改 `restore.py`、CLI/Web restore 分支和脚本入口。
- 若 latest samples 失败，只改 `_samples.py` / CLI samples 输出和对应测试。
- 若法律引用泄漏，只改 detector/pipeline 的最小规则，并新增回归。

**Checkpoint 2**:
- 受影响测试子集全部通过。
- 决策表无新增未签字变更。

### Step 3 · 回归与文档同步

**时间盒**:`1 天`

- 跑 `tests/test_restore.py tests/test_sample_integration.py tests/test_pipeline.py tests/test_web_app.py`。
- 更新 README 或 docs，只反映已经验证的行为。
- 清理临时输出，确认 `.gitignore` 不遗漏本地 FFCS 状态。

### Step 4 · Gate 2 + handoff

**时间盒**:`0.5 天`

- 运行 `/ffcs:review --scope=build` 或等效 review-repair。
- 核验 required reviewer artifact 和 chair signoff。
- 写 `.ff-state/handoff/current.*`，next command 指向后续真实任务或 `<none>`。

## §4 · 时间盒细分

| Step | 估时 | 起止 commit | 备注 |
|---|---|---|---|
| Step 1 · 证据基线 | 0.5 天 | TBD | grep + pytest subset |
| Step 2 · 小范围修复 | 1 天 | TBD | 仅修失败证据 |
| Step 3 · 回归与文档同步 | 1 天 | TBD | 测试和 docs |
| Step 4 · Gate 2 + handoff | 0.5 天 | TBD | review + handoff |
| **总计** | **3 天** | | |

## §5 · 跨模块签字规则

本 milestone 不引入对外 API、DB schema、事件名或跨服务契约。影响面限定在本仓库 CLI/Web/restore/sample 内部模块，owner_signoffs 不适用。

## §6 · 服务端权威重算

不适用。本项目是本地 CLI/Web 工具，不接收客户端传入的服务端决策字段。涉及“分类/策略”的脱敏类型判断由本地 pipeline 根据原始文书文本和本地样本重算，不信任外部提交的分类结果。

## §7 · 文档维护扫(Gate 2 前 7 类)

- [ ] 1 · `_progress.md` 完整。
- [ ] 2 · README 仅同步已验证行为。
- [ ] 3 · 尾单落档到本 README 或后续 milestone。
- [ ] 4 · `docs/` 留底本 milestone。
- [ ] 5 · CLI/Web 指引与实际参数一致。
- [ ] 6 · 过时参数如 `--profile` / `--restore-all` 不回流用户帮助。
- [ ] 7 · `.gitignore` 确认 `.ff-state/` / `.claude/` / `.codex/`。

## §8 · 出口 checklist(本 milestone Gate 2)

- [ ] 全部交付物已落档。
- [ ] 七层硬门槛证据齐。
- [ ] 关键 pytest 子集通过。
- [ ] 主审 Gate 2 review PASS。
- [ ] `_progress.md` DoD 闭环完成。
