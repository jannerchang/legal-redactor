from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pymupdf
import pytest

from legal_redactor.ocr import (
    OCRUnavailableError,
    _curl_json,
    clean_unlimited_ocr,
    extract_pdf_text,
    pdf_page_texts,
    persist_ocr_text,
    take_ocr_output_paths,
)
from legal_redactor.web.documents import _read_input_documents


class _Upload:
    def __init__(self, filename: str, data: bytes = b"pdf") -> None:
        self.filename = filename
        self._data = data

    async def read(self) -> bytes:
        return self._data


def test_pdf_text_layer_preserves_article_177_without_ocr() -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Article 177 statutory reference must remain unchanged.")
    data = document.tobytes()
    document.close()

    pages, needs_ocr = pdf_page_texts(data, "judgment.pdf")

    assert needs_ocr == []
    assert "Article 177" in extract_pdf_text(data, "judgment.pdf", page_texts=pages)


def test_duplicate_pdf_names_keep_distinct_page_layers(monkeypatch) -> None:
    events: list[str] = []

    def page_texts(data: bytes, filename: str):
        return ([data.decode()], [])

    @contextmanager
    def runtime(enabled: bool):
        assert enabled is False
        yield

    def extract(data: bytes, filename: str, *, page_texts: list[str]):
        events.append(page_texts[0])
        return page_texts[0]

    monkeypatch.setattr("legal_redactor.web.deps.pdf_page_texts", page_texts)
    monkeypatch.setattr("legal_redactor.web.deps.ocr_runtime", runtime)
    monkeypatch.setattr("legal_redactor.web.deps.extract_pdf_text", extract)

    documents = asyncio.run(
        _read_input_documents(
            "",
            None,
            [
                _Upload("same.pdf", b"first searchable layer"),
                _Upload("same.pdf", b"second searchable layer"),
            ],
        )
    )

    assert [item.text for item in documents] == [
        "first searchable layer",
        "second searchable layer",
    ]
    assert events == ["first searchable layer", "second searchable layer"]


def test_multiple_pdfs_share_one_ocr_runtime_then_return_text(monkeypatch) -> None:
    events: list[object] = []

    def page_texts(data: bytes, filename: str):
        return ([""] if filename == "scan.pdf" else ["Article 177 searchable PDF text layer."]), (
            [1] if filename == "scan.pdf" else []
        )

    @contextmanager
    def runtime(enabled: bool):
        events.append(("runtime", enabled, "enter"))
        yield
        events.append(("runtime", enabled, "exit"))

    def extract(data: bytes, filename: str, *, page_texts: list[str]):
        events.append(("extract", filename))
        return "OCR 张三" if filename == "scan.pdf" else page_texts[0]

    monkeypatch.setattr("legal_redactor.web.deps.pdf_page_texts", page_texts)
    monkeypatch.setattr("legal_redactor.web.deps.ocr_runtime", runtime)
    monkeypatch.setattr("legal_redactor.web.deps.extract_pdf_text", extract)

    documents = asyncio.run(
        _read_input_documents("", None, [_Upload("scan.pdf"), _Upload("searchable.pdf")])
    )

    assert [(item.source_file, item.text) for item in documents] == [
        ("scan.pdf", "OCR 张三"),
        ("searchable.pdf", "Article 177 searchable PDF text layer."),
    ]
    assert events == [
        ("runtime", True, "enter"),
        ("extract", "scan.pdf"),
        ("extract", "searchable.pdf"),
        ("runtime", True, "exit"),
    ]


def test_legacy_single_pdf_reader_uses_ocr_runtime(monkeypatch) -> None:
    from legal_redactor.web.documents import _read_upload_text

    calls: list[object] = []

    @contextmanager
    def runtime(enabled: bool):
        calls.append(("runtime", enabled))
        yield

    monkeypatch.setattr("legal_redactor.web.deps.pdf_page_texts", lambda *_: ([""], [1]))
    monkeypatch.setattr("legal_redactor.web.deps.ocr_runtime", runtime)
    monkeypatch.setattr(
        "legal_redactor.web.deps.extract_pdf_text", lambda *args, **kwargs: "OCR text"
    )

    assert asyncio.run(_read_upload_text(_Upload("scan.pdf"))) == "OCR text"
    assert calls == [("runtime", True)]


def test_ocr_start_failure_stops_pdf_upload(monkeypatch) -> None:
    monkeypatch.setattr("legal_redactor.web.deps.pdf_page_texts", lambda *_: ([""], [1]))

    @contextmanager
    def failed_runtime(enabled: bool):
        assert enabled is True
        raise OCRUnavailableError("OCR API 不可用")
        yield

    monkeypatch.setattr("legal_redactor.web.deps.ocr_runtime", failed_runtime)

    with pytest.raises(ValueError, match="扫描 PDF OCR 失败"):
        asyncio.run(_read_input_documents("", None, [_Upload("scan.pdf")]))


