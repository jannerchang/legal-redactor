from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import Response
from ._logging import get_logger
from .model_catalog import CatalogModel, CatalogWorker, ModelCatalog, load_model_catalog_from_environment


QWEN_MODEL_ID = "qwen3.6-27b-fp8"
QWEN_MODEL_LABEL = "Qwen3.6 27B FP8（DGX Spark；全文默认）"
DEFAULT_MODEL_ID = QWEN_MODEL_ID
DEFAULT_MODEL_PATH = DEFAULT_QWEN_MODEL_PATH = QWEN_MODEL_ID
DEFAULT_WORKER_BASE_URL = "http://192.168.99.1:8000/v1"
DEFAULT_WORKER_API_KEY = "local-placeholder"
DEFAULT_WORKER_MAX_TOKENS = 8192
DEFAULT_WORKER_STARTUP_TIMEOUT_SECONDS = 300
DEFAULT_WORKER_REQUEST_TIMEOUT_SECONDS = 660


DEFAULT_MODEL_SEARCH_ROOTS = (
    Path.home() / "Models/HuggingFace",
    Path.home() / ".cache/huggingface/hub",
)
SUPPORTED_MODEL_TYPES = frozenset(
    {
        "deepseek_v2",
        "deepseek_v3",
        "gemma",
        "gemma2",
        "gemma3_text",
        "glm4",
        "glm4_moe",
        "llama",
        "mistral",
        "mixtral",
        "phi3",
        "phi4mm",
        "qwen2",
        "qwen2_moe",
        "qwen3",
        "qwen3_5",
        "qwen3_5_text",
        "qwen3_moe",
    }
)
BUILTIN_MODEL_SOURCE_NAMES = frozenset({QWEN_MODEL_ID})
INCOMPATIBLE_FULL_DOCUMENT_MODEL_IDS = frozenset(
    {
        "mlx-community/Qwen3.5-4B-MLX-4bit",
        "prism-ml/Ternary-Bonsai-27B-mlx-2bit",
        "Ternary-Bonsai-27B-mlx-2bit",
    }
)
_logger = get_logger(__name__)



@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    path: Path | str


class ModelManagerError(RuntimeError):
    code = "model_unavailable"
    status_code = 503


class ModelNotFoundError(ModelManagerError):
    code = "model_not_found"
    status_code = 404


class WorkerResponseError(ModelManagerError):
    code = "worker_error"
    status_code = 502


class InvalidWorkerResponseError(ModelManagerError):
    code = "invalid_worker_response"
    status_code = 502


