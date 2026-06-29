<!--
POST_GA opt-in is disabled by default. Enable during or after build only if the
user wants FFCS scheduled observation reminders for this milestone.
-->
---
enabled: false
milestone-id: M6-regression-measurement
---

# M6-regression-measurement · regression-measurement · POST_GA Observation(D+1/7/30/60)

> **依据**:[README.md](README.md)(complex milestone · POST_GA plan present at spec time)
> **复杂度**:complex due report schema, sample privacy, M5/M8 handoff, and cross-surface metrics
> **生命周期**:M6 Gate 2 PASS 后 24 小时内建档, D+60 关档
> **版本**:v1.0 · 2026-06-29

---

## §1 · 观察期目标

| 观察重点 | 关键指标 |
|---|---|
| Report privacy | No report, doc, PR, or handoff exposes raw sample entries, maps, originals, or restored full text |
| Metric usefulness | M6 report makes it clear whether a rule/sample change improved or regressed recognition |
| Newest-sample gate | Sample-driven tuning records freshness before changing rules |
| Saved-case timing | `document_input_to_saved_case_ms` is populated when timestamp evidence exists or clearly null with reason |
| M8 handoff | Runtime benchmark can consume M6 JSON fields without reworking schema |

## §2 · POST_GA 调度三层冗余说明

POST_GA D+1 / D+7 / D+30 / D+60 observation can be tracked through FFCS
handoff/session reminders when enabled. This document is present because the
milestone is complex, but `enabled: false` keeps scheduled reminders opt-in.

## §3 · Day-N 节(D+1 / D+7 / D+30 / D+60 通用结构)

### Day-N 触发条件

- M6 implementation merged or locally accepted after Gate 2 PASS.
- User or agent enables observation reminders if desired.

### Day-N 检查清单

- **Day-1**: focused regression tests pass; a synthetic report contains no raw
  sample/map/original/restored text.
- **Day-7**: at least one local measurement run helped choose or reject a
  sample/rule change, and saved-case timing is either populated from evidence
  or explicitly null with a useful reason.
- **Day-30**: M8 or runtime planning can consume M6 report fields without a
  schema rewrite.
- **Day-60**: close observation after privacy and metric lessons are folded
  into docs/memory if issues appeared.

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
- [ ] Any report privacy or metric-schema regression is hotfixed or recorded as an M6/M8 follow-up with evidence.

## §8 · 关联 .ff-state/post-ga-tasks.json schema

Observation task storage, if enabled during build closeout:

```json
[
  {
    "milestone_id": "M6-regression-measurement",
    "merged_at": "pending",
    "deploy_at": null,
    "checkpoints": [
      { "name": "D+1", "due_at": "pending", "completed_at": null, "notes": "" },
      { "name": "D+7", "due_at": "pending", "completed_at": null, "notes": "" },
      { "name": "D+30", "due_at": "pending", "completed_at": null, "notes": "" },
      { "name": "D+60", "due_at": "pending", "completed_at": null, "notes": "" }
    ],
    "owner": "project-local",
    "observation_doc": "docs/planning/legal-redactor-workflow-efficiency/milestones/M6-regression-measurement/POST_GA_OBSERVATION.md"
  }
]
```
