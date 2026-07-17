# HanLP `MSRA_NER_ELECTRA_SMALL_ZH` 评估说明

## 结论

`MSRA_NER_ELECTRA_SMALL_ZH` 是 HanLP 官方登记的中文命名实体识别模型。官方资料能证明的范围是：它采用 ELECTRA-small，使用 MSRA 数据训练，覆盖 26 个实体类型，并在 HanLP 所指的 MSRA 评测条件下报告 F1 95.16。官方模型注册表和文档没有证明它在本项目的法律文书、候选合并规则、脱敏映射或最终脱敏结果上具有同等准确率。

本仓库目前只能证明该模型已经被接入为一个**可选候选生成器**，并且若干下游候选优先级、校准和冲突行为有测试覆盖；仓库中没有受控的“关闭 HanLP”与“启用 HanLP”配对 gold 评估结果。因此，现阶段不能声称启用该模型提高了本项目的准确率、召回率、F1 或实际脱敏价值。是否有运行时价值，必须通过同一 gold set、同一配置的受控 A/B 评估来判断。

## 官方资料能够确认的模型事实

HanLP 的官方预训练 NER 文档将该模型列为 `hanlp.pretrained.ner.MSRA_NER_ELECTRA_SMALL_ZH`，并说明其采用 ELECTRA-small、训练数据为 MSRA、覆盖 26 个实体类型，官方条目报告 F1 为 95.16。这些信息可在两处相互核对：

1. [HanLP 官方预训练 NER 文档](https://hanlp.hankcs.com/docs/api/hanlp/pretrained/ner.html)
2. [HanLP 官方源码中的预训练 NER 注册表](https://github.com/hankcs/HanLP/blob/master/hanlp/pretrained/ner.py)

该官方成绩适用于 HanLP 所述的 MSRA 评测设置，而不是本项目的法律文书、标签裁剪、候选过滤、冲突消解、最终映射或泄漏检测。将其外推为本项目准确率属于未经验证的域迁移推断。

## 本仓库实际集成和边界

- `PipelineConfig.enable_hanlp_ner` 默认关闭；HanLP 还是可选依赖。
- `hanlp_ner.py` 先加载 `COARSE_ELECTRA_SMALL_ZH` 分词器，再加载 NER 模型；其分词器来源见 [HanLP 官方 tokenizer 注册表](https://github.com/hankcs/HanLP/blob/master/hanlp/pretrained/tok.py)。
- 适配层只保留本项目的 `person`、`location`、`organization` 标签；未知标签、短于两个字符或无法定位的 span 被丢弃。
- 输出只是 `source="hanlp_ner"` 的候选；仍会经过 profile、行政区划覆盖排除、候选优先级、LLM reject/calibrate 和 `LinearRuleEngine` 接受规则。固定 `confidence=0.88` 是集成常量，不是模型概率或项目评估结果。
- `CandidateCollector` 曾在收到 HanLP 机构候选后抑制本地机构规则，因此评价必须比较**完整 pipeline 输出**，而不能只数原始 NER span。

现有 `source="hanlp_ner"` 单测只验证手工构造候选的优先级和 LLM 校准顺序，并不实际运行模型或计算其准确率。规划文件也明确记录缺少 HanLP 开关/项目后缀特征测试。通用 `evaluate_gold_file()` 可以计算单一配置的 TP、FP、FN、precision、recall、F1，但目前没有 paired HanLP A/B 报告。

## 受控 A/B 评估协议

1. 采用人工标注且可用于本地评估的法律文书 gold set，固定输入/gold 的 ID 与哈希、profile、代码和依赖版本、模型 ID、tokenizer、`hanlp_max_chars`，但报告只保存聚合指标和哈希，绝不保存文书、实体原文、模型路径、凭据或私人样本。
2. 仅改变一个变量：A 为 `enable_hanlp_ner=False`；B 为 `enable_hanlp_ner=True` 且模型固定为 `MSRA_NER_ELECTRA_SMALL_ZH`。首轮应同时关闭 LLM 以隔离 HanLP；再在同一稳定 LLM 条件下分层复验。
3. 以最终 `RedactionPipeline` 结果计算整体及按类型 TP/FP/FN、precision/recall/F1、边界/类型错误、最终映射差异、泄漏数、HanLP warning/失败数、耗时和峰值内存。重点审查 B 新增 FP 和 B 造成既有规则候选被抑制后的 FN。
4. 预先定义采纳门槛：B 的 recall 与 F1 可重复净提升、precision 不低于安全下限、关键类型不退化、无新增高风险泄漏，且资源和故障率可接受。否则保持关闭或删除。

## 评估状态

- **已证明**：官方模型来源与 MSRA 评测背景；本仓库的可选加载、候选转换和部分下游规则。
- **未证明**：法律文书上的 precision、recall、F1、泄漏减少、人工修正减少或总体运行时价值。
- **当前决定**：不以官方 F1 宣称本项目提升；只将 HanLP 保留为受约束的辅助候选源，并先修复已观察到的策略冲突和不应抑制确定性规则的问题。默认值在真实配对 gold A/B 通过前仍保持关闭。
