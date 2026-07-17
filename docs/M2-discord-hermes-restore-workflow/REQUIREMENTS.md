# M2-discord-hermes-restore-workflow · Requirements

## Goal

Build a matter-centered workflow for lawyers and authorized legal-service teams.
The local workstation remains authoritative for client materials, encrypted redaction
maps, and restoration, while Hermes may assist with fact organization, summaries,
and legal-document drafts created from redacted materials.

The system should support this practical flow:

1. A lawyer keeps authorized client or matter materials in a local workstation folder.
2. During redaction, the lawyer provides a matter folder name and a controlled
   collaboration thread URL.
3. The local redaction system redacts selected materials, stores outputs and the
   mapping table under the matter folder, and may post only the redacted files to
   the controlled thread.
4. Hermes may organize facts, summarize materials, and draft pleadings, briefs,
   memoranda, or other lawyer work product from those redacted files.
5. When the lawyer requests restoration, Hermes sends the draft back through a
   local tool call.
6. The workstation resolves the thread to the local matter folder, loads the
   corresponding mapping table, restores the legal-document draft, and saves the
   result locally for lawyer review.

All AI output is assistive only. A lawyer must independently review the facts,
authorities, reasoning, confidentiality, and final wording. The workflow does not
produce judicial decisions and must not be used with materials the operator is not
authorized to process.

## Users And Jobs

- As the user, I want to type the case folder name myself during redaction, so
  the workflow does not depend on imperfect case-number recognition.
- As the user, I want the Discord thread URL saved with the case, so later
  restoration can be tied to the current thread without re-selecting a mapping
  table.
- As the user, I want redacted files to be posted to the right Discord thread
  automatically, so I do not manually upload the wrong file or miss files.
- As a lawyer, I want Hermes to restore an authorized legal-document draft when I
  request restoration in the thread, so I do not copy drafts between machines.
- As the system owner, I want mapping tables and original materials to remain on
  the Office Mac, so Hermes and Discord never receive the restoration map.

## Current Project Context

- The project is a brownfield Python package under `legal_redactor/`.
- The current Web UI supports text and `.docx` redaction, batch processing with a
  unified redaction map, and Word-format-preserving restoration.
- CLI restoration already supports `python -m legal_redactor --restore ...` and
  `scripts/restore_docx.py`.
- Mapping tables are sensitive and are stored encrypted by default.
- Project instructions require legal citations and statutory references to be
  preserved during redaction.

## Proposed Architecture

### Office Mac

The local workstation is the source of truth for matter state:

- local source-material folder
- matter folder name
- collaboration thread binding
- redacted files
- encrypted mapping table
- restored legal-document outputs
- operational logs without original text

The workstation should expose a small authenticated API for trusted callers on the
private network. The API is not responsible for legal advice or professional judgment;
it only performs matter lookup, redaction workflow operations, controlled upload, and
restoration.

### Home Mac / Hermes

The Home Mac runs Hermes and the Discord bot. Hermes should call a local MCP
adapter. The adapter forwards restore requests to the Office Mac API over a
private network such as Tailscale.

Hermes should not read local Office Mac folders directly and should not receive
mapping-table contents.

### Discord

Discord is the collaboration surface:

- receives redacted files posted by the Office Mac
- hosts the case-review thread where Hermes works
- supplies the thread id that links a restore request to a case manifest

Discord should not be the source of truth for case-to-map relationships.

## Case Folder Layout

The case folder name is user supplied. It may be a year and case number such as
`2025 8765`, but the system must accept any safe folder name that passes
validation.

Recommended layout:

```text
cases/
  2025 8765/
    manifest.json
    source_refs/
    redacted/
    mapping/
    restored/
    logs/
```

`source_refs/` should store metadata or symlinks only if safe for the local Mac
setup. The implementation must avoid duplicating original source materials unless
the user explicitly opts into that behavior.

## Manifest Contract

Each case folder must contain a manifest file. The manifest is the local
authority for Discord binding and restoration lookup.

Example:

```json
{
  "schema_version": 1,
  "case_folder": "2025 8765",
  "created_at": "2026-06-15T15:30:00+08:00",
  "updated_at": "2026-06-15T15:45:00+08:00",
  "source_dir": "/Users/example/Documents/case-materials/2025 8765",
  "discord_thread_url": "https://discord.com/channels/...",
  "discord_thread_id": "123456789",
  "redacted_dir": "redacted",
  "mapping_dir": "mapping",
  "restored_dir": "restored",
  "mapping_file": "mapping/redaction_map.enc",
  "redacted_files": [
    {
      "filename": "complaint.redacted.txt",
      "discord_attachment_id": "optional",
      "sha256": "optional"
    }
  ]
}
```

## Functional Requirements

### Create Or Update Case

- Provide a Web UI path where the user can enter:
  - source folder or selected source files
  - case folder name
  - Discord thread URL
- Validate case folder names to prevent path traversal and accidental writes
  outside the case root.
- Parse and store the Discord thread id from the URL.
- Create the case folder layout if it does not exist.
- Update `manifest.json` atomically.
- If the case already exists, require the user to explicitly continue in the
  existing case context rather than silently overwriting.

