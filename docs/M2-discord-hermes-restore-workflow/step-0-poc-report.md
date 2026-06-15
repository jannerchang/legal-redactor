# M2-discord-hermes-restore-workflow · legal-redactor · Step 0 · POC Report

> **依据**:[`README.md`](README.md) + [`EXECUTION_PLAN.md`](EXECUTION_PLAN.md) §3 Step 0
> **状态**:`v0.1 实测落档`
> **版本**:v0.1 · `2026-06-15`

---

## 一、POC 范围

| # | POC | 主审签字条件 | 来源 | fallback 优先级 |
|---|---|---|---|---|
| 1 | Office API restore-by-thread smoke | 必跑 | `EXECUTION_PLAN.md` Step 0.1 | fallback:仅本机 CLI restore |
| 2 | MCP adapter HTTP forwarding smoke | 必跑 | `EXECUTION_PLAN.md` Step 0.2 | fallback:Hermes 手动调用 HTTP API |
| D | Defense · path/auth/log guard | 必装 | 安全边界 | 无 fallback |

---

## 二、POC 1 · Office API restore-by-thread smoke

### 目标

- 验证 Office API 能用 bearer token 保护。
- 验证临时 case root 中可通过 `discord_thread_id` 找到 mapping 并还原 draft。
- 验证响应不包含 mapping values。

### 实测脚本

```bash
.venv/bin/python -m pytest tests/test_remote_api.py
```

### 验证标准

- [ ] unauthorized 请求被拒绝。
- [ ] unknown thread 返回结构化错误。
- [ ] valid thread 还原文本并保存到 restored 目录。
- [ ] response 不含 mapping 原文。

### 实测结果

- `Office Mac/local` · `2026-06-15` · `PASS`
- 证据:`.venv/bin/python -m pytest tests/test_remote_api.py` -> 3 passed。

### Fallback 决议

- ① 若 FastAPI TestClient 依赖缺失，先跑函数级测试。
- ② 若 HTTP API 暂缓，先提供 CLI restore-by-thread。
- ⛔ 禁止:把 mapping 表传给 Hermes。

---

## 三、POC 2 · MCP adapter HTTP forwarding smoke

### 目标

- 验证 stdio MCP adapter 能读取 env。
- 验证工具参数包含 `discord_thread_id` 和 draft。
- 验证 Office API 不可达时返回明确错误。

### 实测脚本

```bash
.venv/bin/python -m pytest tests/test_mcp_adapter.py
```

### 验证标准

- [ ] tool schema 可列出。
- [ ] mock Office API 收到 bearer token。
- [ ] 连接失败返回 `office_unreachable`。

### 实测结果

- `Home Mac/local mock` · `2026-06-15` · `PASS`
- 证据:`.venv/bin/python -m pytest tests/test_mcp_adapter.py` -> 4 passed。

### Fallback 决议

- ① Hermes 先手动调用 HTTP API。
- ② 暂时用本地 CLI adapter 脚本替代 MCP。

---

## 四、Defense · path/auth/log guard

### 目标

- 防止 case folder 路径穿越。
- 防止未授权 API 调用。
- 防止日志写入原文、还原正文或 mapping values。

### 实测脚本

```bash
.venv/bin/python -m pytest tests/test_cases.py tests/test_remote_api.py
```

### 验证标准

- [ ] path traversal 测试 PASS。
- [ ] bearer token 测试 PASS。
- [ ] response/log assertion 不含 mapping values。

### 实测结果

- `Office Mac/local` · `2026-06-15` · `PASS`
- 证据:`.venv/bin/python -m pytest tests/test_cases.py tests/test_remote_api.py` -> 7 passed。

---

## 十、出口 Gate 0b checklist

- [x] POC 1 标记 `非阻塞`。
- [x] POC 2 标记 `非阻塞`。
- [x] Defense 标记 `非阻塞`。
- [x] 阻塞项已上抛或 fallback 落档。
- [x] 修订项已回写 [`EXECUTION_PLAN.md`](EXECUTION_PLAN.md)。
