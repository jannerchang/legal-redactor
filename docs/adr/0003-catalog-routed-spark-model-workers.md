# ADR 0003: Catalog-routed Spark model workers

## Status
Accepted.

## Context
The redaction application is deployed as a complete service on Linux/DGX Spark,
not merely as a remote inference endpoint. The browser must choose an approved
logical model without discovering worker routes, credentials, upstream IDs, or
weight paths. The full-document legal redaction protocol remains fail-closed and
must not acquire model routing information from arbitrary upstream inventory.

## Decision
A strict JSON model catalog defines logical IDs, labels, enabled state, workers,
and upstream ID mappings. The model manager discovers each configured worker's
`/models` inventory and exposes only the enabled allowlist intersection. It
routes a chosen logical ID only to its configured worker, rewrites the returned
model to the logical ID, and sanitizes errors. Discovery is independently cached
and a failed worker does not hide healthy workers. The Web UI uses the manager
provided default only when it is live, otherwise the first live model; no live
models disables selection and blocks new redaction.

All Web, manager, and vLLM services bind loopback by default and are accessed
through SSH tunneling or a separately managed authenticated TLS proxy.

## Consequences
Operators explicitly validate and enable any additional model. The example
second worker is intentionally disabled and makes no certification assertion.
A live control plane with zero models is valid, but new redaction stays blocked.
The existing legal redaction pipeline and prior ADR contracts are unchanged.
