# M2-discord-hermes-restore-workflow · Readiness Checklist

## Decision Checklist

| Item | Status | Owner | Evidence / Notes |
| --- | --- | --- | --- |
| Case root path on Office Mac | Needed | User | Example target: `cases/` under a private local folder. |
| Case folder naming rule | Assumed | Codex | User supplies names such as `2025 8765`; implementation validates safe folder segments. |
| Discord thread URL source | Ready | User | User will paste the thread URL during Office Mac redaction. |
| Discord thread id as lookup key | Assumed | Codex | Manifest stores parsed `discord_thread_id`; restore resolves by id. |
| Network route Home Mac -> Office Mac | Needed | User | Recommend Tailscale; avoid public port forwarding. |
| Office API auth token | Needed | User | Bearer token stored in Home Mac MCP adapter env and Office service config. |
| Discord bot token | Needed for auto-post | User | Required only when Office Mac posts redacted files automatically. |
| Return restored file to Discord | Deferred | User/Codex | First version saves restored output on Office Mac and returns path/status. |

## Implementation Preparation

| Area | Prepared? | Notes |
| --- | --- | --- |
| Existing redaction pipeline | Yes | Reuse current `RedactionPipeline` and batch unified mapping behavior. |
| Existing restoration core | Yes | Reuse `restore_text` and `restore_docx`; preserve Word structure behavior. |
| Existing Web UI | Partial | Needs fields for case folder name and Discord thread URL. |
| Case manifest module | No | New module should own manifest schema, validation, lookup, and atomic writes. |
| Office API module | No | New FastAPI routes can live beside current Web app or as a separate app. |
| Home MCP adapter | No | New small stdio MCP service on Home Mac that calls Office HTTP API. |
| Discord posting client | No | Can be implemented after token and target posting mechanism are confirmed. |

## Credentials And Local Setup

- Tailscale or equivalent private route between Home Mac and Office Mac.
- Office Mac API bearer token.
- Home Mac MCP adapter environment:
  - `LEGAL_REDACTOR_API_URL`
  - `LEGAL_REDACTOR_API_TOKEN`
- Optional Discord posting environment on Office Mac:
  - `DISCORD_BOT_TOKEN`
  - allowed guild/channel/thread configuration

## Test Data Needed

- One temporary case source folder with at least:
  - one `.txt` or `.md` legal material
  - one `.docx` legal material if Word restore remains in first milestone
- One Discord test thread URL where bot posting is safe.
- One drafted pleading, brief, memorandum, or other legal document containing
  placeholders generated from the test mapping.
- One negative test draft containing an unknown placeholder to verify
  `unresolved_placeholders`.

## Open Questions

1. Should restored legal-document drafts ever be uploaded back to Discord automatically,
   or should they stay on the local workstation by default?
2. Should the Office Mac copy original source files into the case folder, store
   symlinks, or only store the original source directory path?
3. Should case creation be only through the existing Web UI, or should a local
   CLI command also be supported?
4. Should Discord auto-posting happen in the first implementation, or should the
   first implementation stop at local save + manual upload?

## Initial Scope Recommendation

The first build should avoid over-coupling Discord upload, Hermes behavior, and
case creation. Recommended first implementation:

1. Add case manifest and folder management on Office Mac.
2. Add Web UI fields for case folder name and Discord thread URL.
3. Save redacted outputs and encrypted mapping table into the case folder.
4. Add Office API restore-by-Discord-thread endpoint.
5. Add Home Mac MCP adapter with `restore_judgment_from_thread`.

Then add Discord auto-posting in a follow-up once bot credentials and thread
permissions are confirmed.

## Gate Expectations

- No original text, restored text, or mapping values in logs.
- Mapping tables never leave Office Mac.
- Path traversal and duplicate thread binding tests exist.
- Existing restore and Web regression tests continue to pass.
- Documentation explains the two-machine deployment and required environment
  variables.
