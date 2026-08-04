"""Strict, secret-free model catalog configuration for the model manager."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

CATALOG_SCHEMA_VERSION = "legal-redactor-model-catalog/v1"
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ModelCatalogError(ValueError):
    """Raised when the operator-supplied catalog is invalid."""


@dataclass(frozen=True)
class CatalogModel:
    id: str
    upstream_id: str
    label: str
    enabled: bool


@dataclass(frozen=True)
class CatalogWorker:
    id: str
    base_url: str
    api_key_env: str | None
    discovery_timeout_seconds: float
    request_timeout_seconds: float
    models: tuple[CatalogModel, ...]


@dataclass(frozen=True)
class ModelCatalog:
    schema_version: str
    default_model_id: str
    discovery_ttl_seconds: float
    workers: tuple[CatalogWorker, ...]


def load_model_catalog_from_environment(environ: dict[str, str] | None = None) -> ModelCatalog:
    """Load the catalog path from the environment or synthesize the legacy route."""
    environment = os.environ if environ is None else environ
    filename = environment.get("LEGAL_REDACTOR_MODEL_CATALOG", "").strip()
    if not filename:
        return _legacy_catalog(environment)
    try:
        content = Path(filename).read_text(encoding="utf-8")
    except OSError as exc:
        raise ModelCatalogError("LEGAL_REDACTOR_MODEL_CATALOG cannot be read") from exc
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ModelCatalogError("LEGAL_REDACTOR_MODEL_CATALOG is not valid JSON") from exc
    return parse_model_catalog(payload)


def parse_model_catalog(payload: object) -> ModelCatalog:
    root = _object(payload, "catalog")
    _only_keys(root, {"schema_version", "default_model_id", "discovery_ttl_seconds", "workers"}, "catalog")
    schema_version = _string(root.get("schema_version"), "catalog.schema_version")
    if schema_version != CATALOG_SCHEMA_VERSION:
        raise ModelCatalogError("catalog.schema_version is unsupported")
    default_model_id = _model_id(root.get("default_model_id"), "catalog.default_model_id")
    ttl = _nonnegative_number(root.get("discovery_ttl_seconds"), "catalog.discovery_ttl_seconds")
    worker_values = root.get("workers")
    if not isinstance(worker_values, list) or not worker_values:
        raise ModelCatalogError("catalog.workers must be a non-empty array")

    workers: list[CatalogWorker] = []
    worker_ids: set[str] = set()
    model_ids: set[str] = set()
    enabled_models: set[str] = set()
    for index, value in enumerate(worker_values):
        prefix = f"catalog.workers[{index}]"
        item = _object(value, prefix)
        _only_keys(
            item,
            {"id", "base_url", "api_key_env", "discovery_timeout_seconds", "request_timeout_seconds", "models"},
            prefix,
        )
        worker_id = _model_id(item.get("id"), f"{prefix}.id")
        if worker_id in worker_ids:
            raise ModelCatalogError("catalog contains duplicate worker IDs")
        worker_ids.add(worker_id)
        base_url = _base_url(item.get("base_url"), f"{prefix}.base_url")
        api_key_env_value = item.get("api_key_env")
        if api_key_env_value is not None:
            api_key_env = _string(api_key_env_value, f"{prefix}.api_key_env")
            if not _ENV_NAME_RE.fullmatch(api_key_env):
                raise ModelCatalogError(f"{prefix}.api_key_env is invalid")
        else:
            api_key_env = None
        discovery_timeout = _positive_number(item.get("discovery_timeout_seconds"), f"{prefix}.discovery_timeout_seconds")
        request_timeout = _positive_number(item.get("request_timeout_seconds"), f"{prefix}.request_timeout_seconds")
        model_values = item.get("models")
        if not isinstance(model_values, list) or not model_values:
            raise ModelCatalogError(f"{prefix}.models must be a non-empty array")
        models: list[CatalogModel] = []
        for model_index, model_value in enumerate(model_values):
            model_prefix = f"{prefix}.models[{model_index}]"
            model = _object(model_value, model_prefix)
            _only_keys(model, {"id", "upstream_id", "label", "enabled"}, model_prefix)
            model_id = _model_id(model.get("id"), f"{model_prefix}.id")
            if model_id in model_ids:
                raise ModelCatalogError("catalog contains duplicate logical model IDs")
            model_ids.add(model_id)
            upstream_id = _string(model.get("upstream_id"), f"{model_prefix}.upstream_id")
            label = _string(model.get("label"), f"{model_prefix}.label")
            enabled = model.get("enabled")
            if not isinstance(enabled, bool):
                raise ModelCatalogError(f"{model_prefix}.enabled must be boolean")
            if enabled:
                enabled_models.add(model_id)
            models.append(CatalogModel(model_id, upstream_id, label, enabled))
        workers.append(CatalogWorker(worker_id, base_url, api_key_env, discovery_timeout, request_timeout, tuple(models)))

    if default_model_id not in model_ids:
        raise ModelCatalogError("catalog.default_model_id is not configured")
    if default_model_id not in enabled_models:
        raise ModelCatalogError("catalog.default_model_id must be enabled")
    return ModelCatalog(schema_version, default_model_id, ttl, tuple(workers))


def _legacy_catalog(environment: dict[str, str]) -> ModelCatalog:
    from .model_manager import (
        DEFAULT_WORKER_API_KEY,
        DEFAULT_WORKER_BASE_URL,
        DEFAULT_WORKER_REQUEST_TIMEOUT_SECONDS,
        QWEN_MODEL_ID,
        QWEN_MODEL_LABEL,
    )

    base_url = environment.get("LEGAL_REDACTOR_MODEL_WORKER_BASE_URL", DEFAULT_WORKER_BASE_URL)
    # The legacy placeholder remains a compatibility default, but a real secret is
    # never placed in the catalog. Operators can migrate it to api_key_env.
    api_key = environment.get("LEGAL_REDACTOR_MODEL_WORKER_API_KEY", DEFAULT_WORKER_API_KEY)
    api_key_env = "LEGAL_REDACTOR_MODEL_WORKER_API_KEY" if api_key else None
    return ModelCatalog(
        CATALOG_SCHEMA_VERSION,
        QWEN_MODEL_ID,
        5,
        (
            CatalogWorker(
                "legacy-qwen-worker",
                _base_url(base_url, "legacy worker base URL"),
                api_key_env,
                2,
                DEFAULT_WORKER_REQUEST_TIMEOUT_SECONDS,
                (CatalogModel(QWEN_MODEL_ID, environment.get("LEGAL_REDACTOR_QWEN_MODEL", QWEN_MODEL_ID), QWEN_MODEL_LABEL, True),),
            ),
        ),
    )


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ModelCatalogError(f"{name} must be an object")
    return value


def _only_keys(value: dict[str, object], allowed: set[str], name: str) -> None:
    if set(value) != allowed and not (name.endswith("]") and set(value) == allowed - {"api_key_env"}):
        unknown = set(value) - allowed
        missing = allowed - set(value)
        if unknown:
            raise ModelCatalogError(f"{name} contains unknown fields")
        raise ModelCatalogError(f"{name} is missing required fields")


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelCatalogError(f"{name} must be a non-empty string")
    return value.strip()


def _model_id(value: object, name: str) -> str:
    result = _string(value, name)
    if not _MODEL_ID_RE.fullmatch(result):
        raise ModelCatalogError(f"{name} is invalid")
    return result


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ModelCatalogError(f"{name} must be positive")
    return float(value)


def _nonnegative_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ModelCatalogError(f"{name} must be non-negative")
    return float(value)


def _base_url(value: object, name: str) -> str:
    result = _string(value, name).rstrip("/")
    parsed = urlsplit(result)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ModelCatalogError(f"{name} must be an http(s) API URL")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ModelCatalogError(f"{name} has an invalid port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ModelCatalogError(f"{name} has an invalid port")
    if not parsed.path or parsed.path == "/":
        raise ModelCatalogError(f"{name} must include an API base path")
    return result
