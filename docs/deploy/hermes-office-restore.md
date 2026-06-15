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

The result page can also post the redacted text file directly to the filled
Discord thread when `discord_bot_token` is present in
`~/.config/legal-redactor/api.local.json`. Only the redacted file is sent; the
mapping table remains local.

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

Hermes should pass the current Discord thread id and the drafted judgment text.
The Office Mac resolves the thread id to a local case manifest, loads the local
mapping table, restores the draft, and saves the restored text under `restored/`.

## Safety Rules

- Mapping tables stay on the Office Mac.
- Original materials stay on the Office Mac.
- Restored judgments are saved on the Office Mac by default.
- API logs and responses must not include original text, restored text, or
  mapping values.
- If Discord auto-posting is added later, it should be a separate explicit
  workflow with its own token and permission checks.
