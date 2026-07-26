# Hermes + Office Mac Restore Workflow

This workflow keeps source materials and redaction maps on the Office Mac while
Hermes on the Home Mac can request restoration from a Discord case thread.

## Office Mac

Set a private case root and API token in a local JSON file that is not committed:

```bash
mkdir -p ~/.config/legal-redactor
cp config/api.example.json ~/.config/legal-redactor/api.local.json
```

Start the restore API on localhost. Keep the API off public and private network
interfaces; the Home Mac reaches it through an SSH reverse tunnel:

```bash
LEGAL_REDACTOR_API_CONFIG=~/.config/legal-redactor/api.local.json \
  .venv/bin/python -m uvicorn legal_redactor.remote_api:app --host 127.0.0.1 --port 8787
```

Run the tunnel from the Office Mac to the Home Mac using a Tailscale MagicDNS
hostname (or an SSH alias backed by that hostname), not a numeric Tailscale IP:

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 -R 127.0.0.1:18787:127.0.0.1:8787 home-mac-mini
```

Configure the Home Mac MCP adapter to call `http://127.0.0.1:18787`. Tailscale
IP changes then affect neither the API bind address nor the MCP URL; MagicDNS
resolves the SSH peer's current address.

If Shadowrocket or the Tailscale route changes, do not replace the Home Mac
MCP URL with a newly observed numeric Tailscale IP. Keep the Home Mac config at
`http://127.0.0.1:18787`, restart the SSH reverse tunnel from the Office Mac,
and verify on the Home Mac:

```bash
curl http://127.0.0.1:18787/health
```

After the health check returns `{"status":"ok"}`, reload or restart the
`legal-redactor` MCP session in Hermes and retry the same restore request with
the unchanged draft. An `office_unreachable` result is retryable; it must not
trigger manual replacement of the final draft.

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
- case root path, used only as a fallback when the uploaded/source document
  directory cannot identify the case folder

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

If the upload/source directory points at the case folder, the Office Web and
private API derive `case_root` from that source directory. This keeps the saved
manifest, redacted files, and encrypted map beside the uploaded matter even when
the API config has a different default case root. The configured root remains a
fallback for older/manual flows and smoke tests.

The mapping table is not uploaded to Discord.

## Readiness Status

The Web UI exposes a read-only status panel and machine endpoints:

```bash
curl http://127.0.0.1:7860/health
curl http://127.0.0.1:7860/api/status
curl http://127.0.0.1:7860/api/model-status
curl http://127.0.0.1:18080/health
curl http://127.0.0.1:18080/v1/models
```

`/health` remains a lightweight Web liveness check. `/api/status` passively reports
readiness for the local workflow, and `/api/model-status` returns only the model
manager component state:

- Web/API local config: `LEGAL_REDACTOR_API_CONFIG`, default
  `~/.config/legal-redactor/api.local.json`
- Local model API: `LEGAL_REDACTOR_MODEL_MANAGER_HOST` / `PORT`, default
  `http://127.0.0.1:18080`; the registered logical model ID is `qwen3.5-9b`
- MLX worker: `LEGAL_REDACTOR_MLX_WORKER_HOST` / `PORT`, default
  `127.0.0.1:18081`, owned and started lazily by the manager only
- Case root: `LEGAL_REDACTOR_CASE_ROOT` or the default local case root
- Office restore API token presence: `LEGAL_REDACTOR_API_TOKEN` or
  `api_token` in `api.local.json`
- Hermes MCP config: `LEGAL_REDACTOR_MCP_CONFIG`,
  `LEGAL_REDACTOR_API_URL`, and `LEGAL_REDACTOR_API_TOKEN`
- Discord command channel readiness:
  `LEGAL_REDACTOR_DISCORD_BOT_TOKEN` and
  `LEGAL_REDACTOR_DISCORD_COMMAND_CHANNEL_ID`

The status endpoints are passive. They do not start, stop, or modify the model
manager or worker, call MCP tools, send Discord messages, or write case files.
If the manager or its registered model is unavailable, redaction explicitly falls
back to rules rather than treating that result as LLM-assisted recognition. Public
status and manager responses expose logical IDs only, never model paths, tokens,
document text, mappings, samples, or restored full text.

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

Create the local MCP config from the example. It defaults to the Home Mac's
local reverse-tunnel endpoint; fill in the matching Office API token:

```bash
mkdir -p ~/.config/legal-redactor
cp config/mcp.example.json ~/.config/legal-redactor/mcp.local.json
```

Available tools:

- `restore_judgment_from_thread(discord_thread_id, draft_text)`
- `get_case_status_by_thread(discord_thread_id)`
- `bind_discord_thread_to_case(case_folder, discord_thread_url, source_dir, case_root)`

Hermes should pass the current collaboration thread id and an authorized legal-document
draft. The local workstation resolves the thread id to a matter manifest, loads the local
mapping table, restores the draft, and saves the text under `restored/` for lawyer review.
For binding, Hermes should pass `source_dir` when it knows the uploaded/source
document directory. The Office API uses that directory before the configured
case root, so empty shell manifests under an old configured root do not hide the
real case directory containing the map.

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

- Mapping tables stay on the local workstation.
- Original materials stay on the local workstation.
- Restored legal-document drafts are saved on the local workstation by default for lawyer review.
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
