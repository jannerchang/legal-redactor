# M2-discord-hermes-restore-workflow · Requirements

## Goal

Build a case-centered workflow that lets the Office Mac remain the authority for
source materials, encrypted redaction maps, and restoration, while Hermes on the
Home Mac can request restoration from a Discord case thread after drafting a
judgment from redacted materials.

The system should support this practical flow:

1. The user keeps legal materials in a local Office Mac folder.
2. During redaction, the user manually provides a case folder name such as
   `2025 8765` and a Discord thread URL.
3. The Office Mac redaction system redacts selected materials, stores redacted
   outputs and the mapping table under the named case folder, and posts the
   redacted files into the Discord thread.
4. Hermes analyzes the redacted files in that thread and drafts a judgment.
5. When the user says "还原" in the Discord thread, Hermes sends the draft back
   through a tool call.
6. The Office Mac resolves the Discord thread to the local case folder, loads the
   corresponding mapping table, restores the judgment, and saves the restored
   result locally.

## Users And Jobs

- As the user, I want to type the case folder name myself during redaction, so
  the workflow does not depend on imperfect case-number recognition.
- As the user, I want the Discord thread URL saved with the case, so later
  restoration can be tied to the current thread without re-selecting a mapping
  table.
- As the user, I want redacted files to be posted to the right Discord thread
  automatically, so I do not manually upload the wrong file or miss files.
- As the user, I want Hermes to restore a drafted judgment by saying "还原" in
  the thread, so I do not copy drafts between machines.
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

The Office Mac is the source of truth for case state:

- local source material folder
- case folder name
- Discord thread binding
- redacted files
- encrypted mapping table
- restored judgment outputs
- operational logs without original text

The Office Mac should expose a small authenticated API for trusted callers on the
private network. The API is not responsible for legal analysis; it only performs
case lookup, redaction workflow operations, Discord upload, and restoration.

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

- Hermes invokes a local MCP tool when the user says "还原" in a Discord thread.
- The tool sends the current `discord_thread_id` and the draft judgment text or
  file to the Office Mac API.
- Office Mac resolves `discord_thread_id` to exactly one case manifest.
- Office Mac loads the case mapping table locally and restores the draft.
- Restored output is saved under `restored/` with a non-overwriting timestamped
  filename.
- The API returns:
  - success/failure
  - saved local path
  - unresolved placeholders
  - replacement count when available

### MCP Adapter

Expose the smallest useful MCP surface to Hermes:

- `restore_judgment_from_thread`
  - input: `discord_thread_id`, `draft_text` or `draft_file`
  - output: restore status and Office Mac saved path
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
