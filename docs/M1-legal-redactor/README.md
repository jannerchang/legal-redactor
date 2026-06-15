---
milestone-id: M1-legal-redactor
module: legal-redactor
version: v0.1
created: 2026-06-10
complexity: medium
---

# M1-legal-redactor · legal-redactor · 模块门面

> **状态**:`评审中`
> **依据**:`README.md` + `docs/LINEAR_REFACTOR.md` + FFCS init handoff
> **复杂度**:`medium`
> **时间盒**:`3 天`
> **上游**:`无`
> **下游**:`无`
> **版本**:v0.1 · `2026-06-10`

## 一、依据(上游)

- [`README.md`](../../README.md) § 工作原理 / 脱敏策略 / Word 一键还原 / 量化样本
- [`docs/LINEAR_REFACTOR.md`](../LINEAR_REFACTOR.md) § 线性阅读重构设计
- [FFCS handoff](../../.ff-state/handoff/current.md) · `/ffcs:init` 后续命令

## 二、目标(为什么做)

把当前法律文书脱敏工具收束成可持续迭代的一条标准工程链路：统一标准脱敏、映射表全量还原、Word 原格式还原、最新样本误识别闭环。完成后，后续规则优化可以直接按“新样本证据 -> 小范围修补 -> 回归验证”执行，不再重新讨论产品档位或还原策略。

完成定义:

- 单一标准流程保持不新增用户可选档位。
- `.docx` 还原继续覆盖正文、表格、页眉和页脚，并输出 `*.restored.docx`。
- 最新错误样本优化必须先证明 `source/last_source` 和时间字段可信。
- `.venv/bin/python -m pytest ...` 覆盖 restore、samples、pipeline、web 关键路径。
- Gate 2 前完成 FFCS review 证据和 handoff。

## 三、范围(做什么)

### 3.1 In Scope

- 固化统一标准脱敏和全量还原行为，避免重新引入 `--profile` / `--restore-all` 等用户选择。
- 补齐 `.docx` 原格式还原验证，覆盖 CLI、`python -m legal_redactor`、Web restore 和 `scripts/restore_docx.py`。
- 固化最新样本优化流程，使用 `load_recent_error_samples()` 或 `samples recent-errors`，并验证 `source/last_source` 后再改规则。
- 建立 M1 的测试命令、证据留痕、风险和回退路径。

### 3.2 Out of Scope

- 不引入云端 API 或外部网络上传文书。
- 不重写线性脱敏引擎架构。
- 不新增多档脱敏策略或用户选择流程。
- 不改变 `samples/_auto.sample.json` 的既有语义，除非实装期发现时间字段损坏且已有测试证明。

### 3.3 关键交付物清单

| # | 文件路径 | 类型 | 备注 |
|---|---|---|---|
| 1 | `legal_redactor/restore.py` | 代码 | 文本和 Word 还原核心 |
| 2 | `legal_redactor/__main__.py` / `legal_redactor/cli.py` | 代码 | CLI restore 与 samples recent-errors |
| 3 | `legal_redactor/web_app.py` | 代码 | Web 脱敏、映射编辑、Word 还原 |
| 4 | `legal_redactor/_samples.py` | 代码 | 样本保存、时间戳、最新错误读取 |
| 5 | `scripts/restore_docx.py` | 脚本 | Word 一键还原入口 |
| 6 | `tests/test_restore.py` / `tests/test_sample_integration.py` / `tests/test_pipeline.py` / `tests/test_web_app.py` | 测试 | 关键回归覆盖 |

## 四、决策表(D-XX · 锁定项 / 可选项)

