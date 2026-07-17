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

BONSAI_MODEL_ID = "bonsai-27b"
BONSAI_MODEL_LABEL = "Ternary Bonsai 27B（MLX 2-bit）"
DEFAULT_MODEL_PATH = Path.home() / "Models/HuggingFace/prism-ml/Ternary-Bonsai-27B-mlx-2bit"
DEFAULT_WORKER_HOST = "127.0.0.1"
DEFAULT_WORKER_PORT = 18081


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    path: Path


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
    ) -> None:
        self._models = dict(models)
        self._worker_host = worker_host
        self._worker_port = worker_port
        self._startup_timeout_seconds = startup_timeout_seconds
        self._popen_factory = popen_factory
        self._lock = threading.RLock()
        self._worker_process: subprocess.Popen[bytes] | None = None
        self._active_model: str | None = None
        self._worker_state = "stopped"

    def models_payload(self) -> dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {"id": spec.id, "object": "model"}
                for spec in self._models.values()
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
            spec = self._models.get(model_id)
            if spec is None:
                raise ModelNotFoundError("Requested model is not registered")
            if not (spec.path / "config.json").is_file():
                raise ModelManagerError("Registered model is unavailable")
            self._ensure_worker()
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

    def _ensure_worker(self) -> None:
        self._refresh_worker_state()
        if self._worker_process is not None and self._worker_state == "ready":
            return
        if self._worker_process is not None:
            raise ModelManagerError("MLX worker stopped before handling the request")
        if not shutil.which("mlx_lm.server"):
            raise ModelManagerError("mlx_lm.server is not installed")
        if _port_is_listening(self._worker_host, self._worker_port):
            raise ModelManagerError("MLX worker port is occupied by another process")

        command = [
            "mlx_lm.server",
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
        try:
            self._worker_process = self._popen_factory(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self._worker_state = "error"
            raise ModelManagerError("Failed to start MLX worker") from exc

        deadline = time.monotonic() + self._startup_timeout_seconds
        while time.monotonic() < deadline:
            if self._worker_process.poll() is not None:
                self._worker_state = "error"
                raise ModelManagerError("MLX worker exited during startup")
            if _worker_is_healthy(self._worker_host, self._worker_port):
                self._worker_state = "ready"
                return
            time.sleep(0.1)
        self._worker_state = "error"
        raise ModelManagerError("MLX worker startup timed out")

    def _refresh_worker_state(self) -> None:
        process = self._worker_process
        if process is None:
            if self._worker_state != "error":
                self._worker_state = "stopped"
            return
        if process.poll() is not None:
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
    spec = ModelSpec(BONSAI_MODEL_ID, BONSAI_MODEL_LABEL, DEFAULT_MODEL_PATH)
    return ModelManager({spec.id: spec}, worker_host, worker_port)


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