### Redact Into Case Folder

- Redact selected materials using the existing redaction pipeline.
- Use one unified mapping table for the case batch.
- Save redacted outputs under `redacted/`.
- Save the encrypted mapping table under `mapping/`.
- Preserve existing `.docx` restoration semantics and legal citation behavior.
- Record file metadata in the manifest without logging original content.

### Post Redacted Files To Discord

- Use a Discord bot token or another configured posting mechanism.
- Post redacted files to the bound Discord thread.
- Update manifest entries with Discord attachment/message identifiers when
  available.
- Avoid posting mapping tables, original materials, or restoration outputs by
  default.
- Return clear errors if Discord credentials or thread permissions are missing.

### Restore From Discord Thread

- Hermes invokes a local MCP tool when the lawyer requests restoration in a collaboration thread.
- The tool sends the current `discord_thread_id` and the legal-document draft text or
  file to the local API.
- The workstation resolves `discord_thread_id` to exactly one matter manifest.
- The workstation loads the matter mapping table locally and restores the draft.
- Restored output is saved under `restored/` with a non-overwriting timestamped
  filename for lawyer review.
- The API returns:
  - success/failure
  - saved local path
  - unresolved placeholders
  - replacement count when available

### MCP Adapter

Expose the smallest useful MCP surface to Hermes. The existing tool name is retained
for API compatibility, but its documented use is restoration of lawyer-reviewed legal drafts:

- `restore_judgment_from_thread`
  - input: `discord_thread_id`, `draft_text` or `draft_file`
  - output: restore status and local saved path
- `get_case_status_by_thread`
  - input: `discord_thread_id`
  - output: case folder, redacted file count, mapping presence, latest restored
    output metadata

Optional later tools:

- `list_recent_cases`
- `post_redacted_files`
- `create_case`

The first implementation should keep case creation and redaction in the Office
Mac Web UI. Hermes should only trigger restoration and status lookup.

## API Boundary

Use an authenticated Office Mac HTTP API behind a private network route.

Recommended first endpoints:

```text
GET  /health
GET  /cases/by-discord-thread/{thread_id}
POST /cases/{case_folder}/restore-text
POST /cases/by-discord-thread/{thread_id}/restore-text
POST /cases/by-discord-thread/{thread_id}/restore-docx
```

The API must reject:

- missing or invalid bearer token
- case folders outside the configured case root
- thread ids with no manifest match
- thread ids with multiple manifest matches
- restore requests with no mapping file
- unsafe output filenames

## Security And Privacy Requirements

- Mapping tables stay on the Office Mac.
- Original materials stay on the Office Mac.
- Discord receives only redacted files unless the user explicitly chooses
  otherwise.
- Logs must not include original text, restored text, or mapping values.
- The Office API should bind to a Tailscale IP or localhost behind a tunnel, not
  a public interface.
- All remote calls require a bearer token.
- Temporary files must be deleted after processing.
- Restoration output is saved locally by default. Sending restored output back to
  Discord should be a separate explicit option.

## Assumptions

- The user can install or configure a Discord bot token with permission to post
  in target threads.
- The Home Mac and Office Mac can reach each other through Tailscale or an
  equivalent private network.
- Hermes can call a local MCP stdio adapter on the Home Mac.
- The first scope can support text drafts first; `.docx` judgment restoration can
  follow if Hermes produces `.docx` files.
- Existing redaction and restoration code remains the implementation authority.

## Risks

- Discord thread URL parsing may vary by server/channel/thread shape.
- Office Mac may be offline when Hermes asks for restoration.
- Hermes may draft text with placeholders that are not present in the case map.
- A user may accidentally bind the wrong Discord thread to a case.
- Multiple cases could be configured with the same thread id if manifest updates
  are not guarded.
- Discord file upload limits may affect large redacted bundles.

## Testing Plan

- Unit test case folder name validation and path traversal rejection.
- Unit test Discord URL parsing into channel/thread ids.
- Unit test manifest creation, atomic update, and duplicate thread detection.
- Unit test thread-id-to-case lookup across multiple manifests.
- Unit test restore by thread id using a temporary case root and encrypted map.
- Integration test text restore through the Office API.
- Integration test MCP adapter tool schema and HTTP forwarding with a fake Office
  API.
- Existing regression tests for restore, pipeline, and Web restore remain in
  scope:
  - `.venv/bin/python -m pytest tests/test_restore.py`
  - `.venv/bin/python -m pytest tests/test_pipeline.py tests/test_web_app.py`

## Recommended Next FFCS Command

Use `/ffcs:spec M2-discord-hermes-restore-workflow` after this need document is
reviewed. The spec should focus on a minimal first milestone:

1. Office Mac case manifest and folder service.
2. Office Mac restore-by-thread API.
3. Home Mac MCP adapter for Hermes restoration.

Discord auto-posting can be specified as part of the same milestone only if the
Discord bot credential and posting path are already available. Otherwise it
should be a follow-up milestone.
