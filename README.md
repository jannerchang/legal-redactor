# legal-redactor

面向律师、律所及其他获得授权的法律服务人员，完全本地运行的中文法律文书脱敏工具。
系统按照人工处理文书的方式，从前向后阅读，读到明确实体后生成全文替换规则，
便于在不暴露原始身份信息的前提下开展材料整理、检索、摘要和法律文书辅助起草。

这是一个纯 vibe 项目，适合交给 AI agent 按文档部署、检查和维护：
使用者不需要会写代码或读代码，只要描述目标和确认结果；代码、原始材料、映射表
和还原结果都留在本机或私网机器上，agent 负责按文档配置服务、检查连通性、
绑定协作 thread，并通过 MCP 调用受控还原工具。推荐让 agent 直接执行部署步骤，
尤其是本地 MCP、私网 API、访问控制和本地 JSON 配置，避免手动复制 token/IP 到仓库文件。

详细设计见 [线性阅读重构说明](docs/LINEAR_REFACTOR.md)。

> **用途边界**：本项目是面向律师工作场景的文书去标识化与辅助处理工具，不代表任何法院、
> 司法机关或任职单位。AI 输出仅供法律专业人员复核，不构成法律意见或裁判结论，不能替代
> 律师的专业判断，也不得用于未经授权的案件材料。未公开材料不得发送到公共 AI 或未经批准的
> 第三方服务；使用者应自行遵守保密、数据安全、个人信息保护及所在机构的内部制度。

## v0.2.0 全文识别更新

`v0.2.0` 默认使用 `qwen3.5-9b` 执行整篇文书双轮识别：首轮建立案件级实体登记表，第二轮重新阅读全文补充遗漏实体与明确的同一主体关系，再校验所有名称确实逐字存在于原文后生成确定性映射。

- Web、CLI 与配置工厂默认统一为 `full_document` 和 `qwen3.5-9b`，仍可按次切换模型或回退逐句窗口。
- 人名与机构采用两轮合并登记；身份证号、电话、银行账号、案号及通过 gate 的行政区划继续走确定性规则。
- 第二轮失败时保留首轮有效结果；首轮失败、无效或超过 120000 字符时明确回退逐句窗口，不截断原文。
- ModelManager 继续只接收逻辑模型 ID，支持模型切换回滚与 worker 自愈，不向应用或页面暴露权重路径。
- TXT 下载加入 UTF-8 BOM，兼容按系统默认编码打开中文文本的编辑器。

此前 `v0.1.2` 完成的候选发现、实体确认与流程编排分层仍保持不变：`CandidateCollector.collect(context)` 是候选发现入口，`LinearRuleEngine.discover(...)` 负责候选接受和映射扩展，`RedactionPipeline.redact` / `redact_many` 负责编排与降级。

## 工作原理

系统不是先对全文制造大量疑似候选再逐个排除，而是采用线性规则发现：

1. 从文首读取到事实认定部分结束。
2. 读到明确的人名、行政区划或机构全称时确认实体。
3. 立即建立该实体的全称和常见简称替换规则。
4. 继续向后阅读，已经确认的实体不再重复猜测。
5. 读完后按长词优先统一执行全文替换。

实现中不会真的反复改写原文。系统先累积替换表，最后统一替换，
这样生成的假名不会干扰后续阅读。

### 示例

以下人名、机构名和行政区划均为虚构，仅用于说明规则。

```text
林甲明（虚构）
-> 林某甲

示例省 / 示例
-> 甲省

示例省星河运输有限公司（虚构）
-> 甲省甲运输公司

星河公司 / 星河（虚构）
-> 甲公司 / 甲

某全国性银行示例省分行（虚构）
-> 某全国性银行甲省分行
```

普通公司保留建筑、设计、运输、物流等行业类别，只替换行政区划和字号。
银行、保险及公共机构优先保留机构品牌和类别，只替换其中已经确认的地名。

## 脱敏策略

