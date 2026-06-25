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
- MLX 模型缓存：`/Volumes/SSD2T/.cache/huggingface`
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

Web 支持粘贴文本、拖拽 txt/md、上传 txt/md/doc/docx/pdf、多文件批量处理
（统一映射表）。脱敏时可以选填或自动识别案件文件夹；填写或绑定 Discord
帖子后，脱敏文本和加密映射表会保存到本地案件库，供后续 Hermes/Discord
还原工作流使用。

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
- Hermes 写回帖子链接后，Web 可自动把脱敏附件和附言发送到绑定帖子。
- Office Mac 只在本地保存原始材料、脱敏文件和加密映射表。
- Home Mac 的 Hermes 通过 MCP adapter 调用 Office 私网 API。
- 还原结果写回 Office Mac 的案件目录 `restored/`，MCP 响应不返回映射表或还原全文。
- 私网地址、token、案件根目录放在本机 JSON 配置中，不提交到 Git。
- 可选配置 Discord bot token 后，脱敏结果页可一键把脱敏文件作为附件发送到已填写的 Discord 帖子。

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
`mlx-lm`，并确保模型缓存位于 `/Volumes/SSD2T/.cache/huggingface`：

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

删除样本作为误识别黑名单使用，其他样本可作为 LLM 参考。短中文姓名这类高风险
负样本只保留给人工规则优化，不进入全局黑名单或 LLM 负例提示。样本不能让 LLM
生成原文中不存在的实体。

## 兼容模式

默认使用新的 `linear` 线性阅读策略。旧的候选池流水线仍保留用于回归：

```python
from legal_redactor.config import PipelineConfig

config = PipelineConfig(strategy="legacy")
```

## 隐私与安全

- Web 服务只监听 `127.0.0.1`
- 不调用任何云端 API，不向任何外部网络上传原文
- 脱敏映射表默认采用 AES-128-GCM 加密存储，密钥自动生成保存在 `~/.config/legal-redactor/key`
- 映射表可用于受控恢复，是否恢复由调用方明确决定
- 远程还原 API 必须通过私网和 bearer token 访问；API/MCP 响应不返回映射表内容

## 支持格式

- 输入：`.txt` / `.md` / `.doc` / `.docx` / `.pdf`
- 输出：脱敏文本、加密映射表、可选 Word 还原文件