class ModelManager:
    """Expose registered logical model IDs through one managed or remote worker."""

    def __init__(
        self,
        models: Mapping[str, ModelSpec],
        worker_host: str,
        worker_port: int,
        startup_timeout_seconds: float = DEFAULT_WORKER_STARTUP_TIMEOUT_SECONDS,
        request_timeout_seconds: float = DEFAULT_WORKER_REQUEST_TIMEOUT_SECONDS,
        popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        model_discovery: Callable[[], Mapping[str, ModelSpec]] | None = None,
        manage_worker: bool = True,
        worker_base_path: str = "",
        worker_api_key: str | None = None,
    ) -> None:
        self._models = dict(models)
        self._model_discovery = model_discovery
        self._worker_host = worker_host
        self._worker_port = worker_port
        self._worker_base_path = worker_base_path.rstrip("/")
        self._worker_api_key = worker_api_key
        self._startup_timeout_seconds = startup_timeout_seconds
        self._request_timeout_seconds = request_timeout_seconds
        self._popen_factory = popen_factory
        self._manage_worker = manage_worker
        self._lock = threading.RLock()
        self._worker_process: subprocess.Popen[bytes] | None = None
        self._active_model: str | None = None
        self._worker_state = "stopped" if manage_worker else "ready"

    def _refresh_models(self) -> None:
        if self._model_discovery is None:
            return
        self._models = {
            QWEN_MODEL_ID: ModelSpec(
                QWEN_MODEL_ID,
                QWEN_MODEL_LABEL,
                os.environ.get("LEGAL_REDACTOR_QWEN_MODEL", str(DEFAULT_QWEN_MODEL_PATH)),
            )
        }


    def models_payload(self) -> dict[str, Any]:
        with self._lock:
            self._refresh_models()
            return {
                "object": "list",
                "data": [
                    {"id": spec.id, "object": "model", "name": spec.label}
                    for spec in self._models.values()
                    if not self._manage_worker or _model_source_is_available(spec.path)
                ],
            }

    def health_payload(self) -> dict[str, str | None]:
        acquired = self._lock.acquire(blocking=False)
        if not acquired:
            return {
                "status": "ok",
                "active_model": self._active_model,
                "worker_state": "busy",
            }
        try:
            if self._manage_worker:
                self._refresh_worker_state()
            return {
                "status": "error" if self._worker_state == "error" else "ok",
                "active_model": self._active_model,
                "worker_state": self._worker_state,
            }
        finally:
            self._lock.release()

    def ensure_model(self, model_id: str) -> ModelSpec:
        with self._lock:
            self._refresh_models()
            spec = self._models.get(model_id)
            if spec is None:
                raise ModelNotFoundError("Requested model is not registered")
            if self._manage_worker:
                if not _model_source_is_available(spec.path):
                    raise ModelManagerError("Registered model is unavailable")
                spec = ModelSpec(spec.id, spec.label, _resolve_model_source(spec.path))
                self._ensure_worker(spec)
            return spec

    def proxy_chat_completion(self, payload: dict[str, Any]) -> tuple[int, bytes, str]:
        model_id = payload.get("model")
        if not isinstance(model_id, str) or not model_id:
            return _error_response(ModelNotFoundError("A registered model ID is required"))

        max_tokens = payload.get("max_tokens")
        safe_max_tokens = max_tokens if isinstance(max_tokens, int) and not isinstance(max_tokens, bool) else "未指定"
        started = time.monotonic()
        with self._lock:
            try:
                _logger.info("模型请求开始：逻辑模型=%s，max_tokens=%s。", model_id, safe_max_tokens)
                spec = self.ensure_model(model_id)
                worker_payload = dict(payload)
                worker_payload["model"] = str(spec.path)
                status, body, content_type = self._post_worker(worker_payload)
                if not 200 <= status < 300:
                    raise WorkerResponseError("Model worker rejected the request")
                response_payload = _parse_worker_response(body)
                if "model" in response_payload:
                    response_payload["model"] = spec.id
                self._active_model = spec.id
                self._worker_state = "ready"
                usage = response_payload.get("usage") if isinstance(response_payload, dict) else None
                completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
                _logger.info(
                    "模型请求完成：逻辑模型=%s，HTTP=200，用时=%.2fs，输出 tokens=%s。",
                    spec.id,
                    time.monotonic() - started,
                    completion_tokens if isinstance(completion_tokens, int) else "未知",
                )
                return 200, json.dumps(response_payload, ensure_ascii=False).encode("utf-8"), content_type
            except ModelManagerError as exc:
                safe_reason = _safe_manager_reason(exc)
                _logger.warning(
                    "模型请求终止：逻辑模型=%s，HTTP=%d，错误码=%s，原因=%s，用时=%.2fs。",
                    model_id,
                    exc.status_code,
                    exc.code,
                    safe_reason,
                    time.monotonic() - started,
                )
                return _error_response(exc)
            except (OSError, http.client.HTTPException):
                if self._manage_worker:
                    self._refresh_worker_state()
                else:
                    self._worker_state = "error"
                error = ModelManagerError("Model worker is unavailable")
                _logger.warning(
                    "模型请求终止：逻辑模型=%s，HTTP=%d，错误码=%s，用时=%.2fs。",
                    model_id,
                    error.status_code,
                    error.code,
                    time.monotonic() - started,
                )
                return _error_response(error)

    def shutdown(self) -> None:
        with self._lock:
            if self._manage_worker:
                self._stop_worker()

    def _ensure_worker(self, spec: ModelSpec) -> None:
        self._refresh_worker_state()
        previous_spec: ModelSpec | None = None
        if self._worker_process is not None and self._worker_state == "ready":
            if self._active_model == spec.id:
                return
            previous_spec = self._available_model_spec(self._active_model)
            self._stop_worker()
        elif self._worker_process is not None:
            raise ModelManagerError("MLX worker stopped before handling the request")

        try:
            self._start_worker(spec)
        except ModelManagerError as switch_error:
            if previous_spec is None:
                raise
            try:
                self._start_worker(previous_spec)
            except ModelManagerError as rollback_error:
                raise ModelManagerError("MLX worker switch and rollback failed") from rollback_error
            raise ModelManagerError("Requested model failed to start; previous model restored") from switch_error

    def _available_model_spec(self, model_id: str | None) -> ModelSpec | None:
        if model_id is None:
            return None
        spec = self._models.get(model_id)
        if spec is None or not _model_source_is_available(spec.path):
            return None
        return ModelSpec(spec.id, spec.label, _resolve_model_source(spec.path))

    def _start_worker(self, spec: ModelSpec) -> None:
        if not shutil.which("mlx_lm.server"):
            raise ModelManagerError("mlx_lm.server is not installed")
        if _port_is_listening(self._worker_host, self._worker_port):
            raise ModelManagerError("MLX worker port is occupied by another process")

        command = [
            "mlx_lm.server",
            "--model",
            str(spec.path),
            "--host",
            self._worker_host,
            "--port",
            str(self._worker_port),
            "--chat-template-args",
            '{"enable_thinking":false}',
            "--temp",
            "0",
            "--max-tokens",
            str(DEFAULT_WORKER_MAX_TOKENS),
            "--prompt-cache-size",
            "2",
        ]
        self._worker_state = "starting"
        self._active_model = spec.id
        try:
            self._worker_process = self._popen_factory(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self._worker_state = "error"
            self._active_model = None
            raise ModelManagerError("Failed to start MLX worker") from exc

        deadline = time.monotonic() + self._startup_timeout_seconds
        while time.monotonic() < deadline:
            if self._worker_process.poll() is not None:
                self._worker_process = None
                self._worker_state = "error"
                self._active_model = None
                raise ModelManagerError("MLX worker exited during startup")
            if _worker_is_healthy(self._worker_host, self._worker_port):
                self._worker_state = "ready"
                return
            time.sleep(0.1)
        self._stop_worker()
        self._worker_state = "error"
        raise ModelManagerError("MLX worker startup timed out")

    def _stop_worker(self) -> None:
        process = self._worker_process
        self._worker_process = None
        self._active_model = None
        self._worker_state = "stopped"
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def _refresh_worker_state(self) -> None:
        process = self._worker_process
        if process is None:
            if self._worker_state != "error":
                self._worker_state = "stopped"
            return
        if process.poll() is not None:
            self._worker_process = None
            self._active_model = None
            self._worker_state = "error"
            return
        if _worker_is_healthy(self._worker_host, self._worker_port):
            self._worker_state = "ready"
        elif self._worker_state == "ready":
            self._worker_state = "error"

    def _post_worker(self, payload: dict[str, Any]) -> tuple[int, bytes, str]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        connection = http.client.HTTPConnection(
            self._worker_host,
            self._worker_port,
            timeout=self._request_timeout_seconds,
        )
        headers = {"Content-Type": "application/json"}
        if self._worker_api_key:
            headers["Authorization"] = f"Bearer {self._worker_api_key}"
        try:
            connection.request(
                "POST",
                f"{self._worker_base_path}/v1/chat/completions" if self._manage_worker else f"{self._worker_base_path}/chat/completions",
                body=body,
                headers=headers,
            )
            response = connection.getresponse()
            return response.status, response.read(), "application/json"
        finally:
            connection.close()




class CatalogModelManager:
    """Route only catalog allowlisted logical models to their configured workers.

    Discovery is short-lived and guarded independently from requests, so a slow
    inference never blocks the public model registry or health control plane.
    """

    def __init__(self, catalog: ModelCatalog, environ: Mapping[str, str] | None = None) -> None:
        self._catalog = catalog
        self._environ = os.environ if environ is None else environ
        self._routes = {
            model.id: (worker, model)
            for worker in catalog.workers
            for model in worker.models
            if model.enabled
        }
        self._discovery_lock = threading.Lock()
        self._live_model_ids: frozenset[str] = frozenset()
        self._discovered_at = 0.0
        self._active_model: str | None = None
        self._state_lock = threading.Lock()

    def models_payload(self) -> dict[str, Any]:
        live_ids = self._live_models()
        return {
            "object": "list",
            "default_model_id": self._catalog.default_model_id,
            "data": [
                {"id": model_id, "object": "model", "name": self._routes[model_id][1].label}
                for model_id in self._routes
                if model_id in live_ids
            ],
        }

    def health_payload(self) -> dict[str, str | None]:
        live_ids = self._live_models()
        with self._state_lock:
            active_model = self._active_model
        return {
            "status": "ok",
            "active_model": active_model,
            "worker_state": "ready" if live_ids else "no_models",
        }

    def proxy_chat_completion(self, payload: dict[str, Any]) -> tuple[int, bytes, str]:
        model_id = payload.get("model")
        if not isinstance(model_id, str) or model_id not in self._routes:
            return _error_response(ModelNotFoundError("Requested model is not registered"))
        if model_id not in self._live_models():
            return _error_response(ModelManagerError("Requested model is unavailable"))
        worker, model = self._routes[model_id]
        request_payload = dict(payload)
        request_payload["model"] = model.upstream_id
        try:
            status, body, content_type = self._request_worker(worker, "POST", "/chat/completions", request_payload)
            if not 200 <= status < 300:
                raise WorkerResponseError("Model worker rejected the request")
            response_payload = _parse_worker_response(body)
            response_payload["model"] = model_id
            with self._state_lock:
                self._active_model = model_id
            return 200, json.dumps(response_payload, ensure_ascii=False).encode("utf-8"), content_type
        except ModelManagerError as exc:
            return _error_response(exc)
        except (OSError, http.client.HTTPException, ValueError):
            return _error_response(ModelManagerError("Model worker is unavailable"))

    def shutdown(self) -> None:
        return None

    def _live_models(self) -> frozenset[str]:
        now = time.monotonic()
        if now - self._discovered_at < self._catalog.discovery_ttl_seconds:
            return self._live_model_ids
        # Do not wait behind an in-flight discovery: existing cached information
        # is preferable to contending with a long-running inference or worker.
        if not self._discovery_lock.acquire(blocking=False):
            return self._live_model_ids
        try:
            now = time.monotonic()
            if now - self._discovered_at < self._catalog.discovery_ttl_seconds:
                return self._live_model_ids
            found: set[str] = set()
            with ThreadPoolExecutor(max_workers=len(self._catalog.workers)) as executor:
                for worker_models in executor.map(self._discover_worker_models, self._catalog.workers):
                    found.update(worker_models)
            self._live_model_ids = frozenset(found)
            self._discovered_at = time.monotonic()
            return self._live_model_ids
        finally:
            self._discovery_lock.release()

    def _discover_worker_models(self, worker: CatalogWorker) -> frozenset[str]:
        try:
            status, body, _ = self._request_worker(worker, "GET", "/models", None)
            if not 200 <= status < 300:
                return frozenset()
            payload = json.loads(body)
            upstream_ids = {
                item.get("id")
                for item in payload.get("data", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            } if isinstance(payload, dict) else set()
            return frozenset(
                model.id
                for model in worker.models
                if model.enabled and model.upstream_id in upstream_ids
            )
        except (OSError, ValueError, http.client.HTTPException):
            # One unavailable worker must not hide models from another.
            return frozenset()

    def _request_worker(
        self,
        worker: CatalogWorker,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None,
    ) -> tuple[int, bytes, str]:
        from urllib.parse import urlsplit

        parsed = urlsplit(worker.base_url)
        connection_class = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        connection = connection_class(parsed.hostname, parsed.port, timeout=(
            worker.discovery_timeout_seconds if method == "GET" else worker.request_timeout_seconds
        ))
        headers: dict[str, str] = {}
        body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if worker.api_key_env:
            api_key = self._environ.get(worker.api_key_env, "")
            if worker.id == "legacy-qwen-worker" and not api_key:
                api_key = DEFAULT_WORKER_API_KEY
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        try:
            connection.request(method, f"{parsed.path.rstrip('/')}{endpoint}", body=body, headers=headers)
            response = connection.getresponse()
            return response.status, response.read(), "application/json"
        finally:
            connection.close()


def create_model_manager_app(manager: Any) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            manager.shutdown()

    app = FastAPI(title="legal-redactor local model manager", version="0.2.2", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str | None]:
        return manager.health_payload()

    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        return manager.models_payload()

    @app.post("/v1/chat/completions")
    def chat_completions(payload: dict[str, Any]) -> Response:
        status, body, content_type = manager.proxy_chat_completion(payload)
        return Response(content=body, status_code=status, media_type=content_type)

    return app


def default_model_manager() -> Any:
    """Build the production catalog router; legacy MLX management remains test-only."""
    return CatalogModelManager(load_model_catalog_from_environment())


def _parse_worker_base_url(value: str) -> tuple[str, int, str]:
    from urllib.parse import urlsplit

    parsed = urlsplit(value.strip())
    if parsed.scheme != "http" or not parsed.hostname:
        raise RuntimeError("LEGAL_REDACTOR_MODEL_WORKER_BASE_URL must be an http URL")
    try:
        port = parsed.port or 80
    except ValueError as exc:
        raise RuntimeError("LEGAL_REDACTOR_MODEL_WORKER_BASE_URL has an invalid port") from exc
    base_path = parsed.path.rstrip("/")
    if not base_path:
        raise RuntimeError("LEGAL_REDACTOR_MODEL_WORKER_BASE_URL must include an API base path")
    return parsed.hostname, port, base_path


def discover_model_specs(
    search_roots: tuple[Path, ...] = DEFAULT_MODEL_SEARCH_ROOTS,
) -> dict[str, ModelSpec]:
    discovered: dict[str, ModelSpec] = {}
    for root in search_roots:
        expanded_root = root.expanduser()
        if not expanded_root.is_dir():
            continue
        candidates = [expanded_root]
        try:
            candidates.extend(sorted(path for path in expanded_root.iterdir() if path.is_dir()))
        except OSError:
            continue
        for candidate in candidates:
            if candidate.name in BUILTIN_MODEL_SOURCE_NAMES:
                continue
            if not _model_source_is_available(candidate) or not _is_supported_discovered_model(candidate):
                continue
            model_id = _logical_model_id(candidate.name)
            if (
                not model_id
                or model_id in discovered
                or model_id in INCOMPATIBLE_FULL_DOCUMENT_MODEL_IDS
            ):
                continue
            discovered[model_id] = ModelSpec(
                model_id,
                _model_display_label(candidate.name),
                candidate,
            )
    return discovered


def _logical_model_id(directory_name: str) -> str:
    name = directory_name.strip()
    if name.startswith("models--"):
        name = name.removeprefix("models--").replace("--", "/")
    return name


def _model_display_label(directory_name: str) -> str:
    model_id = _logical_model_id(directory_name)
    return model_id.rsplit("/", 1)[-1] or model_id


def _resolve_model_source(source: Path | str) -> Path | str:
    value = str(source).strip()
    path = Path(value).expanduser()
    if (path / "config.json").is_file():
        return path
    refs_main = path / "refs" / "main"
    if refs_main.is_file():
        try:
            revision = refs_main.read_text(encoding="utf-8").strip()
        except OSError:
            revision = ""
        snapshot = path / "snapshots" / revision
        if revision and (snapshot / "config.json").is_file():
            return snapshot
    return source


def _is_supported_discovered_model(source: Path | str) -> bool:
    resolved = _resolve_model_source(source)
    config_path = Path(str(resolved)).expanduser() / "config.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    model_type = payload.get("model_type")
    if not isinstance(model_type, str):
        text_config = payload.get("text_config")
        model_type = text_config.get("model_type") if isinstance(text_config, dict) else None
    return model_type in SUPPORTED_MODEL_TYPES


def _model_source_is_available(source: Path | str) -> bool:
    value = str(source).strip()
    if not value:
        return False
    resolved = _resolve_model_source(source)
    path = Path(str(resolved)).expanduser()
    if path.is_dir():
        return (path / "config.json").is_file()
    return not path.is_absolute() and value.count("/") == 1


def _worker_is_healthy(host: str, port: int) -> bool:
    connection: http.client.HTTPConnection | None = None
    try:
        connection = http.client.HTTPConnection(host, port, timeout=0.5)
        connection.request("GET", "/health")
        response = connection.getresponse()
        body = response.read()
    except (OSError, http.client.HTTPException):
        return False
    finally:
        if connection is not None:
            connection.close()
    if response.status != 200:
        return False
    try:
        payload = json.loads(body)
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("status") == "ok"


def _port_is_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def _parse_worker_response(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidWorkerResponseError("MLX worker returned invalid JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("choices"), list):
        raise InvalidWorkerResponseError("MLX worker returned an invalid completion")
    return payload

def _safe_manager_reason(error: ModelManagerError) -> str:
    message = str(error)
    labels = {
        "Registered model is unavailable": "model_source_unavailable",
        "mlx_lm.server is not installed": "mlx_server_not_installed",
        "MLX worker port is occupied by another process": "worker_port_occupied",
        "Failed to start MLX worker": "worker_spawn_failed",
        "MLX worker exited during startup": "worker_exited_during_startup",
        "MLX worker startup timed out": "worker_startup_timeout",
        "Requested model failed to start; previous model restored": "model_switch_failed_previous_restored",
        "MLX worker switch and rollback failed": "model_switch_and_rollback_failed",
        "MLX worker rejected the request": "worker_rejected_request",
    }
    return labels.get(message, "model_manager_error")



def _error_response(error: ModelManagerError) -> tuple[int, bytes, str]:
    payload = {
        "error": {
            "message": "The requested local model is unavailable.",
            "type": "server_error" if error.status_code >= 500 else "invalid_request_error",
            "code": error.code,
        }
    }
    return error.status_code, json.dumps(payload).encode("utf-8"), "application/json"


app = create_model_manager_app(default_model_manager())
