from __future__ import annotations

import json
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
