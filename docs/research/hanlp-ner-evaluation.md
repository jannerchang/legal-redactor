# HanLP `MSRA_NER_ELECTRA_SMALL_ZH` 评估说明

> **2026-07-26 status**: Historical evaluation record. HanLP and its optional dependency were removed because runtime discovery now requires successful full-document LLM registration for new semantic entities.

## 结论

`MSRA_NER_ELECTRA_SMALL_ZH` 是 HanLP 官方登记的中文命名实体识别模型。官方资料能证明的范围是：它采用 ELECTRA-small，使用 MSRA 数据训练，覆盖 26 个实体类型，并在 HanLP 所指的 MSRA 评测条件下报告 F1 95.16。官方模型注册表和文档没有证明它在本项目的法律文书、候选合并规则、脱敏映射或最终脱敏结果上具有同等准确率。

本仓库曾将该模型接入为可选候选生成器，但没有受控的关闭/启用配对 gold 结果；它现已退出运行时发现路径。因此，现阶段不能声称 HanLP 提高本项目的准确率、召回率、F1 或实际脱敏价值。

## 官方资料能够确认的模型事实

HanLP 的官方预训练 NER 文档将该模型列为 `hanlp.pretrained.ner.MSRA_NER_ELECTRA_SMALL_ZH`，并说明其采用 ELECTRA-small、训练数据为 MSRA、覆盖 26 个实体类型，官方条目报告 F1 为 95.16。这些信息可在两处相互核对：

1. [HanLP 官方预训练 NER 文档](https://hanlp.hankcs.com/docs/api/hanlp/pretrained/ner.html)
2. [HanLP 官方源码中的预训练 NER 注册表](https://github.com/hankcs/HanLP/blob/master/hanlp/pretrained/ner.py)

该官方成绩适用于 HanLP 所述的 MSRA 评测设置，而不是本项目的法律文书、标签裁剪、候选过滤、冲突消解、最终映射或泄漏检测。将其外推为本项目准确率属于未经验证的域迁移推断。

## 历史集成边界

- 旧 `hanlp_ner.py` 适配器、可选依赖、`PipelineConfig` 开关和 Web 表单均已删除。
- 旧适配层只保留 `person`、`location`、`organization` 标签，固定 `confidence=0.88` 也不是模型概率或项目评估结果。
- 当前生产候选收集器不会加载或调用 HanLP。

旧 `source="hanlp_ner"` 单测只验证手工候选的接受边界，不证明真实模型或最终脱敏质量。

## 若未来重新评估

1. 先建立人工标注且可用于本地评估的法律文书 gold set，只保存聚合指标和哈希，不保存文书、实体原文、模型路径、凭据或私人样本。
2. 在独立实验分支比较全文 LLM 基线与 HanLP 候选注入版本；不得把实验开关直接恢复到生产 Web/CLI。
3. 以最终 `RedactionPipeline` 结果计算整体及按类型 TP/FP/FN、precision/recall/F1、边界/类型错误、泄漏数、耗时和峰值内存。
4. 只有 recall 与 F1 可重复净提升、precision 不低于安全下限且无新增高风险泄漏，才可另行提出运行时架构变更。

## 评估状态

- **已证明**：官方模型来源与 MSRA 评测背景；旧适配层的候选转换行为。
- **未证明**：法律文书上的 precision、recall、F1、泄漏减少、人工修正减少或总体运行时价值。
- **当前决定**：HanLP 不参与运行时发现；新语义实体必须来自成功的全文登记。
