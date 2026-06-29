# M3-startup-status-diagnostics · startup-status-diagnostics · HUMAN_TASKS

> **依据**:[README.md](README.md) + [EXECUTION_PLAN.md](EXECUTION_PLAN.md)
> **节奏**:只记录 AI 物理无法完成的事项和评审拍板项
> **版本**:v1.0 · 2026-06-27

---

## §A · 物理无法

### A.1 · 环境准备

- [ ] α-1.1 · Optional live Web/MLX smoke requires the local services to be running. Detection: `curl http://127.0.0.1:7860/health` and `curl http://127.0.0.1:18080/v1/models`. Fallback: run unit tests and record smoke as skipped with reason.

### A.2 · API key / 凭证注入

- [ ] α-2.1 · Optional live Office API smoke requires `LEGAL_REDACTOR_API_TOKEN` or local `api_token`. Detection: status probe reports configured token presence only. Fallback: verify missing-token diagnostic without live call.
- [ ] α-2.2 · Optional Discord send/thread live smoke requires a real bot token and command channel. Detection: status probe reports token/channel presence only. Fallback: do not send Discord messages in M3.

### A.3 · 第三方依赖 / CLI

- [ ] α-3.1 · Optional MLX live readiness requires `mlx_lm.server` installed. Detection: `command -v mlx_lm.server`. Fallback: status reports `missing_cli` and pure-rule fallback.

### A.4 · 跨平台前置

No cross-platform or remote-machine physical step is required for M3. Home Mac
Hermes live validation is deferred to M7.

### A.5 · webhook / 通知通道

No new webhook or notification channel is required for M3.

### A.6 · 拍板 / Trust

No user trust action is required for M3 beyond the existing local FFCS reviewer
configuration.

## §B · 评审拍板

### B.1 · Gate 0a 评审拍板项

No unresolved user choice is carried into Gate 0a. The review should decide
whether the spec is sufficiently scoped and safe.

### B.2 · Gate 0b 评审拍板项

Gate 0b is not required for this medium milestone unless Step 0 discovers that
the status design needs a new risky POC.

### B.3 · Step N 末 · Gate 2 / DoD 闭环评审拍板项

- [x] H-7.1 · Gate 2 build review decided the codex r0 HIGH was repaired and
  no remaining non-blocking findings need user action for M3.

### B.4 · 跨模块签字项

No external owner signoff is required at Gate 0a. Project-local downstream
milestones M4/M5/M7/M8 should reuse status outputs after M3 Gate 2.

### B.5 · 本 milestone 完成出口拍板

- [x] H-7.E.1 · M3 Gate 2 PASS with effective `codex + grok` artifacts.

### B.6 · 断路上抛拍板项

No current blocker. If the same probe design fails three times or live
credentials become required to proceed, record a new H-B item then.

## §C · 签字状态

### Gate 0a · 五件套规划评审

- 评审池:`codex,grok`
- 状态:✅ PASS
- 主审:`codex chair`
- 合议结果:`codex-r1` PASS, `grok-r1` PASS, chair signoff PASS

### Gate 2 · DoD 闭环

- 评审池:`codex,grok`
- 状态:✅ PASS
- 主审:`codex chair`
- 合议结果:`codex-r1` PASS, `grok-r2` PASS, chair signoff PASS
