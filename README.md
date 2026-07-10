# legal-redactor

完全本地运行的中文法律文书脱敏工具。系统按照人工处理文书的方式，
从前向后阅读，读到明确实体后生成全文替换规则。

这是一个纯 vibe 项目，适合交给 AI agent 按文档部署、检查和维护：
使用者不需要会写代码或读代码，只要描述目标和确认结果；代码、案件材料、映射表
和还原结果都留在本机或私网机器上，agent 负责按文档配置服务、检查连通性、
绑定 Discord thread，并通过 MCP 调用受控还原工具。推荐让 agent 直接执行部署步骤，
尤其是 Home Mac 上的 Hermes MCP 配置、Office Mac 私网 API、Tailscale ACL 和本地
JSON 配置，避免手动复制 token/IP 到仓库文件。

详细设计见 [线性阅读重构说明](docs/LINEAR_REFACTOR.md)。

## v0.1.2 架构更新

`v0.1.2` 把候选发现、实体确认和流程编排拆成三个职责明确的深模块，目标是让后续新增 detector、调整 LLM 审核或修改掩码规则时，只改真正拥有该行为的模块：

- `CandidateCollector.collect(context)` 是候选发现的唯一生产接口，统一处理规则、HanLP、行政区划种子和 LLM 精确候选的顺序、offset 与去重；内部 helper 不再作为第二套公开接口。
- `LinearRuleEngine.discover(text, candidates, analysis)` 只负责先应用 LLM reject/calibrate，再处理 span 冲突、确认实体并扩展确定性映射；不再导入或调用 detector。
- `RedactionPipeline.redact` / `redact_many` 保持为稳定入口，负责固定正则、样本/base 映射、行政区划 span gate、LLM 编排、后处理和结果组装。
- 删除未接入运行时的 `detector_registry`，避免维护者把新 detector 接到不会生效的错误 seam。
- 非主 LLM 路径只执行一次规则发现；审核完成后仅追加 LLM 精确候选，不再重新扫描整篇法律文书。

本次改动保持外部调用方式、Web/CLI 入口、样本库运行时行为和失败降级策略不变。合并前聚焦回归覆盖候选顺序、offset、同姓编号、机构别名、行政区划优先级、LLM 校准顺序、fail-closed 短路和 Web 离线兜底。

详细职责和不变量见 [线性阅读重构说明](docs/LINEAR_REFACTOR.md)。

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

系统只采用一套统一标准，不需要选择档位。它覆盖人名、地名、机构/公司/项目、
身份证号、手机号、银行账号、信用代码、邮箱地址和案号省份简称映射。

### 法院名与案号的特殊过滤规则

1. **法院名处理**：法院名只替换地名部分，保留法院层级。例如：`某省某市中级人民法院` $\rightarrow$ `甲省乙市中级人民法院`（使用抽象符号替换），不处理审判组织人员名。
2. **案号脱敏规则**：
   * **最高人民法院案号**：原样保留（如：`〔2024〕最高法民终...`）。
   * **其他地区法院案号**：为了保留文书的司法特征（如审级和年份），案号的结构予以保留，但将其中的**省份简称进行随机且一致的映射替换**。例如：原文中多处出现的 `（2025）豫01民终...` 中的 `豫` 字会被随机且在全文中一致地替换为其他省份简称（如 `粤`、`苏` 等）。

## 实测运行环境

当前生产使用环境如下，供复现部署时参考：

- 设备：Mac mini，Apple M4 Pro
- CPU：12 核（8 个性能核心、4 个能效核心）
- 内存：24 GB
- 系统：macOS 26.5.1
- Python：3.13.2（项目 `.venv`）
- MLX 运行时：`mlx_lm.server`
- 固定本地审核模型：`mlx-community/Qwen3.5-9B-MLX-4bit`（约 5.6 GB）
- MLX 模型缓存：`~/.cache/huggingface`
- MLX 服务端口：`127.0.0.1:18080`
- 默认 Web 端口：`127.0.0.1:7860`
- Office 私网还原 API 端口：建议 `127.0.0.1:8787` 或 Tailscale 私网地址绑定

实际使用中，Web 端固定调用 MLX Qwen3.5 9B 做整句语义识别和候选审核；
该模型服务不可用或调用失败时，
系统降级为纯规则模式，仍可完成基础脱敏、映射保存、MCP 还原和 Discord 发帖流程。

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

