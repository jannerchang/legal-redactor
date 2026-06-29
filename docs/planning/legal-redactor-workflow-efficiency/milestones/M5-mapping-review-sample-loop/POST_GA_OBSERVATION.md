<!--
POST_GA opt-in is disabled by default. Enable during or after build only if the
user wants FFCS scheduled observation reminders for this milestone.
-->
---
enabled: false
milestone-id: M5-mapping-review-sample-loop
---

# M5-mapping-review-sample-loop · mapping-review-sample-loop · POST_GA Observation(D+1/7/30/60)

> **依据**:[README.md](README.md)(complex milestone · POST_GA plan present at spec time)
> **复杂度**:complex due 7-10 day time box, Web/sample/M6 cross-surface work, and >20 hard gates
> **生命周期**:M5 Gate 2 PASS 后 24 小时内建档, D+60 关档
> **版本**:v1.0 · 2026-06-29

---

## §1 · 观察期目标

| 观察重点 | 关键指标 |
|---|---|
| Sample-save safety | No reported unsafe global delete sample; short-person and province abbreviation guards still pass focused tests |
| Review context preservation | Mapping review save does not drop current rows, filters, reasons, or case context in daily use |
| M6 handoff usefulness | M6 can consume M5 summary keys without re-parsing sensitive sample files |
| Sensitive-data boundary | No `samples/_auto.sample.json`, maps, originals, or restored full text are tracked, staged, pushed, or pasted into docs |

## §2 · POST_GA 调度三层冗余说明

POST_GA D+1 / D+7 / D+30 / D+60 observation can be tracked through FFCS
handoff/session reminders when enabled. This document is present because the
milestone is complex, but `enabled: false` keeps scheduled reminders opt-in.

## §3 · Day-N 节(D+1 / D+7 / D+30 / D+60 通用结构)

### Day-N 触发条件

- M5 implementation merged or locally accepted after Gate 2 PASS.
- User or agent enables observation reminders if desired.

### Day-N 检查清单

- **Day-1**: focused sample/Web tests pass; browser smoke confirms filter +
  sample-save context preservation; sensitive-data audit clean.
- **Day-7**: daily use reports no context-drop or unsafe sample-save issue; M6
  spec/build can read M5 handoff fields.
- **Day-30**: M6 regression measurement has either consumed M5 summary fields or
  recorded an explicit schema change request.
- **Day-60**: close observation after lessons are folded into docs/memory if
  sample-save or review-context issues appeared.

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
- [ ] Any unsafe sample-save or context-loss regression is hotfixed or recorded as an M6/M5 follow-up with evidence.

## §8 · 关联 .ff-state/post-ga-tasks.json schema

Observation task storage, if enabled during build closeout:

```json
[
  {
    "milestone_id": "M5-mapping-review-sample-loop",
    "merged_at": "pending",
    "deploy_at": null,
    "checkpoints": [
      { "name": "D+1", "due_at": "pending", "completed_at": null, "notes": "" },
      { "name": "D+7", "due_at": "pending", "completed_at": null, "notes": "" },
      { "name": "D+30", "due_at": "pending", "completed_at": null, "notes": "" },
      { "name": "D+60", "due_at": "pending", "completed_at": null, "notes": "" }
    ],
    "owner": "project-local",
    "observation_doc": "docs/planning/legal-redactor-workflow-efficiency/milestones/M5-mapping-review-sample-loop/POST_GA_OBSERVATION.md"
  }
]
```