默认自动范围是人名、机构/公司名、行政区划的省/市/区县、身份证号、手机号和案号省份简称映射。街道及以下地点、详细地址、项目/工程/楼盘、银行账号、统一社会信用代码和邮箱保留原文；需要处理时在映射审核页手动选取添加。

### 法院名与案号的特殊过滤规则

1. **法院名处理**：法院名只替换地名部分，保留法院层级。例如：`某省某市中级人民法院` $\rightarrow$ `甲省乙市中级人民法院`（使用抽象符号替换），不处理审判组织人员名。
2. **案号脱敏规则**：
   * **最高人民法院案号**：原样保留（如：`〔2024〕最高法民终...`）。
   * **其他地区法院案号**：为了保留文书的司法特征（如审级和年份），案号的结构予以保留，但将其中的**省份简称进行随机且一致的映射替换**。例如：原文中多处出现的 `（2025）豫01民终...` 中的 `豫` 字会被随机且在全文中一致地替换为其他省份简称（如 `粤`、`苏` 等）。

## 参考测试环境

以下是一个已验证的本地部署环境，仅供复现参考：

- 设备：Mac mini，Apple M4 Pro
- CPU：12 核（8 个性能核心、4 个能效核心）
- 内存：24 GB
- 系统：macOS 26.5.1
- Python：3.13.2（项目 `.venv`）
- 本地模型 API：`model-manager`，默认 `127.0.0.1:18080`
- 默认逻辑模型 ID：`qwen3.5-9b`（展示名：Qwen3.5 9B（MLX 4-bit））
- 已注册可选模型还包括 `bonsai-27b`（展示名：Ternary Bonsai 27B（MLX 2-bit））
- 默认 Web 端口：`127.0.0.1:7860`
- Office 私网还原 API：建议绑定 `127.0.0.1:8787`，通过 SSH 反向隧道暴露到 Home Mac 的 `127.0.0.1:18787`

应用和 Web 表单只向本地 `model-manager` 发送逻辑模型 ID。管理器通过 OpenAI-compatible `GET /v1/models` 公布当前可用模型，并把每次请求选择的 ID 映射到本机 MLX 权重；切换模型时会卸载当前 worker 后加载所选模型。权重路径不会出现在应用请求或 Web 页面中。模型 API 不可用时，系统明确提示并降级为纯规则模式，仍可完成基础脱敏、映射保存、MCP 还原和 Discord 发帖流程。

## 安装与启动

```bash
cd legal-redactor
./start.sh --install-deps
```

### Web 界面

```bash
./start.sh
# 浏览器打开 http://127.0.0.1:7860
```

`start.sh` 会创建/复用 `.venv`、检查 Web 依赖、复用或启动本地模型管理器，然后启动 WebUI。管理器只在首次推理请求时启动内部 MLX worker；设置 `LEGAL_REDACTOR_SKIP_MLX=1` 会跳过模型 API，并让 Web 使用纯规则模式。

首页会显示一个只读系统状态区，也可直接访问机器接口：

```bash
curl http://127.0.0.1:7860/health
curl http://127.0.0.1:7860/api/status
curl http://127.0.0.1:7860/api/model-status
curl http://127.0.0.1:18080/health
curl http://127.0.0.1:18080/v1/models
```

`/api/status` 检查 Web 运行配置、本地模型 API、案件库目录、Office API、Hermes MCP 和 Discord 指令通道；`/api/model-status` 只返回本地模型 API 状态。状态读取不会启动 worker、清理缓存、发送 Discord 消息或写入案件文件；响应只返回是否配置和下一步动作，不返回 token、原文、样本、映射表、权重路径或还原全文。

Web 支持粘贴文本、拖拽 txt/md、上传 txt/md/doc/docx/pdf、多文件批量处理
（统一映射表）。脱敏时可以选填或自动识别案件文件夹；填写或绑定 Discord
帖子后，脱敏文本和加密映射表会保存到本地案件库，供后续 Hermes/Discord
还原工作流使用。

