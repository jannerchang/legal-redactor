<!--
POST_GA disabled for candidate-collection-architecture: risk=medium. File included because complexity=complex; enable only if later Gate 2 raises risk to high.
-->
---
enabled: false
milestone-id: candidate-collection-architecture
---

# candidate-collection-architecture · candidate-collector · POST_GA Observation

> **Basis**: [README.md](README.md), [EXECUTION_PLAN.md](EXECUTION_PLAN.md)
> **Complexity**: complex
> **Risk**: medium; POST_GA is not active unless risk is raised during build/review.
> **Version**: v1.0 · 2026-07-09

---

## §1 · Observation Scope

POST_GA is disabled by default for this milestone because the resolved risk is
`medium`. If Gate 2 raises risk to `high`, enable this file and observe:

| Focus | Metric |
|---|---|
| Candidate collection parity | No legal-entity leak regression in focused suite and manual smoke |
| LLM review fallback | Web `/redact` offline fallback remains non-blocking |
| Old seam deletion | No `detector_registry` or `collect_candidates` production relapse |
| Documentation durability | Future work reads collector/engine/pipeline responsibilities correctly |

## §2 · Disabled-state checklist

- [x] `enabled: false` in frontmatter.
- [x] No POST_GA scheduler entry is required at spec time.
- [ ] If risk becomes `high`, build phase must flip `enabled: true`, create scheduler entry, and fill D+1/D+7/D+30/D+60 sections.

## §3 · Future high-risk activation template

### Day-1

- [ ] Focused suite rerun after merge.
- [ ] Scoped grep confirms no old seam relapse.
- [ ] Web offline fallback smoke remains non-blocking.

### Day-7

- [ ] Any newly reported legal-redaction regression is triaged against candidate collection changes.

### Day-30

- [ ] Architecture docs still match runtime code after follow-up work.

### Day-60

- [ ] Close observation or create follow-up issue if collector seam drift appears.
