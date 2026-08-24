from __future__ import annotations

import json
import os
import subprocess
import time

import pytest

from legal_redactor.model_catalog import ModelCatalogError, parse_model_catalog
from legal_redactor.model_manager import CatalogModelManager


def _catalog() -> dict:
    return {
        "schema_version": "legal-redactor-model-catalog/v1",
        "default_model_id": "qwen",
        "discovery_ttl_seconds": 30,
        "workers": [
            {
                "id": "qwen-worker",
                "base_url": "http://127.0.0.1:8000/v1",
                "discovery_timeout_seconds": 1,
                "request_timeout_seconds": 2,
                "models": [{"id": "qwen", "upstream_id": "qwen-upstream", "label": "Qwen", "enabled": True}],
            },
            {
                "id": "other-worker",
                "base_url": "http://127.0.0.1:8001/v1",
                "discovery_timeout_seconds": 1,
                "request_timeout_seconds": 2,
                "models": [{"id": "other", "upstream_id": "other-upstream", "label": "Other", "enabled": True}],
            },
        ],
    }


def test_catalog_rejects_duplicate_logical_ids_and_invalid_urls() -> None:
    duplicate = _catalog()
    duplicate["workers"][1]["models"][0]["id"] = "qwen"
    with pytest.raises(ModelCatalogError, match="duplicate logical"):
        parse_model_catalog(duplicate)

    invalid_url = _catalog()
    invalid_url["workers"][0]["base_url"] = "https://worker.example.test"
    with pytest.raises(ModelCatalogError, match="API base path"):
        parse_model_catalog(invalid_url)


def test_catalog_router_intersects_allowlist_tolerates_worker_failure_and_routes(monkeypatch) -> None:
    manager = CatalogModelManager(parse_model_catalog(_catalog()), environ={"WORKER_TOKEN": "secret"})
    calls: list[tuple[str, str, dict | None]] = []

    def request(worker, method, endpoint, payload):
        calls.append((worker.id, method, payload))
        if worker.id == "other-worker":
            raise OSError("not reachable")
        if method == "GET":
            return 200, json.dumps({"data": [{"id": "qwen-upstream"}, {"id": "unallowlisted"}]}).encode(), "application/json"
        assert payload is not None
        assert payload["model"] == "qwen-upstream"
        return 200, json.dumps({"model": "private-upstream", "choices": []}).encode(), "application/json"

    monkeypatch.setattr(manager, "_request_worker", request)
    payload = manager.models_payload()
    assert payload == {
        "object": "list",
        "default_model_id": "qwen",
        "data": [{"id": "qwen", "object": "model", "name": "Qwen"}],
    }

    status, body, _ = manager.proxy_chat_completion({"model": "qwen", "messages": []})
    assert status == 200
    assert json.loads(body)["model"] == "qwen"
    assert all("private-upstream" not in str(item) for item in (payload, json.loads(body)))

    status, body, _ = manager.proxy_chat_completion({"model": "other", "messages": []})
    assert status == 503
    assert json.loads(body)["error"]["code"] == "model_unavailable"
    assert "other-worker" not in body.decode()


def test_catalog_curl_transport_keeps_payload_and_api_key_out_of_argv(monkeypatch) -> None:
    catalog = _catalog()
    catalog["workers"][0]["api_key_env"] = "WORKER_TOKEN"
    manager = CatalogModelManager(parse_model_catalog(catalog), environ={"WORKER_TOKEN": "secret-token"})
    worker = manager._catalog.workers[0]
    calls: list[dict] = []

    def run(command, *, input, capture_output, check, timeout, pass_fds):
        calls.append(
            {
                "command": command,
                "input": input,
                "headers": os.read(pass_fds[0], 4096) if pass_fds else b"",
            }
        )
        assert capture_output is True
        assert check is False
        assert timeout == 7
        return subprocess.CompletedProcess(command, 0, b'{"choices":[]}\n200', b"")

    monkeypatch.setattr("legal_redactor.model_manager.subprocess.run", run)
    document_text = "原告张三的私密文书内容"

    status, body, content_type = manager._request_worker_with_curl(
        worker,
        "POST",
        "/chat/completions",
        {"model": "qwen-upstream", "messages": [{"role": "user", "content": document_text}]},
    )

    assert status == 200
    assert body == b'{"choices":[]}'
    assert content_type == "application/json"
    command_text = " ".join(calls[0]["command"])
    assert calls[0]["command"][:4] == ["/usr/bin/curl", "--noproxy", "*", "--silent"]
    assert calls[0]["command"][-1] == "http://127.0.0.1:8000/v1/chat/completions"
    assert calls[0]["input"] is not None and document_text.encode() in calls[0]["input"]
    assert calls[0]["headers"] == b"Authorization: Bearer secret-token\n"
    assert document_text not in command_text
    assert "secret-token" not in command_text
    assert "@-" in calls[0]["command"]


def test_catalog_curl_timeout_is_reported_as_unavailable(monkeypatch) -> None:
    manager = CatalogModelManager(parse_model_catalog(_catalog()))
    worker = manager._catalog.workers[0]

    def run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr("legal_redactor.model_manager.subprocess.run", run)

    with pytest.raises(OSError, match="unavailable"):
        manager._request_worker_with_curl(worker, "GET", "/models", None)


def test_catalog_discovery_queries_workers_concurrently(monkeypatch) -> None:
    catalog_data = _catalog()
    catalog_data["workers"].insert(
        1,
        {
            "id": "second-slow-worker",
            "base_url": "http://127.0.0.1:8002/v1",
            "discovery_timeout_seconds": 1,
            "request_timeout_seconds": 2,
            "models": [{"id": "slow", "upstream_id": "slow-upstream", "label": "Slow", "enabled": True}],
        },
    )
    manager = CatalogModelManager(parse_model_catalog(catalog_data))

    def request(worker, method, endpoint, payload):
        assert method == "GET"
        if worker.id != "other-worker":
            time.sleep(0.2)
            raise OSError("slow failure")
        return 200, json.dumps({"data": [{"id": "other-upstream"}]}).encode(), "application/json"

    monkeypatch.setattr(manager, "_request_worker", request)
    started = time.monotonic()

    payload = manager.models_payload()

    elapsed = time.monotonic() - started
    assert payload["data"] == [{"id": "other", "object": "model", "name": "Other"}]
    # Two serial worker timeouts would exceed 0.4s. This generous threshold
    # proves discovery costs roughly one timeout without relying on tight timing.
    assert elapsed < 0.35