首页默认选择“整篇文书（LLM 双轮补漏）”和 `qwen3.5-9b`。本地 LLM 首轮读取完整文书并返回案件级实体登记表，第二轮再次独立阅读全文，只补充首轮遗漏的人名、机构、行政区划及明确的同一主体关系；程序校验所有名称都逐字存在于原文后合并两轮登记、定位全部精确 span，并沿用现有确定性映射与替换流程。首轮成功但补漏失败时保留首轮有效结果；首轮失败、超限或无效登记表时明确回退逐句窗口。行政区划库以及身份证号、电话、银行账号、案号等确定性规则始终保留。全文模式单篇硬上限为 120000 字符，不截断。结果页只展示模式、逻辑模型 ID、状态、文档数、调用数、识别耗时、降级与冲突计数，不展示 prompt、response、实体登记表、证据或模型权重路径。TXT 下载使用 UTF-8 BOM，兼容按系统默认编码打开的编辑器。

脱敏结果页的映射表带有复核筛选：全部、低置信、手工新增、已修改、删除候选、
还原风险和样本复用。保存为样本时页面不会跳转，会在当前结果页显示本次保存摘要，
包括可复用映射、删除黑名单候选、被保护跳过项、人工校正总数、误识别删除和
漏识别新增。真实样本内容仍只保存在本机 `samples/` 目录，不写入文档或远端通知。

脱敏结果页会显示一个案件流程状态：`not_saved`（未保存）、`saved_local`
（本地已保存）、`bound_thread`（已绑定 Discord 帖子）、`sent_discord`
（已发送脱敏附件）、`waiting_hermes`（等待 Hermes 建帖写回）、`attach_failed`
（附件发送失败）。这些状态由服务端根据本地 manifest、线程链接和发送结果重算；
浏览器提交的 `state/status/bound/sent/conflict_result` 等字段会被拒绝。

### 命令行

```bash
# 按统一标准脱敏
.venv/bin/python -m legal_redactor 文件.txt

# 纯规则（关闭本地 LLM 辅助验证）
.venv/bin/python -m legal_redactor --llm off 文件.txt

# 指定输出目录
.venv/bin/python -m legal_redactor -o output/2026-05 文件.txt
```

还原不设档位，始终按映射表一次性还原全部条目。

### Word 一键还原

如果整理案件资料时需要把脱敏后的 Word 文档按映射表还原，并继续保留表格、
段落和原有格式，可以直接执行：

```bash
.venv/bin/python scripts/restore_docx.py 脱敏后.docx output/standard_llm_max-effect/redaction_map.enc
```

默认会在同目录输出 `脱敏后.restored.docx`。也可以指定输出路径：

```bash
.venv/bin/python scripts/restore_docx.py 脱敏后.docx redaction_map.enc --out 还原后.docx
```

同样也可以使用统一命令：

```bash
.venv/bin/python -m legal_redactor --restore redaction_map.enc 脱敏后.docx -o output/restored
```

该方式会直接在 Word 文档内部替换占位符，覆盖正文、表格、页眉和页脚。
如果 Word 将一个占位符拆成多个格式片段，还原文字会沿用占位符起始片段的格式。

### 私有协作与远程还原

本功能用于律师在受控协作空间中处理脱敏材料，并由本地脱敏系统保存和还原文书草稿：

- Web 脱敏时可绑定项目文件夹和协作帖子链接，生成 `manifest.json`。
- Web 脱敏后也可以填写项目标题，一键请求协作 agent 新建工作帖。
- agent 写回帖子链接后，Web 可自动把脱敏附件发送到绑定帖子。
- 工作站只在本地保存原始材料、脱敏文件和加密映射表。
- 协作 agent 通过 MCP adapter 调用私网 API。
- 还原结果写回本地项目目录 `restored/`，MCP 响应不返回映射表或还原全文。
- Office API / MCP 返回 `ok`、`code`、`case`、`restore`、`next_action` 结构；
  `restore` 只包含 `restored_filename`、`restored_relative_path`、替换数量、
  `unresolved_placeholder_count` 和时间元数据，不返回占位符数组、绝对路径或全文。
