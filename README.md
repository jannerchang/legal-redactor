# legal-redactor

完全本地运行的中文法律文书脱敏工具。纯文本替换，不分析案情、不分类、不联网。

## 脱敏策略

两档可量化预设，每类实体独立开关：

| 策略 | 内容 |
|------|------|
| `minimal` | 仅最核心标识：人名 + 地名 + 身份证号 + 手机号 |
| `standard`（默认） | 深度去标识化：minimal + 机构/公司/项目 + 银行账号 + 信用代码 + 邮箱地址 + 案号省份简称映射 |

### 法院名与案号的特殊过滤规则

1. **法院名处理**：法院名只替换地名部分，保留法院层级。例如：`某省某市中级人民法院` $\rightarrow$ `甲省乙市中级人民法院`（使用抽象符号替换），不处理审判组织人员名。
2. **案号脱敏规则**：
   * **最高人民法院案号**：原样保留（如：`〔2024〕最高法民终...`）。
   * **其他地区法院案号**：为了保留文书的司法特征（如审级和年份），案号的结构予以保留，但将其中的**省份简称进行随机且一致的映射替换**。例如：原文中多处出现的 `（2025）豫01民终...` 中的 `豫` 字会被随机且在全文中一致地替换为其他省份简称（如 `粤`、`苏` 等）。

## 安装与启动

```bash
cd /Users/jannerchang/legal-redactor
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install cryptography
```

### Web 界面

```bash
.venv/bin/python -m legal_redactor --web
# 浏览器打开 http://127.0.0.1:7860
```

支持拖拽 txt/md 文件到文本框、上传 docx、多文件批量处理（统一映射表）。

### 命令行

```bash
# 标准脱敏（默认，含案号省简称替换与信用代码）
.venv/bin/python -m legal_redactor --profile standard 文件.txt

# 最小脱敏（仅人名地名人身份证手机号）
.venv/bin/python -m legal_redactor --profile minimal 文件.txt

# 纯规则（关闭本地 LLM 辅助验证）
.venv/bin/python -m legal_redactor --profile standard --llm off 文件.txt

# 指定输出目录
.venv/bin/python -m legal_redactor -o output/2026-05 文件.txt
```

## 本地 LLM

需安装 Ollama 并拉取模型：

```bash
ollama pull qwen3:30b   # 最大效果
ollama pull qwen3:8b    # 也可用 8B 极速运行
```

LLM 不可用时自动降级为纯规则模式，不影响主流程。提示词自动注入量化样本作为 few-shot 参考，积累越多越准。

## 量化样本

Web 结果页编辑映射表后点「保存为样本」，自动追加到 `samples/_auto.sample.json`。修改、删除、新增的记录全部保留：

- `keep`：确认的原文 $\rightarrow$ 占位符映射，下次直接命中
- `delete`：误匹配原文进黑名单，下次自动跳过
- `add`：手动补充的映射
- `modify`：修正后的映射

样本自动注入 LLM prompt，正则规则不受样本影响（格式固定的字段正则已够用）。

## 隐私与安全

- Web 服务只监听 `127.0.0.1`
- 不调用任何云端 API，不向任何外部网络上传原文
- 脱敏映射表默认采用 AES-128-GCM 加密存储，密钥自动生成保存在 `~/.config/legal-redactor/key`
- 系统不保留任何数据解密还原功能

## 支持格式

- 输入：`.txt` / `.md` / `.docx`
- 输出：脱敏文本、加密映射表
