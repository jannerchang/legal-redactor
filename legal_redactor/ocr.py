from __future__ import annotations

import base64
import fcntl
import json
import os
import re
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ._logging import get_logger

_OCR_BASE_URL = "http://127.0.0.1:18081/v1"
_OCR_MODEL = str(Path.home() / "Library/Application Support/legal-redactor/unlimited-ocr-mlx/model")
_OCR_LAUNCH_LABEL = "com.legal-redactor.unlimited-ocr"
_OCR_LOCK_PATH = Path.home() / ".local/state/legal-redactor/unlimited-ocr.lock"
_OCR_OUTPUT_DIR = Path.home() / "Documents" / "legal-redactor-ocr"
_OCR_READY_TIMEOUT_SECONDS = 60
_TEXT_LAYER_MIN_CHARS = 20
_DET_RE = re.compile(r"<\|det\|>([^<\s]+)(?:\s*\[[^\]]*\])?\s*<\|/det\|>(.*)", re.DOTALL)
_REF_RE = re.compile(r"<\|/?ref\|>")
_UNSAFE_OCR_NAME_RE = re.compile(r"[^A-Za-z0-9._\u4e00-\u9fff-]+")
_logger = get_logger(__name__)
_OCR_OUTPUT_PATHS: dict[str, str] = {}


class OCRUnavailableError(RuntimeError):
    pass


def persist_ocr_text(filename: str, text: str) -> Path | None:
    """Write OCR text next to other local redaction artifacts so LLM failure still leaves a copy."""
    if not text.strip():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    stem = _UNSAFE_OCR_NAME_RE.sub("_", Path(filename).name).strip("._")[:80] or "document"
    directory = _OCR_OUTPUT_DIR / stamp
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}.ocr.txt"
    if path.exists():
        path = directory / f"{stem}-{os.getpid()}.ocr.txt"
    path.write_text(text, encoding="utf-8")
    _OCR_OUTPUT_PATHS[filename] = str(path)
    _logger.info("OCR 原文已保存：%s", path)
    return path


def take_ocr_output_paths() -> dict[str, str]:
    paths = dict(_OCR_OUTPUT_PATHS)
    _OCR_OUTPUT_PATHS.clear()
    return paths


def clean_unlimited_ocr(raw: str) -> str:
    raw = _decode_bpe_bytes(raw)
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for source_line in raw.splitlines():
        line = source_line.rstrip()
        if not line:
            continue
        match = _DET_RE.match(line)
        if match:
            category, content = match.group(1).strip(), match.group(2).strip()
            if category == "image":
                continue
            if current is not None:
                blocks.append(current)
            current = [content] if content else []
            continue
        if current is None:
            current = []
        current.append(line)
    if current is not None:
        blocks.append(current)
    return _REF_RE.sub("", "\n\n".join("\n".join(block) for block in blocks).strip())


def _decode_bpe_bytes(value: str) -> str:
    decoder: dict[str, int] = {}
    limits = [0, ord("!"), ord("~") + 1, ord("¡"), ord("¬") + 1, ord("®"), ord("ÿ") + 1]
    offset = 0
    for index, (start, stop) in enumerate(zip(limits, limits[1:])):
        if index % 2 == 0:
            for byte_value in range(start, stop):
                decoder[chr(256 + offset)] = byte_value
                offset += 1
        else:
            for byte_value in range(start, stop):
                decoder[chr(byte_value)] = byte_value

    output: list[str] = []
    encoded = bytearray()

    def flush() -> None:
        if encoded:
            output.append(encoded.decode("utf-8", errors="replace"))
            encoded.clear()

    for character in value:
        byte_value = decoder.get(character)
        if byte_value is None:
            flush()
            output.append(character)
        else:
            encoded.append(byte_value)
    flush()
    return "".join(output)


def pdf_page_texts(data: bytes, filename: str) -> tuple[list[str], list[int]]:
    try:
        import pymupdf
    except ImportError as exc:
        raise OCRUnavailableError("扫描 PDF 处理需要安装 PyMuPDF") from exc
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            texts = [page.get_text("text").strip() for page in document]
    except Exception as exc:
        raise ValueError(f"读取文件 {filename} 失败: PDF 格式无效或文件已损坏") from exc
    needs_ocr = [
        index for index, text in enumerate(texts, start=1) if len(text) < _TEXT_LAYER_MIN_CHARS
    ]
    return texts, needs_ocr