- 私网地址、token、案件根目录放在本机 JSON 配置中，不提交到 Git。
- 可选配置 Discord bot token 后，脱敏结果页可一键把脱敏文件作为附件发送到已填写的 Discord 帖子。
  发送到 Discord/Hermes 的建帖命令只包含请求 ID、案件目录/标题和脱敏附件元数据，
  不包含 `case_root`、`source_dir`、本地绝对路径、原文、映射表、样本或还原全文。

Office Mac 可以启动只面向私网的还原 API：

```bash
cp config/api.example.json ~/.config/legal-redactor/api.local.json
# 编辑 ~/.config/legal-redactor/api.local.json，填入本机案件根目录、API token；
# 如需一键发帖，再填入 discord_bot_token。
LEGAL_REDACTOR_API_CONFIG=~/.config/legal-redactor/api.local.json \
  .venv/bin/python -m uvicorn legal_redactor.remote_api:app --host 127.0.0.1 --port 8787
```

Home Mac 上的 Hermes 可通过本地 MCP adapter 调用：

```bash
cp config/mcp.example.json ~/.config/legal-redactor/mcp.local.json
# 编辑 ~/.config/legal-redactor/mcp.local.json，填入 Home Mac 上的反向隧道地址（默认 http://127.0.0.1:18787）和 token。
LEGAL_REDACTOR_MCP_CONFIG=~/.config/legal-redactor/mcp.local.json \
  .venv/bin/python -m legal_redactor.mcp_adapter
```

Hermes 工具调用只传协作 thread id 和法律文书草稿；本地工作站根据
`manifest.json` 找到项目映射表并保存还原结果。详细部署见
[`docs/deploy/hermes-office-restore.md`](docs/deploy/hermes-office-restore.md)。

## 本地模型管理器

唯一的对外模型端点是 `model-manager`，默认 `http://127.0.0.1:18080`。它公开 OpenAI-compatible `GET /v1/models` 和 `POST /v1/chat/completions`。Web 每次载入页面时读取模型列表，处理文书时提交本次选择的逻辑模型 ID；CLI 可使用 `--model` 指定同一个 ID。浏览器和命令行仍不接受任意权重路径。

管理器启动时会自动扫描 `~/Models/HuggingFace` 和 `~/.cache/huggingface/hub` 中包含 `config.json` 的本地模型；Hugging Face 缓存目录会转换为逻辑 ID，例如 `models--owner--model` 显示为 `owner/model`。因此以后下载到这些目录的新 MLX 模型，重启模型管理器后会自动出现在下拉列表，不需要改代码。内置的 `bonsai-27b` 和 `qwen3.5-9b` 保留更友好的短 ID 与展示名。

管理器本身通过 `scripts/start_model_manager.sh` 启动或复用。内部 MLX worker 默认仅监听 `127.0.0.1:18081`，由管理器按请求惰性拥有、切换和关闭；不要直接启动 worker。可通过以下环境变量分别覆盖本机监听地址，并可用 `LEGAL_REDACTOR_QWEN_MODEL` 覆盖 Qwen 模型的本地路径或 Hugging Face 仓库 ID：

```bash
LEGAL_REDACTOR_MODEL_MANAGER_HOST=127.0.0.1
LEGAL_REDACTOR_MODEL_MANAGER_PORT=18080
LEGAL_REDACTOR_MLX_WORKER_HOST=127.0.0.1
LEGAL_REDACTOR_MLX_WORKER_PORT=18081
LEGAL_REDACTOR_QWEN_MODEL=~/Models/HuggingFace/hub/models--mlx-community--Qwen3.5-9B-MLX-4bit/snapshots/<revision>
```

例如，先读取可选模型，再在请求中传入其中一个逻辑 ID：

```bash
curl -fsS http://127.0.0.1:18080/v1/models
curl -fsS http://127.0.0.1:18080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.5-9b","messages":[{"role":"user","content":"Return exactly {}"}],"stream":false,"temperature":0,"max_tokens":16}'
```

管理器或模型不可用时，应用显式使用纯规则模式；不会尝试 Ollama、Open WebUI 或其他后端。LLM 只负责整句实体识别和低置信候选审核，不负责控制全文替换。