`start.sh` 会创建/复用 `.venv`，检查 Web 依赖，启动或复用
`127.0.0.1:18080` 上的 MLX Qwen3.5 9B 服务，然后启动 WebUI。启动脚本会通过
`/v1/models` 确认端口上响应的是目标 Qwen 模型；如果端口被其他服务占用会直接报错。
如果只想临时跳过 MLX，可设置 `LEGAL_REDACTOR_SKIP_MLX=1 ./start.sh`。

首页会显示一个只读系统状态区，也可直接访问机器接口：

```bash
curl http://127.0.0.1:7860/health
curl http://127.0.0.1:7860/api/status
curl http://127.0.0.1:18080/v1/models
```

`/api/status` 检查 Web 运行配置、固定 MLX 模型、`mlx_lm.server`、`HF_HOME`
本地缓存、案件库目录、Office API、Hermes MCP 和 Discord 指令通道。状态读取
不会启动模型、清理缓存、发送 Discord 消息或写入案件文件；响应只返回是否配置
和下一步动作，不返回 token、原文、样本、映射表或还原全文。

Web 支持粘贴文本、拖拽 txt/md、上传 txt/md/doc/docx/pdf、多文件批量处理
（统一映射表）。脱敏时可以选填或自动识别案件文件夹；填写或绑定 Discord
帖子后，脱敏文本和加密映射表会保存到本地案件库，供后续 Hermes/Discord
还原工作流使用。

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

### Hermes / Discord 远程还原

本功能用于 Home Mac 上的 Hermes/Discord 和 Office Mac 上的本地脱敏系统协作：

- Web 脱敏时可绑定案件文件夹和 Discord 帖子链接，生成 `manifest.json`。
- Web 脱敏后也可以填写案由，一键请求 Hermes 新建 Discord 案件帖。
- Hermes 写回帖子链接后，Web 可自动把脱敏附件发送到绑定帖子。
- Office Mac 只在本地保存原始材料、脱敏文件和加密映射表。
- Home Mac 的 Hermes 通过 MCP adapter 调用 Office 私网 API。
- 还原结果写回 Office Mac 的案件目录 `restored/`，MCP 响应不返回映射表或还原全文。
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
# 编辑 ~/.config/legal-redactor/mcp.local.json，填入 Office API 私网地址和 token。
LEGAL_REDACTOR_MCP_CONFIG=~/.config/legal-redactor/mcp.local.json \
  .venv/bin/python -m legal_redactor.mcp_adapter
```

Hermes 工具调用只传 Discord thread id 和判决稿；Office Mac 根据本地
`manifest.json` 找到案件映射表并保存还原结果。详细部署见
[`docs/deploy/hermes-office-restore.md`](docs/deploy/hermes-office-restore.md)。

## 本地 LLM

Web 启动脚本固定使用 MLX Qwen3.5 9B，不再在页面提供模型选择。首次部署需安装
`mlx-lm`，默认模型缓存位于本机 `~/.cache/huggingface`；如需临时改位置可设置
`HF_HOME`：

```bash
uv tool install mlx-lm --python /opt/homebrew/bin/python3.11
bash scripts/start_mlx9b_server.sh
```

默认由 MLX Qwen3.5 9B 处理整句实体识别和低置信候选审核；模型服务不可用时
自动降级为纯规则模式。启动脚本会用 `/v1/models` 做模型级探活，避免误把其他
占用同端口的进程当作 MLX 服务。LLM 不负责控制全文替换。

当前 Web 端固定使用这一个模型，不再提供 9B/27B 或自定义模型选择。旧的
Ollama 模型不参与默认流程。

## HanLP 本地 NER

Web 脱敏页可启用 HanLP 本地 NER 作为高速候选生成器。HanLP 只负责补充
人名、地名、机构名候选，候选仍会进入现有线性规则、样本黑名单和 LLM
校验流程；不会直接绕过映射规则。

HanLP 是可选依赖，未安装时系统会跳过并继续使用现有规则。当前 HanLP
兼容 `transformers<5`，项目的可选依赖已固定该约束：

```bash
.venv/bin/pip install '.[hanlp]'
```

默认模型名为 `MSRA_NER_ELECTRA_SMALL_ZH`。首次启用时 HanLP 会下载本地模型，
因此需要预留磁盘空间和网络时间。

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

## 支持格式

- 输入：`.txt` / `.md` / `.doc` / `.docx` / `.pdf`
- 输出：脱敏文本、加密映射表、可选 Word 还原文件
