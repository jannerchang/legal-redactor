# M2-discord-hermes-restore-workflow · legal-redactor · HUMAN_TASKS

> **依据**:[`README.md`](README.md) + [`EXECUTION_PLAN.md`](EXECUTION_PLAN.md)
> **版本**:v0.1 · `2026-06-15`

---

## §A · 物理无法(用户必做 · AI 无法替代)

### A.1 · 环境准备

- [ ] α-1.1 · Home Mac 与 Office Mac 私网互通 · 检测:`curl http://<office-private-ip>:<port>/health` · fallback:先仅本机 smoke。
- [ ] α-1.2 · Office Mac 选择 case root 本地路径 · 检测:用户提供路径且目录可写 · fallback:开发期使用临时目录。
- [ ] α-1.3 · Hermes 能启动本地 MCP stdio server · 检测:Hermes 配置中注册 `legal-redactor` MCP · fallback:先用 CLI smoke。

### A.2 · API key / 凭证注入

- [ ] α-2.1 · `LEGAL_REDACTOR_API_TOKEN` 注入 Office API 和 Home MCP adapter · 检测:token 长度校验且不入 git · fallback:开发期测试 token。
- [ ] α-2.2 · `LEGAL_REDACTOR_API_URL` 注入 Home MCP adapter · 检测:adapter 能访问 `/health` · fallback:localhost。
- [ ] α-2.3 · Discord bot token · 检测:`DISCORD_BOT_TOKEN` 存在且 bot 可发帖 · fallback:本 milestone 不实现自动发帖。

### A.3 · 第三方依赖 / CLI

- [ ] α-3.1 · Tailscale 或等价私网通道可用 · 检测:Home Mac ping/curl Office Mac 私网地址 · fallback:同机开发。
- [ ] α-3.2 · Hermes 当前 Discord thread id 可传给 MCP · 检测:Hermes tool call 参数含 `discord_thread_id` · fallback:手动传 thread id。

### A.4 · 跨平台前置

- [ ] α-4.1 · Office Mac 服务绑定地址确认 · 检测:只绑定 localhost/Tailscale IP，不暴露公网 · fallback:localhost-only。

---

## §B · 评审拍板(评审组介入 · Gate 0a 内消化完)

### B.1 · Gate 0a 评审拍板项

- 无。架构决策已在 README D-01~D-06 锁定。

### B.2 · Gate 0b 评审拍板项

- [ ] H-0.B.1 · POC 若证明 Hermes 无法传 thread id，则改为由用户显式输入 case folder · `β review-signoff` · `urgency: before_step_1` · `expected_input: 同意 fallback` · `blocking: true`

### B.3 · Gate 2 / DoD 闭环评审拍板项

- [ ] H-7.1 · Gate 2 时确认是否把 Discord 自动发帖并入当前 milestone 或转入 M3 · `β review-signoff` · `urgency: gate_2_signoff` · `expected_input: 当前不并入/并入` · `blocking: false`

### B.4 · 跨模块签字项

- [ ] H-S.1 · Office API contract 影响 Home MCP adapter / Hermes · 用户 owner 签字 · Gate 2 前确认。

### B.5 · 本 milestone 完成出口拍板

- [ ] H-7.E.1 · M2 Gate 2 PASS 后允许进入实现 Discord 自动发帖的 M3。

---

## §C · 签字状态

### Gate 0a · 五件套规划评审

- 评审池:`codex, claude`(项目本地配置)
- 状态:⏳ 待启动
- 已知限制:`claude` CLI 当前不可用；`agy` 只能作为 advisory review，不算 FFCS claude lane。

### Gate 0b · POC 放行

- 状态:⏳ 待 Step 0 实测

### Gate 2 · DoD 闭环

- 状态:⏳ 待实装