CLI 可用 `--recognition-mode sentence_windows|full_document` 选择同一识别路径；默认仍为 `sentence_windows`。`full_document` 仅是实验选项，尚未通过人工盲评和配对 benchmark 门禁，因此不会自动成为默认值。要回滚实验路径，只需重新选择或传入 `sentence_windows`，无需改动模型管理器端口或恢复旧后端。
## HanLP 本地 NER

Web 脱敏页可启用 HanLP 本地 NER 作为候选生成器。HanLP 只负责补充人名、地名、机构名候选；候选仍会进入现有线性规则、候选消解和 LLM 校验流程，不会直接绕过映射规则。它默认关闭；尚无项目法律文书的配对 gold A/B 证据证明启用后能提升最终 precision、recall 或 F1。

HanLP 是可选依赖，未安装时系统会跳过并继续使用现有规则。当前 HanLP 兼容 `transformers<5`，项目的可选依赖已固定该约束：

```bash
.venv/bin/pip install '.[hanlp]'
```

默认模型名为 `MSRA_NER_ELECTRA_SMALL_ZH`。首次启用时 HanLP 会下载本地模型，因此需要预留磁盘空间和网络时间。模型的公开 MSRA F1 不能外推到本项目；完整结论和受控 A/B 协议见 [`docs/research/hanlp-ner-evaluation.md`](docs/research/hanlp-ner-evaluation.md)。

## 识别率评估与调试

可以用 gold set JSON 对脱敏结果做 Precision / Recall / F1 评估。gold set
只需要列出期望识别的实体；`type` 可选，填写后会按类型严格匹配：

```json
{
  "cases": [
    {
      "name": "case-001",
      "text": "原告张三与被告星河建设有限公司签订施工合同。",
      "expected": [
        {"type": "person", "original": "张三"},
        {"type": "organization", "original": "星河建设有限公司"}
      ]
    }
  ]
}
```

运行评估：

```bash
.venv/bin/python -m legal_redactor --eval-gold path/to/gold.json --eval-report output/eval-report.json
# 或禁用本地 LLM，只评估规则兜底：
.venv/bin/python -m legal_redactor --llm off --eval-gold path/to/gold.json
```

需要把评估结果、样本修正摘要和恢复占位符情况汇总成 M6 回归测量报告时，使用
`--regression-report`。该报告默认只包含聚合指标、每个 gold case 的数量字段、
样本文件元数据和本地耗时，不复制 `matched` / `missing` / `extra` 原始实体、
样本文本、映射表原文、还原全文或 debug trace：

```bash
.venv/bin/python -m legal_redactor \
  --llm off \
  --eval-gold path/to/gold.json \
  --eval-fail-under-recall 0.90 \
  --eval-fail-under-precision 0.90 \
  --regression-report output/regression-report.json \
  --regression-sample-summary output/sample-summary.json \
  --regression-sample-file samples/_auto.sample.json
```

如果已有脱敏文本和映射表，也可以补充恢复占位符计数；没有这两项证据时报告会把
`restore` 写为 `null`，不会猜测：

```bash
.venv/bin/python -m legal_redactor \
  --regression-report output/regression-report.json \
  --regression-redacted output/case.redacted.txt \
  --regression-map output/redaction_map.enc \
  --regression-input-at 2026-06-29T08:00:00+00:00 \
  --regression-saved-at 2026-06-29T08:01:30+00:00
```

### M8 运行时基准报告

比较 `mlx_lm.server`、Rapid-MLX、纯规则兜底或其他本地候选时，先为每个候选生成
同一 gold set / input set / profile 下的 M6 回归报告，再用
`--runtime-benchmark-report` 生成本地 JSON 基准报告。M8 只给出可复核的候选比较；
不会自动切换默认模型、`--llm` 默认值或启动脚本。

`benchmark_context` 必须对所有候选一致；如果 gold set、输入文档集合或 benchmark
profile 不匹配，报告会把推荐动作降为 `manual_review`：

