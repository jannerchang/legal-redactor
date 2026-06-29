# M4-guided-intake-case-binding · guided-intake-case-binding · HUMAN_TASKS

> **依据**:[README.md](README.md) + [EXECUTION_PLAN.md](EXECUTION_PLAN.md)
> **节奏**:只记录 AI 物理无法完成的事项和评审拍板项
> **版本**:v1.0 · 2026-06-29

---

## §A · 物理无法

### A.1 · 环境准备

- [x] α-1.1 · Optional browser smoke requires the Web UI to be running on the
  current code. Detection: `GET http://127.0.0.1:7860/health` and page load.
  Result: Web was restarted with current code; `/api/status`, homepage, suggest
  API, forged-field 400, and short `/redact` HTTP smoke all passed.

### A.2 · API key / 凭证注入

- [x] α-2.1 · Optional live Discord create/send smoke requires a real bot token
  and command channel. Detection: M3 status reports Discord configured.
  Result: live Discord remains unconfigured, so build used the planned fallback:
  mocked `_post_discord_channel_message` and `_post_discord_thread_file` in Web
  tests, including payload privacy assertions.

### A.3 · 第三方依赖 / CLI

No new third-party CLI is required for M4. Existing FFCS review requires
`codex` and `grok` reviewer lanes per `.claude/ffcs.local.md`.

### A.4 · 跨平台前置

No cross-platform or remote-machine physical step is required for M4. Home Mac
Hermes live restore validation remains M7 scope.

### A.5 · webhook / 通知通道

No new webhook or notification channel is required. M4 may use existing Discord
bot configuration only for optional live smoke.

### A.6 · 拍板 / Trust

No user trust action is required at spec time. Build may require user approval
only if it discovers that overwriting existing manifest/thread binding needs a
product policy beyond README D-05.

## §B · 评审拍板

### B.1 · Gate 0a 评审拍板项

- [x] H-0.1 · Gate 0a review decided the fixed state vocabulary,
  conflict/authoritative-recompute gates, and outbound metadata allowlist are
  sufficient for M4 build after r0 repair.

### B.2 · Gate 0b 评审拍板项

Gate 0b is not required unless Step 0 discovers a risky unknown in suggestion
scoring or manifest overwrite behavior.

### B.3 · Step N 末 · Gate 2 / DoD 闭环评审拍板项

- [x] H-7.1 · Gate 2 build review decides whether remaining non-blocking
  findings are absorbed, deferred to M7, rejected, or blocking.
  Result: chair signed PASS with `decision=pass_defer`; Grok MEDIUM/LOW
  findings are deferred hardening follow-ups, not M4 blockers.

### B.4 · 跨模块签字项

No external owner signoff is required for Gate 0a. Project-local owner signoff is
encoded in README D-02/D-05: local manifest authority and no silent thread
overwrite.

### B.5 · 本 milestone 完成出口拍板

- [x] H-0.E.1 · M4 Gate 0a PASS with effective `codex + grok` artifacts.
- [x] H-7.E.1 · M4 Gate 2 PASS with effective `codex + grok` artifacts.

### B.6 · 断路上抛拍板项

No current blocker. If suggestion/conflict design fails the same way three
times, or live Discord credentials become mandatory to finish tests, record a
new H-B item and upthrow.

## §C · 签字状态

### Gate 0a · 五件套规划评审

- 评审池:`codex,grok`
- 状态:✅ PASS
- 主审:`codex chair`
- 合议结果:`codex-r0` FAIL repaired, `codex-r1` PASS, `grok-r0` PASS, chair signoff PASS

### Gate 2 · DoD 闭环

- 评审池:`codex,grok`
- 状态:✅ PASS
- 主审:`codex chair`
- 合议结果:`codex-r0` FAIL repaired, `grok-r0` FAIL repaired,
  `codex-r1` PASS, `grok-r1` PASS, chair signoff PASS
  (`decision=pass_defer`)
