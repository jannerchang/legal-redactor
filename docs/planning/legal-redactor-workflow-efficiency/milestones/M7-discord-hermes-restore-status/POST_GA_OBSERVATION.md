<!--
POST_GA opt-in is disabled by default. Enable during or after build only if the
user wants FFCS scheduled observation reminders for this milestone.
-->
---
enabled: false
milestone-id: M7-discord-hermes-restore-status
---

# M7-discord-hermes-restore-status · discord-hermes-restore-status · POST_GA Observation(D+1/7/30/60)

> **依据**:[README.md](README.md)(complex/high-risk milestone · POST_GA plan present at spec time)
> **复杂度**:complex due private API, local MCP, local Web restore status, and cross-machine operator runbook
> **风险档**:high due client-related legal-document privacy, bearer-token-protected API, local path exposure risk, and optional live credentials
> **生命周期**:M7 Gate 2 PASS 后 24 小时内建档, D+60 关档
> **版本**:v1.0 · 2026-06-29

---

## §1 · 观察期目标

| 观察重点 | 关键指标 |
|---|---|
| Remote privacy | API/MCP/Discord defaults never expose restored full text, originals, map values, samples, tokens, or absolute Office paths |
| Status usefulness | A Discord thread id yields a clear status or next action for manifest, binding, map, latest restore, unresolved count, and Office/MCP reachability |
| Office authority | Restored output remains saved on Office Mac under the local case folder |
| MCP reliability | Home Mac Hermes can list tools and receive safe errors when Office API is missing/unreachable |
| Operator docs | Runbook smoke commands match implemented fields and separate required local tests from optional live checks |

## §2 · POST_GA 调度三层冗余说明

POST_GA D+1 / D+7 / D+30 / D+60 observation can be tracked through FFCS
handoff/session reminders when enabled. This document is present because M7 is
high risk, but `enabled: false` keeps scheduled reminders opt-in.

## §3 · Day-N 节(D+1 / D+7 / D+30 / D+60 通用结构)

### Day-N 触发条件

- M7 implementation merged or locally accepted after Gate 2 PASS.
- User or agent enables observation reminders if desired.

### Day-N 检查清单

- **Day-1**: focused API/MCP/Web tests pass; synthetic canary report proves no
  remote text/map/path/token leak; docs show implemented response schema.
- **Day-7**: optional live Office/Home MCP smoke is attempted if credentials are
  available; otherwise missing/unreachable diagnostics remain clear and safe.
- **Day-30**: at least one real or synthetic restore run confirms status fields
  remain useful and no absolute path/text leaks appear in logs or handoff.
- **Day-60**: close observation after privacy and cross-machine lessons are
  folded into README/deploy docs or memory if issues appeared.

### Day-N 关键指标

- 实测时间:pending.
- 异常记录:pending.
- 是否需 hotfix:pending.

### Day-N 出口

- PASS moves to next checkpoint.
- FAIL triggers a focused hotfix or a Gate review on the failing behavior.

## §7 · 出口标准

- [ ] D+1 checked or explicitly skipped.
- [ ] D+7 checked or explicitly skipped.
- [ ] D+30 checked or explicitly skipped.
- [ ] D+60 checked or explicitly skipped.
- [ ] Any remote privacy, safe-status, or operator-doc regression is hotfixed or recorded with evidence.

## §8 · 关联 .ff-state/post-ga-tasks.json schema

Observation task storage, if enabled during build closeout:

```json
[
  {
    "milestone_id": "M7-discord-hermes-restore-status",
    "merged_at": "pending",
    "deploy_at": null,
    "checkpoints": [
      { "name": "D+1", "due_at": "pending", "completed_at": null, "notes": "" },
      { "name": "D+7", "due_at": "pending", "completed_at": null, "notes": "" },
      { "name": "D+30", "due_at": "pending", "completed_at": null, "notes": "" },
      { "name": "D+60", "due_at": "pending", "completed_at": null, "notes": "" }
    ],
    "owner": "project-local",
    "observation_doc": "docs/planning/legal-redactor-workflow-efficiency/milestones/M7-discord-hermes-restore-status/POST_GA_OBSERVATION.md"
  }
]
```