```json
{
  "gold_set_id": "spc-public-v1",
  "gold_set_hash": "sha256-of-gold-manifest",
  "input_set_id": "public-spc-samples-v1",
  "input_set_kind": "public_spc_sample",
  "input_set_hash": "sha256-of-relative-path-manifest",
  "sample_provenance_id": "sample-meta-v1",
  "benchmark_profile": "m8-default-v1"
}
```

生成报告：

```bash
.venv/bin/python -m legal_redactor \
  --runtime-benchmark-report output/runtime-benchmark.json \
  --benchmark-context output/benchmark-context.json \
  --benchmark-candidate baseline mlx mlx-lm output/baseline-regression.json \
  --benchmark-candidate rapid-mlx mlx rapid-mlx output/rapid-regression.json
```

如果有本地探测数据，可为每个候选追加 observation JSON，记录 first-token、Web workflow、
peak memory、error rate 或 `/v1/models` identity 这类元数据：

```bash
.venv/bin/python -m legal_redactor \
  --runtime-benchmark-report output/runtime-benchmark.json \
  --benchmark-context output/benchmark-context.json \
  --benchmark-candidate baseline mlx mlx-lm output/baseline-regression.json \
  --benchmark-candidate rapid-mlx mlx rapid-mlx output/rapid-regression.json \
  --benchmark-observation baseline output/baseline-observation.json \
  --benchmark-observation rapid-mlx output/rapid-observation.json
```

M8 报告仍然是隐私安全边界：只保存标签、聚合指标、delta、reason 和模型 identity
元数据，不写入 `matched` / `missing` / `extra` 原始诊断、样本 entries、映射值、
还原正文、绝对 Office 路径、token、prompt/body 或 debug trace。现有 `samples/`
里的公开最高人民法院样本可以作为 M8 benchmark/test input，但报告中只能引用相对
路径清单的 hash 或类别，不复制文书正文。

命令行脱敏可加 `--debug-trace` 输出 `debug_trace.json`；Web 结果页也提供
`debug_trace.json` 下载按钮。该文件记录映射来源、置信度、复核候选、泄漏告警、
每个映射在各文件中的出现次数，适合排查漏识别或边界漂移。它和映射表一样包含原文
实体，不能上传到 Discord 或提交到 Git。

## 量化样本

Web 结果页编辑映射表后点「保存为样本」，自动追加到 `samples/_auto.sample.json`。修改、删除、新增的记录全部保留：

- `keep`：确认的原文到占位符映射
- `delete`：误匹配原文进黑名单，下次自动跳过；2 至 3 字、疑似常见中文姓名的
  `delete` 不会写入或生效为全局黑名单，避免污染其他案件中的真实当事人姓名
- `add`：手动补充的映射
- `modify`：修正后的映射

映射表编辑页可以在每条删除、修改、新增记录后填写“修改理由”，样本库会保存为
`reason` 字段，便于之后复盘误识别原因、优化规则和调整 LLM prompt。

删除样本作为误识别黑名单使用，其他样本可作为 LLM 参考。短中文姓名这类高风险
负样本只保留给人工规则优化，不进入全局黑名单或 LLM 负例提示。样本不能让 LLM
生成原文中不存在的实体。


## 隐私与安全

- Web 服务只监听 `127.0.0.1`
- 不调用任何云端 API，不向任何外部网络上传原文
- 脱敏映射表默认采用 AES-128-GCM 加密存储，密钥自动生成保存在 `~/.config/legal-redactor/key`
- 映射表可用于受控恢复，是否恢复由调用方明确决定
- 远程还原 API 必须通过私网和 bearer token 访问；API/MCP 响应不返回映射表内容
- 本项目定位于律师法律服务中的辅助处理；AI 结果必须由具备相应职责的专业人员独立复核
- 不处理国家秘密、审判执行工作秘密或其他依法、依约不得交由该系统处理的材料

## 支持格式

- 输入：`.txt` / `.md` / `.doc` / `.docx` / `.pdf`
- 输出：脱敏文本、加密映射表、可选 Word 还原文件
