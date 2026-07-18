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
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import Response

DEFAULT_MODEL_ID = "bonsai-27b"
BONSAI_MODEL_ID = DEFAULT_MODEL_ID
BONSAI_MODEL_LABEL = "Ternary Bonsai 27B（MLX 2-bit）"
QWEN_MODEL_ID = "qwen3.5-9b"
QWEN_MODEL_LABEL = "Qwen3.5 9B（MLX 4-bit）"
DEFAULT_MODEL_PATH = Path.home() / "Models/HuggingFace/prism-ml/Ternary-Bonsai-27B-mlx-2bit"
DEFAULT_QWEN_MODEL_PATH = (
    Path.home()
    / "Models/HuggingFace/hub/models--mlx-community--Qwen3.5-9B-MLX-4bit"
)
DEFAULT_WORKER_HOST = "127.0.0.1"
DEFAULT_WORKER_PORT = 18081
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
BUILTIN_MODEL_SOURCE_NAMES = frozenset(
    {
        "Ternary-Bonsai-27B-mlx-2bit",
        "models--prism-ml--Ternary-Bonsai-27B-mlx-2bit",
        "models--mlx-community--Qwen3.5-9B-MLX-4bit",
    }
)


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
    """Expose registered logical model IDs while owning one lazy MLX worker."""

    def __init__(
        self,
        models: Mapping[str, ModelSpec],
        worker_host: str,
        worker_port: int,
        startup_timeout_seconds: float = 130,
        popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        model_discovery: Callable[[], Mapping[str, ModelSpec]] | None = None,
    ) -> None:
        self._models = dict(models)
        self._model_discovery = model_discovery
        self._worker_host = worker_host
        self._worker_port = worker_port
        self._startup_timeout_seconds = startup_timeout_seconds
        self._popen_factory = popen_factory
        self._lock = threading.RLock()
        self._worker_process: subprocess.Popen[bytes] | None = None
        self._active_model: str | None = None
        self._worker_state = "stopped"

    def _refresh_models(self) -> None:
        if self._model_discovery is None:
            return
        discovered = dict(self._model_discovery())
        discovered[BONSAI_MODEL_ID] = ModelSpec(BONSAI_MODEL_ID, BONSAI_MODEL_LABEL, DEFAULT_MODEL_PATH)
        discovered[QWEN_MODEL_ID] = ModelSpec(
            QWEN_MODEL_ID,
            QWEN_MODEL_LABEL,
            os.environ.get("LEGAL_REDACTOR_QWEN_MODEL", str(DEFAULT_QWEN_MODEL_PATH)),
        )
        self._models = discovered


    def models_payload(self) -> dict[str, Any]:
        with self._lock:
            self._refresh_models()
            return {
                "object": "list",
                "data": [
                    {"id": spec.id, "object": "model", "name": spec.label}
                    for spec in self._models.values()
                    if _model_source_is_available(spec.path)
                ],
            }

    def health_payload(self) -> dict[str, str | None]:
        with self._lock:
            self._refresh_worker_state()
            return {
                "status": "ok",
                "active_model": self._active_model,
                "worker_state": self._worker_state,
            }

    def ensure_model(self, model_id: str) -> ModelSpec:
        with self._lock:
            self._refresh_models()
            spec = self._models.get(model_id)
            if spec is None:
                raise ModelNotFoundError("Requested model is not registered")
            if not _model_source_is_available(spec.path):
                raise ModelManagerError("Registered model is unavailable")
            spec = ModelSpec(spec.id, spec.label, _resolve_model_source(spec.path))
            self._ensure_worker(spec)
            return spec

    def proxy_chat_completion(self, payload: dict[str, Any]) -> tuple[int, bytes, str]:
        model_id = payload.get("model")
        if not isinstance(model_id, str) or not model_id:
            return _error_response(ModelNotFoundError("A registered model ID is required"))

        with self._lock:
            try:
                spec = self.ensure_model(model_id)
                worker_payload = dict(payload)
                worker_payload["model"] = str(spec.path)
                status, body, content_type = self._post_worker(worker_payload)
                if not 200 <= status < 300:
                    raise WorkerResponseError("MLX worker rejected the request")
                response_payload = _parse_worker_response(body)
                if "model" in response_payload:
                    response_payload["model"] = spec.id
                self._active_model = spec.id
                self._worker_state = "ready"
                return 200, json.dumps(response_payload, ensure_ascii=False).encode("utf-8"), content_type
            except ModelManagerError as exc:
                return _error_response(exc)
            except (OSError, http.client.HTTPException):
                self._refresh_worker_state()
                return _error_response(ModelManagerError("MLX worker is unavailable"))

    def shutdown(self) -> None:
        with self._lock:
            self._stop_worker()

    def _ensure_worker(self, spec: ModelSpec) -> None:
        self._refresh_worker_state()
        if self._worker_process is not None and self._worker_state == "ready":
            if self._active_model == spec.id:
                return
            self._stop_worker()
        elif self._worker_process is not None:
            raise ModelManagerError("MLX worker stopped before handling the request")
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
            "4096",
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
            timeout=self._startup_timeout_seconds,
        )
        try:
            connection.request(
                "POST",
                "/v1/chat/completions",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            return response.status, response.read(), "application/json"
        finally:
            connection.close()


def create_model_manager_app(manager: ModelManager) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            manager.shutdown()

    app = FastAPI(title="legal-redactor local model manager", version="0.1.2", lifespan=lifespan)

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


def default_model_manager() -> ModelManager:
    worker_host = os.environ.get("LEGAL_REDACTOR_MLX_WORKER_HOST", DEFAULT_WORKER_HOST)
    try:
        worker_port = int(os.environ.get("LEGAL_REDACTOR_MLX_WORKER_PORT", str(DEFAULT_WORKER_PORT)))
    except ValueError as exc:
        raise RuntimeError("LEGAL_REDACTOR_MLX_WORKER_PORT must be an integer") from exc
    if not 1 <= worker_port <= 65535:
        raise RuntimeError("LEGAL_REDACTOR_MLX_WORKER_PORT must be between 1 and 65535")
    models = discover_model_specs()
    models[BONSAI_MODEL_ID] = ModelSpec(BONSAI_MODEL_ID, BONSAI_MODEL_LABEL, DEFAULT_MODEL_PATH)
    models[QWEN_MODEL_ID] = ModelSpec(
        QWEN_MODEL_ID,
        QWEN_MODEL_LABEL,
        os.environ.get("LEGAL_REDACTOR_QWEN_MODEL", str(DEFAULT_QWEN_MODEL_PATH)),
    )
    return ModelManager(models, worker_host, worker_port, model_discovery=discover_model_specs)


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
            if not model_id or model_id in discovered:
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