def test_ocr_runtime_uses_local_launch_agent_not_spark(monkeypatch, tmp_path) -> None:
    from legal_redactor import ocr

    lock_path = tmp_path / "ocr.lock"
    events: list[str] = []
    monkeypatch.setattr(ocr, "_OCR_LOCK_PATH", lock_path)
    monkeypatch.setattr(ocr, "_start_local_ocr", lambda: events.append("start"))
    monkeypatch.setattr(ocr, "_wait_for_ocr", lambda: events.append("ready"))
    monkeypatch.setattr(ocr, "_stop_local_ocr", lambda: events.append("stop"))

    with ocr.ocr_runtime(True):
        events.append("body")

    assert events == ["start", "ready", "body", "stop"]


def test_ocr_runtime_holds_lock_for_entire_ocr_session(monkeypatch, tmp_path) -> None:
    from legal_redactor import ocr

    monkeypatch.setattr(ocr, "_OCR_LOCK_PATH", tmp_path / "ocr.lock")
    monkeypatch.setattr(ocr, "_start_local_ocr", lambda: None)
    monkeypatch.setattr(ocr, "_wait_for_ocr", lambda: None)
    monkeypatch.setattr(ocr, "_stop_local_ocr", lambda: None)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first() -> None:
        with ocr.ocr_runtime(True):
            first_entered.set()
            release_first.wait(timeout=2)

    def second() -> None:
        first_entered.wait(timeout=2)
        with ocr.ocr_runtime(True):
            second_entered.set()

    one = threading.Thread(target=first)
    two = threading.Thread(target=second)
    one.start()
    two.start()
    assert first_entered.wait(timeout=2)
    time.sleep(0.05)
    assert not second_entered.is_set()
    release_first.set()
    one.join(timeout=2)
    two.join(timeout=2)
    assert second_entered.is_set()


def test_ocr_start_targets_local_launch_agent(monkeypatch) -> None:
    from legal_redactor import ocr

    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(ocr.subprocess, "run", run)

    ocr._start_local_ocr()

    assert calls == [
        [
            "/bin/launchctl",
            "kickstart",
            "-k",
            f"gui/{os.getuid()}/com.legal-redactor.unlimited-ocr",
        ]
    ]
    assert all("ssh" not in item for item in calls[0])


def test_clean_unlimited_ocr_decodes_bpe_bytes_to_chinese() -> None:
    assert clean_unlimited_ocr("ä¸Ńåįİäººæ°ĳåħ±åĴĮåĽ½") == "中华人民共和国"


def test_clean_unlimited_ocr_removes_detection_tokens() -> None:
    raw = (
        "<|det|>title [1,2,3,4]<|/det|><|ref|>裁判文书<|/ref|>\n"
        "Article 177\n"
        "<|det|>image [0,0,1,1]<|/det|>ignored"
    )

    assert clean_unlimited_ocr(raw) == "裁判文书\nArticle 177"


def test_ocr_curl_keeps_image_payload_out_of_process_arguments(monkeypatch) -> None:
    calls: list[dict] = []

    def run(command, *, input, capture_output, check, timeout):
        calls.append({"command": command, "input": input})
        return subprocess.CompletedProcess(command, 0, b'{"data":[]}', b"")

    monkeypatch.setattr("legal_redactor.ocr.subprocess.run", run)
    payload = {"image": "private-base64-document"}

    assert _curl_json("http://ocr.local/v1/test", payload, timeout=2) == {"data": []}
    assert json.loads(calls[0]["input"]) == payload
    assert "private-base64-document" not in " ".join(calls[0]["command"])
    assert "@-" in calls[0]["command"]


def test_extract_pdf_text_writes_ocr_copy(monkeypatch, tmp_path) -> None:
    from legal_redactor import ocr

    monkeypatch.setattr(ocr, "_OCR_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(ocr, "_OCR_OUTPUT_PATHS", {})
    monkeypatch.setattr(ocr, "pdf_page_texts", lambda *_: ([""], [1]))
    monkeypatch.setattr(ocr, "_recognize_pages", lambda *_: {1: "OCR 张三 Article 177"})

    text = extract_pdf_text(b"pdf", "判决书.pdf")
    saved = take_ocr_output_paths()

    assert text == "OCR 张三 Article 177"
    assert saved["判决书.pdf"].endswith("判决书.pdf.ocr.txt") or saved["判决书.pdf"].endswith(
        ".ocr.txt"
    )
    assert Path(saved["判决书.pdf"]).read_text(encoding="utf-8") == text
    assert persist_ocr_text("empty.pdf", "   ") is None