@contextmanager
def ocr_runtime(enabled: bool) -> Iterator[None]:
    if not enabled:
        yield
        return
    _OCR_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _OCR_LOCK_PATH.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        started = False
        try:
            _start_local_ocr()
            started = True
            _wait_for_ocr()
            yield
        finally:
            if started:
                _stop_local_ocr()
            fcntl.flock(lock, fcntl.LOCK_UN)


def extract_pdf_text(data: bytes, filename: str, *, page_texts: list[str] | None = None) -> str:
    texts, needs_ocr = (
        pdf_page_texts(data, filename)
        if page_texts is None
        else (
            page_texts,
            [
                index
                for index, text in enumerate(page_texts, start=1)
                if len(text) < _TEXT_LAYER_MIN_CHARS
            ],
        )
    )
    if not needs_ocr:
        return "\n\n".join(texts)

    ocr_pages = _recognize_pages(data, needs_ocr)
    missing = [page for page in needs_ocr if not ocr_pages.get(page, "").strip()]
    if missing:
        raise OCRUnavailableError(f"文件 {filename} 的第 {missing[0]} 页 OCR 未返回有效文字")
    text = "\n\n".join(
        ocr_pages.get(index, page_text) for index, page_text in enumerate(texts, start=1)
    )
    persist_ocr_text(filename, text)
    return text


def _recognize_pages(data: bytes, pages: list[int]) -> dict[int, str]:
    import pymupdf

    results: dict[int, str] = {}
    with pymupdf.open(stream=data, filetype="pdf") as document:
        for page_number in pages:
            image = (
                document[page_number - 1]
                .get_pixmap(
                    matrix=pymupdf.Matrix(200 / 72, 200 / 72),
                    alpha=False,
                )
                .tobytes("png")
            )
            encoded = base64.b64encode(image).decode("ascii")
            payload = {
                "model": _OCR_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Free OCR."},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{encoded}"},
                            },
                        ],
                    }
                ],
                "stream": False,
                "temperature": 0,
                "max_tokens": 4096,
                "repetition_penalty": 1.05,
            }
            body = _curl_json(f"{_OCR_BASE_URL}/chat/completions", payload, timeout=1200)
            try:
                raw = body["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as exc:
                raise OCRUnavailableError(f"第 {page_number} 页 OCR 返回格式无效") from exc
            cleaned = clean_unlimited_ocr(str(raw))
            if not cleaned:
                raise OCRUnavailableError(f"第 {page_number} 页 OCR 返回空文字")
            results[page_number] = cleaned
    return results


def _start_local_ocr() -> None:
    service = f"gui/{os.getuid()}/{_OCR_LAUNCH_LABEL}"
    completed = subprocess.run(
        ["/bin/launchctl", "kickstart", "-k", service],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise OCRUnavailableError(f"Mac 本地 OCR 服务启动失败：{detail or completed.returncode}")


def _stop_local_ocr() -> None:
    subprocess.run(
        ["/bin/launchctl", "kill", "SIGTERM", f"gui/{os.getuid()}/{_OCR_LAUNCH_LABEL}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _wait_for_ocr() -> None:
    deadline = time.monotonic() + _OCR_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            payload = _curl_json("http://127.0.0.1:18081/health", timeout=3)
            if payload.get("status") == "healthy":
                return
        except OCRUnavailableError:
            time.sleep(1)
    raise OCRUnavailableError("Mac 本地 Unlimited OCR 未在 60 秒内就绪")


def _curl_json(url: str, payload: dict | None = None, *, timeout: float) -> dict:
    command = [
        "/usr/bin/curl",
        "--noproxy",
        "*",
        "--silent",
        "--show-error",
        "--fail-with-body",
        "--max-time",
        str(timeout),
    ]
    stdin = None
    if payload is not None:
        command.extend(["--header", "Content-Type: application/json", "--data-binary", "@-"])
        stdin = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    command.append(url)
    try:
        completed = subprocess.run(
            command,
            input=stdin,
            capture_output=True,
            check=False,
            timeout=timeout + 5,
        )
    except subprocess.TimeoutExpired as exc:
        raise OCRUnavailableError("Unlimited OCR 请求超时") from exc
    if completed.returncode != 0:
        raise OCRUnavailableError("Unlimited OCR API 不可用")
    try:
        body = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise OCRUnavailableError("Unlimited OCR API 返回无效 JSON") from exc
    if not isinstance(body, dict):
        raise OCRUnavailableError("Unlimited OCR API 返回格式无效")
    return body
