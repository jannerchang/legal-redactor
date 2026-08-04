# DGX Spark / Linux deployment

Deploy the complete application on the Spark host: Web UI, model manager, and one
or more loopback-only vLLM workers. The browser should reach the UI via SSH
forwarding rather than by opening the legal-document service to the LAN:

```bash
ssh -L 7860:127.0.0.1:7860 spark-host
# browse http://127.0.0.1:7860 locally
```

## Install

1. Create a dedicated `legal-redactor` Linux account and install the repository
   at `/opt/legal-redactor`; create its virtual environment and install
   `requirements.txt`. The application requirements intentionally do **not**
   include vLLM. Install vLLM separately in a DGX/CUDA-compatible Python runtime;
   the exact interpreter configured for each worker must successfully run
   `import vllm`.
2. Copy `config/models.example.json` outside the checkout (for example
   `/etc/legal-redactor/models.json`), set `LEGAL_REDACTOR_MODEL_CATALOG` in
   `/etc/legal-redactor/model-manager.env`, and put worker API keys only in the
   environment file named by each `api_key_env` field. Do not commit either file.
3. For each worker create `/etc/legal-redactor/vllm-NAME.env` with `VLLM_MODEL`,
   `VLLM_PORT`, mandatory `VLLM_SERVED_MODEL_NAME`, and `PYTHON_BIN` pointing to
   the DGX/CUDA vLLM interpreter. `VLLM_SERVED_MODEL_NAME` must exactly equal that
   model's catalog `upstream_id`; discovery will not expose a mismatched name.
   Keep `VLLM_HOST=127.0.0.1` (only `127.0.0.1` and `localhost` are accepted).
   If `/opt/legal-redactor/.venv/bin/python` contains vLLM, `PYTHON_BIN` may be
   omitted and that interpreter is used. Free-form worker arguments are not
   accepted. Start with `systemctl enable --now legal-redactor-vllm@NAME`.
4. Install the three units from `deploy/systemd/`, then enable the manager and
   Web services. All units intentionally bind to `127.0.0.1`.

`GET /v1/models` exposes only enabled catalog IDs that currently appear in the
matching worker's upstream `/models` response. A configured, disabled example
is not a certification claim and cannot become selectable. Worker URLs, API
keys, upstream names, and local paths are never sent to the Web UI.

## Data migration and operations

Migrate the complete case root (`LEGAL_REDACTOR_CASE_ROOT`) with ownership and
permissions preserved. Also migrate the encryption key material used for
existing encrypted redaction maps; without the original key, those mappings
cannot be restored. Test a copied case before cutover and retain a protected
backup.

Linux does not provide the macOS `textutil` conversion path for legacy `.doc`.
Use `.docx`, PDF, text, or convert legacy Word documents before upload.

The manager may be healthy while no workers are live. This is intentional:
new redaction is fail-closed until a live, allowlisted model appears; recovery
of existing encrypted mappings is unaffected.
