from __future__ import annotations

import json
import subprocess
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from legal_redactor.model_manager import (
    ModelManager,
    ModelSpec,
    create_model_manager_app,
    discover_model_specs,
)


class _FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class _WorkerHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []
    status = 200
    payload: object = {"id": "chatcmpl-1", "model": "/private/model", "choices": [{"message": {"content": "{}"}}]}

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._respond(200, {"status": "ok"})
            return
        self._respond(404, {})

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.requests.append(json.loads(body))
        self._respond(self.status, self.payload)

    def _respond(self, status: int, payload: object) -> None:
        if isinstance(payload, bytes):
            body = payload
        else:
            body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        del format, args


class _WorkerServer:
    def __enter__(self) -> "_WorkerServer":
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _WorkerHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()


def _manager(tmp_path: Path, port: int, created: list[_FakeProcess]) -> ModelManager:
    model_path = tmp_path / "model"
    model_path.mkdir()
    (model_path / "config.json").write_text("{}", encoding="utf-8")

    def popen(command: list[str], **kwargs: object) -> _FakeProcess:
        assert kwargs == {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        assert command[command.index("--model") + 1] == str(model_path)
        created.append(_FakeProcess())
        return created[-1]

    spec = ModelSpec("bonsai-27b", "Test Bonsai", model_path)
    return ModelManager({spec.id: spec}, "127.0.0.1", port, startup_timeout_seconds=1, popen_factory=popen)


def test_manager_exposes_only_registered_logical_model(tmp_path: Path) -> None:
    created: list[_FakeProcess] = []
    manager = _manager(tmp_path, _unused_port(), created)
    client = TestClient(create_model_manager_app(manager))

    assert client.get("/v1/models").json() == {
        "object": "list",
        "data": [{"id": "bonsai-27b", "object": "model", "name": "Test Bonsai"}],
    }
    assert client.get("/health").json() == {
        "status": "ok",
        "active_model": None,
        "worker_state": "stopped",
    }


def test_manager_rewrites_model_and_reuses_owned_worker(tmp_path: Path, monkeypatch) -> None:
    _WorkerHandler.requests = []
    _WorkerHandler.status = 200
    _WorkerHandler.payload = {"id": "chatcmpl-1", "model": "/private/model", "choices": [{"message": {"content": "{}"}}]}
    created: list[_FakeProcess] = []
    monkeypatch.setattr("legal_redactor.model_manager._port_is_listening", lambda host, port: False)
    with _WorkerServer() as worker:
        manager = _manager(tmp_path, worker.port, created)
        client = TestClient(create_model_manager_app(manager))
        request = {"model": "bonsai-27b", "messages": [{"role": "user", "content": "private source text"}], "stream": False}

        first = client.post("/v1/chat/completions", json=request)
        second = client.post("/v1/chat/completions", json=request)
        health = manager.health_payload()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["model"] == "bonsai-27b"
    assert len(created) == 1
    assert _WorkerHandler.requests[0]["model"] == str(tmp_path / "model")
    assert _WorkerHandler.requests[0]["messages"] == request["messages"]
    assert health == {"status": "ok", "active_model": "bonsai-27b", "worker_state": "ready"}
    manager.shutdown()
    assert created[0].terminated

def test_manager_starts_worker_without_inheriting_output(tmp_path: Path, monkeypatch) -> None:
    _WorkerHandler.requests = []
    _WorkerHandler.status = 200
    _WorkerHandler.payload = {"choices": [{"message": {"content": "{}"}}]}
    calls: list[tuple[list[str], dict]] = []
    model_path = tmp_path / "model"
    model_path.mkdir()
    (model_path / "config.json").write_text("{}", encoding="utf-8")

    def popen(command: list[str], **kwargs) -> _FakeProcess:
        calls.append((command, kwargs))
        return _FakeProcess()

    monkeypatch.setattr("legal_redactor.model_manager._port_is_listening", lambda host, port: False)
    with _WorkerServer() as worker:
        spec = ModelSpec("bonsai-27b", "Test Bonsai", model_path)
        manager = ModelManager({spec.id: spec}, "127.0.0.1", worker.port, startup_timeout_seconds=1, popen_factory=popen)
        response = TestClient(create_model_manager_app(manager)).post("/v1/chat/completions", json={"model": "bonsai-27b"})
    assert response.status_code == 200

    assert len(calls) == 1
    assert calls[0][1] == {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    assert calls[0][0][calls[0][0].index("--model") + 1] == str(model_path)
    manager.shutdown()


def test_manager_switches_owned_worker_when_model_changes(tmp_path: Path, monkeypatch) -> None:
    first_path = tmp_path / "first"
    second_path = tmp_path / "second"
    for path in (first_path, second_path):
        path.mkdir()
        (path / "config.json").write_text("{}", encoding="utf-8")
    created: list[_FakeProcess] = []

    def popen(command: list[str], **kwargs: object) -> _FakeProcess:
        del command, kwargs
        created.append(_FakeProcess())
        return created[-1]

    monkeypatch.setattr("legal_redactor.model_manager._port_is_listening", lambda host, port: False)
    with _WorkerServer() as worker:
        manager = ModelManager(
            {
                "first": ModelSpec("first", "First", first_path),
                "second": ModelSpec("second", "Second", second_path),
            },
            "127.0.0.1",
            worker.port,
            startup_timeout_seconds=1,
            popen_factory=popen,
        )
        client = TestClient(create_model_manager_app(manager))
        assert client.post("/v1/chat/completions", json={"model": "first"}).status_code == 200
        assert client.post("/v1/chat/completions", json={"model": "second"}).status_code == 200

    assert len(created) == 2
    assert created[0].terminated
    assert manager.health_payload()["active_model"] == "second"
    manager.shutdown()


def test_manager_hides_unavailable_models_from_registry(tmp_path: Path) -> None:
    available = tmp_path / "available"
    available.mkdir()
    (available / "config.json").write_text("{}", encoding="utf-8")
    manager = ModelManager(
        {
            "available": ModelSpec("available", "Available", available),
            "missing": ModelSpec("missing", "Missing", tmp_path / "missing"),
        },
        "127.0.0.1",
        _unused_port(),
    )

    assert manager.models_payload()["data"] == [
        {"id": "available", "object": "model", "name": "Available"}
    ]


def test_discovery_registers_direct_and_huggingface_cache_models(tmp_path: Path) -> None:
    direct = tmp_path / "Acme-7B-MLX-4bit"
    direct.mkdir()
    (direct / "config.json").write_text('{"model_type":"qwen3"}', encoding="utf-8")

    cached = tmp_path / "models--mlx-community--Fresh-Model-MLX-8bit"
    snapshot = cached / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (cached / "refs").mkdir()
    (cached / "refs" / "main").write_text("abc123", encoding="utf-8")
    (snapshot / "config.json").write_text('{"model_type":"llama"}', encoding="utf-8")
    embedding = tmp_path / "models--sentence-transformers--Embedding"
    embedding_snapshot = embedding / "snapshots" / "def456"
    embedding_snapshot.mkdir(parents=True)
    (embedding / "refs").mkdir()
    (embedding / "refs" / "main").write_text("def456", encoding="utf-8")
    (embedding_snapshot / "config.json").write_text('{"model_type":"bert"}', encoding="utf-8")

    discovered = discover_model_specs((tmp_path,))

    assert set(discovered) == {
        "Acme-7B-MLX-4bit",
        "mlx-community/Fresh-Model-MLX-8bit",
    }
    assert discovered["Acme-7B-MLX-4bit"].label == "Acme-7B-MLX-4bit"
    assert discovered["mlx-community/Fresh-Model-MLX-8bit"].label == "Fresh-Model-MLX-8bit"


def test_manager_refreshes_discovered_models_without_restart(tmp_path: Path) -> None:
    model_dir = tmp_path / "First-MLX"
    model_dir.mkdir()
    (model_dir / "config.json").write_text('{"model_type":"qwen3"}', encoding="utf-8")
    def discovery() -> dict[str, ModelSpec]:
        return discover_model_specs((tmp_path,))

    manager = ModelManager(
        discovery(),
        "127.0.0.1",
        _unused_port(),
        model_discovery=discovery,
    )

    assert {item["id"] for item in manager.models_payload()["data"]} >= {"First-MLX"}

    second = tmp_path / "Second-MLX"
    second.mkdir()
    (second / "config.json").write_text('{"model_type":"llama"}', encoding="utf-8")

    assert {item["id"] for item in manager.models_payload()["data"]} >= {"First-MLX", "Second-MLX"}


def test_manager_scrubs_unknown_and_worker_errors(tmp_path: Path, monkeypatch) -> None:
    created: list[_FakeProcess] = []
    monkeypatch.setattr("legal_redactor.model_manager._port_is_listening", lambda host, port: False)
    with _WorkerServer() as worker:
        manager = _manager(tmp_path, worker.port, created)
        client = TestClient(create_model_manager_app(manager))

        unknown = client.post("/v1/chat/completions", json={"model": "../../private/model"})
        _WorkerHandler.status = 500
        _WorkerHandler.payload = {"error": {"message": "/private/model failed"}}
        worker_error = client.post("/v1/chat/completions", json={"model": "bonsai-27b"})
        _WorkerHandler.status = 200
        _WorkerHandler.payload = {"model": "/private/model"}
        invalid = client.post("/v1/chat/completions", json={"model": "bonsai-27b"})

    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "model_not_found"
    assert worker_error.status_code == 502
    assert worker_error.json()["error"]["code"] == "worker_error"
    assert invalid.status_code == 502
    assert invalid.json()["error"]["code"] == "invalid_worker_response"
    assert "/private/model" not in worker_error.text


def test_manager_rejects_missing_model_without_starting_worker(tmp_path: Path) -> None:
    created: list[_FakeProcess] = []
    missing = tmp_path / "missing"
    manager = ModelManager(
        {"bonsai-27b": ModelSpec("bonsai-27b", "Test Bonsai", missing)},
        "127.0.0.1",
        _unused_port(),
        startup_timeout_seconds=0.01,
        popen_factory=lambda command: created.append(_FakeProcess()) or created[-1],
    )
    response = TestClient(create_model_manager_app(manager)).post("/v1/chat/completions", json={"model": "bonsai-27b"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_unavailable"
    assert created == []


def test_manager_never_terminates_unowned_port_listener(tmp_path: Path) -> None:
    created: list[_FakeProcess] = []
    with _WorkerServer() as worker:
        manager = _manager(tmp_path, worker.port, created)
        response = TestClient(create_model_manager_app(manager)).post("/v1/chat/completions", json={"model": "bonsai-27b"})
        manager.shutdown()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_unavailable"
    assert created == []


def _unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
