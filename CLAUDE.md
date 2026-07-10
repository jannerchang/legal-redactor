# legal-redactor

This is a brownfield Python project for legal document redaction and restoration.

## Project Instructions

- Preserve legal citations and statutory references during redaction, especially references such as Article 177.
- Prefer the existing Python package layout under `legal_redactor/`.
- Use `.venv/bin/python -m pytest ...` for tests in this repository.
- Keep Word document restoration workflows structure-preserving.

## FFCS

Forge Flow commands use the local FFCS configuration in `.claude/ffcs.local.md`.

Recommended next command:

```text
/ffcs:spec <milestone-id>
```

## Agent skills

### Issue tracker

Issues and PRDs are tracked in GitHub Issues via the `gh` CLI; external PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repo: use root `CONTEXT.md` and root `docs/adr/` for domain language and architecture decisions. See `docs/agents/domain.md`.