| # | 决策主题 | 取值 | rationale | signoff_version | evidence_link |
|---|---|---|---|---|---|
| M1-legal-redactor.D-01 | 产品流程 | 统一标准脱敏 + 全量还原 | 用户先前已要求“不用选择，直接一套标准”；README 也声明统一标准 | v0.1 | `README.md:47`, memory unified standard |
| M1-legal-redactor.D-02 | Word 还原 | 保留原 `.docx` 结构和格式 | 法律文书常含表格、页眉页脚；旧文本 round-trip 不满足验收 | v0.1 | `README.md:93`, `legal_redactor/restore.py:21` |
| M1-legal-redactor.D-03 | 样本优先级 | 最新错误样本优先，先验 provenance | 仅 `updated_at` 曾被污染，必须核对 `source/last_source` | v0.1 | `legal_redactor/_samples.py:199`, memory recent errors |
| M1-legal-redactor.D-04 | 本地隐私 | 不调用云端 API，不上传原文 | README 隐私边界已明确；法律文书敏感 | v0.1 | `README.md:148` |

### 4.1 可选项(待用户拍板)

- 无。当前 milestone 的流程性选择由执行 agent 按项目既有约束自决。

## 五、七层硬门槛 / 选型

七层条数预估:

| 层 | 预估条数 | 备注 |
|---|---|---|
| D | 4 | 映射表、样本时间戳、docx 输出、隐私边界 |
| P | 3 | 还原函数、样本读取、长词优先替换 |
| S | 1 | 批量映射一致性和文件写入原子性检查 |
| N | 0 | 本地工具无通知回调 |
| C+A | 2 | CLI/Web/script 入口 |
| T | 4 | restore、sample、pipeline、web 回归 |
| E | 3 | README、FFCS docs、忽略规则 |

## 六、依赖图

```text
README.md + docs/LINEAR_REFACTOR.md
        |
        v
M1-legal-redactor · single standard + docx restore + recent sample loop
        |
        v
future sample-driven rule optimization
```

## 七、上下游依赖

### 7.1 上游

- 无外部 milestone 依赖。
- 现有代码和 README 是本 milestone 的事实来源。

### 7.2 下游

- 后续样本驱动优化必须继承本 milestone 的 recency provenance 规则。
- 后续 restore/UI 变更必须保持 `.docx` 原格式还原与全量还原语义。

## 八、风险 + 缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 最新样本时间戳再次被旧数据污染 | 错把旧误识别当今天问题 | 使用 `source/last_source` 和真实文件名交叉验证 |
| `.docx` run 被 Word 拆分 | 还原不完整或格式变化 | 保留脚本和单测覆盖 body/table/header/footer，必要时按 run 合并策略修复 |
| 统一标准被 UI/CLI 参数回流破坏 | 用户再次面对多档选择 | grep `--profile` / `--restore-all`，测试 help 文案 |
| LLM 不可用 | 脱敏质量波动 | 必须自动降级纯规则，测试不得依赖外部模型 |

## 九、时间盒

| Step | 估时 | 备注 |
|---|---|---|
| Step 1 · 现状证据与测试基线 | 0.5 天 | 跑关键 pytest 子集和 grep |
| Step 2 · 规则/restore/web 小修 | 1 天 | 仅基于失败证据改动 |
| Step 3 · 回归验证和文档同步 | 1 天 | pytest + README/FFCS 证据 |
| Step 4 · Gate 2 review + handoff | 0.5 天 | 评审证据与下一步 |
| **总计** | **3 天** | |

## 十、本 milestone 五件套清单

| 件 | 文件 | 说明 |
|---|---|---|
| 1 · README | [本文件](README.md) | 模块门面 |
| 2 · EXECUTION_PLAN | [EXECUTION_PLAN.md](EXECUTION_PLAN.md) | 七层硬门槛 + 决策表 + Step 顺序 |
| 3 · HUMAN_TASKS | [HUMAN_TASKS.md](HUMAN_TASKS.md) | α 物理无法 + β 评审拍板 |
| 4 · step-0-poc-report | [step-0-poc-report.md](step-0-poc-report.md) | 中等复杂度，无强制 POC |
| 5 · _progress | [_progress.md](_progress.md) | 状态、grep 留痕、Gate 证据 |
