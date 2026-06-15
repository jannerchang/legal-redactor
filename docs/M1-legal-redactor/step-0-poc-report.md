# M1-legal-redactor · legal-redactor · Step 0 POC Report

> **版本**:v0.1 · `2026-06-10`
> **复杂度**:`medium`

## 结论

本 milestone 不需要复杂级 POC。未知点主要是现有行为是否仍被测试覆盖，放入 Step 1 的证据基线处理。

## E-1 · Word 还原 smoke

- 状态:待 Step 1 验证
- 命令:

```bash
.venv/bin/python -m pytest tests/test_restore.py
```

- fallback:若缺少 `.docx` 覆盖，补临时 docx 回读测试。

## E-2 · 最新样本 smoke

- 状态:待 Step 1 验证
- 命令:

```bash
.venv/bin/python -m pytest tests/test_sample_integration.py
.venv/bin/python -m legal_redactor.cli samples recent-errors --limit 10
```

- fallback:若 recent list provenance 不可信，先修 `_samples.py` 时间戳保留逻辑。
