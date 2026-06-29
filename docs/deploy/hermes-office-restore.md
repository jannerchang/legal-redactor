# Hermes + Office Mac Restore Workflow

This workflow keeps source materials and redaction maps on the Office Mac while
Hermes on the Home Mac can request restoration from a Discord case thread.

## Office Mac

Set a private case root and API token in a local JSON file that is not committed:

```bash
mkdir -p ~/.config/legal-redactor
cp config/api.example.json ~/.config/legal-redactor/api.local.json
```

Start the restore API on localhost for smoke tests:

```bash
LEGAL_REDACTOR_API_CONFIG=~/.config/legal-redactor/api.local.json \
  .venv/bin/python -m uvicorn legal_redactor.remote_api:app --host 127.0.0.1 --port 8787
```

For Home Mac access, bind only to a private interface such as a Tailscale IP:

```bash
.venv/bin/python -m uvicorn legal_redactor.remote_api:app --host 100.x.y.z --port 8787
```

Do not expose this API through a public port. The API requires:

```text
Authorization: Bearer <LEGAL_REDACTOR_API_TOKEN>
```

## Office Web Redaction

Open the existing Web UI:

```bash
.venv/bin/python -m legal_redactor --web
```

During redaction, optionally fill:

- case folder name, for example `2025 8765`
- Discord thread URL
- case root path

The result page shows one case workflow state: `not_saved`, `saved_local`,
`bound_thread`, `sent_discord`, `waiting_hermes`, or `attach_failed`. These
states are recomputed by the Office Mac service from local manifest and send
results; browser-submitted state/status/binding decisions are rejected.

The result page can also post the redacted text file directly to the filled
Discord thread when `discord_bot_token` is present in
`~/.config/legal-redactor/api.local.json`. Only the redacted file is sent; the
mapping table remains local.

Hermes create-thread commands and Discord attachment messages use an allowlist:
request id, sanitized case folder/title/cause, and redacted attachment metadata.
They must not include `case_root`, `source_dir`, local absolute paths, original
text, map contents, sample data, or restored full text.

When both case fields are filled, redacted files and the encrypted mapping table
are saved under:

```text
<case_root>/<case_folder>/
  manifest.json
  redacted/
  mapping/redaction_map.enc
  restored/
```

The mapping table is not uploaded to Discord.

## Readiness Status

The Web UI exposes a read-only status panel on the first screen and a machine
endpoint:

```bash
curl http://127.0.0.1:7860/health
curl http://127.0.0.1:7860/api/status
curl http://127.0.0.1:18080/v1/models
```

`/health` stays a lightweight liveness check. `/api/status` reports readiness
for the existing local workflow:

- Web/API local config: `LEGAL_REDACTOR_API_CONFIG`, default
  `~/.config/legal-redactor/api.local.json`
- MLX server: `LEGAL_REDACTOR_MLX_HOST`, `LEGAL_REDACTOR_MLX_PORT`,
  `LEGAL_REDACTOR_SKIP_MLX`, expected model
  `mlx-community/Qwen3.5-9B-MLX-4bit`
- MLX cache/runtime: `HF_HOME`, `HF_HUB_DISABLE_XET`, `COPYFILE_DISABLE`,
  `mlx_lm.server`, and macOS `._*` AppleDouble sidecar warnings
- Case root: `LEGAL_REDACTOR_CASE_ROOT` or the default local case root
- Office restore API token presence: `LEGAL_REDACTOR_API_TOKEN` or
  `api_token` in `api.local.json`
- Hermes MCP config: `LEGAL_REDACTOR_MCP_CONFIG`,
  `LEGAL_REDACTOR_API_URL`, and `LEGAL_REDACTOR_API_TOKEN`
- Discord command channel readiness:
  `LEGAL_REDACTOR_DISCORD_BOT_TOKEN` and
  `LEGAL_REDACTOR_DISCORD_COMMAND_CHANNEL_ID`

The status endpoint is passive. It does not start MLX, kill port listeners,
clean cache files, call MCP tools, send Discord messages, or write case files.
If MLX is skipped or unavailable, the status should show degraded recognition
support rather than presenting pure-rule mode as equivalent to MLX-assisted
recognition.

## Home Mac MCP Adapter

Configure Hermes to start the local MCP adapter:

```json
{
  "mcpServers": {
    "legal-redactor": {
      "command": "python",
      "args": [
        "-m",
        "legal_redactor.mcp_adapter"
      ],
      "env": {
        "LEGAL_REDACTOR_MCP_CONFIG": "~/.config/legal-redactor/mcp.local.json"
      }
    }
  }
}
```

Create the local MCP config from the example and fill in the Office Mac private
API URL and token:

```bash
mkdir -p ~/.config/legal-redactor
cp config/mcp.example.json ~/.config/legal-redactor/mcp.local.json
```

Available tools:

- `restore_judgment_from_thread(discord_thread_id, draft_text)`
- `get_case_status_by_thread(discord_thread_id)`
- `bind_discord_thread_to_case(case_folder, discord_thread_url, source_dir, case_root)`

Hermes should pass the current Discord thread id and the drafted judgment text.
The Office Mac resolves the thread id to a local case manifest, loads the local
mapping table, restores the draft, and saves the restored text under `restored/`.

The status and restore tools return the Office API envelope:

```json
{
  "ok": true,
  "code": "restored",
  "case": {
    "case_folder": "2025 8765",
    "discord_thread_id": "1234567890",
    "discord_thread_url": "https://discord.com/channels/1/2/1234567890",
    "workflow_state": "bound_thread",
    "redacted_file_count": 1,
    "mapping_present": true
  },
  "restore": {
    "status": "restored",
    "restored_filename": "judgment.restored.20260629-000000-000000.txt",
    "restored_relative_path": "restored/judgment.restored.20260629-000000-000000.txt",
    "replacement_count": 3,
    "unresolved_placeholder_count": 0,
    "requested_at": "2026-06-29T00:00:00+00:00",
    "completed_at": "2026-06-29T00:00:01+00:00",
    "duration_ms": 1000,
    "timing_reason": null,
    "metadata_status": "written"
  },
  "next_action": "open_office_restored_file"
}
```

Status codes distinguish `missing_map`, `no_restore_yet`, `restored`,
`restore_failed`, `unbound_thread`, and `duplicate_thread`. API and MCP errors
use safe `code`, `status`, `message`, and `next_action` fields and never relay
raw HTTP response bodies.

## Safety Rules

- Mapping tables stay on the Office Mac.
- Original materials stay on the Office Mac.
- Restored judgments are saved on the Office Mac by default.
- API logs and responses must not include original text, restored text, or
  mapping values.
- API/MCP responses return `unresolved_placeholder_count`, not placeholder
  arrays.
- API/MCP responses return `restored_filename` and `restored_relative_path`, not
  absolute Office paths.
- `/api/status` must not include token values, original text, restored text,
  mapping values, or sample contents; it should report presence/readiness only.
- If Discord auto-posting is added later, it should be a separate explicit
  workflow with its own token and permission checks.
