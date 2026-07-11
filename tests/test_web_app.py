from __future__ import annotations

import os
import io
import json
import subprocess
import tempfile
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch

try:
    from legal_redactor.cases import create_or_update_manifest, load_manifest, write_last_restore_metadata
    from legal_redactor.io import redaction_map_to_json, save_redaction_map
    from legal_redactor.models import MappingEntry, RedactedDocument, RedactionMap, RedactionResult
    from legal_redactor.web_app import (
        _case_creation_command,
        _classify_mapping_review_row,
        _decode_text_bytes,
        _persist_optional_case_redaction,
        _read_input_documents,
        _read_restore_map_text,
        _read_upload_text,
        _render_case_workflow_panel,
        _page,
        _render_redaction_result,
        _render_status_panel,
        _renumber_mapping_placeholders,
        _restore_risk_reasons,
        _should_apply_auto_prefill,
        _suggest_manual_mapping_entry,
        _suggest_case_location_from_relative_paths,
        _safe_public_error_message,
        send_redacted_to_discord,
        attach_to_bound_discord_thread,
        app,
        create_discord_thread,
        health,
        index,
    )
    from legal_redactor.cases import suggest_case_location_from_filenames
except RuntimeError as exc:  # Web deps are optional for non-Web unit runs.
    _case_creation_command = None
    _classify_mapping_review_row = None
    _decode_text_bytes = None
    _persist_optional_case_redaction = None
    _read_input_documents = None
    _read_restore_map_text = None
    _read_upload_text = None
    _render_case_workflow_panel = None
    _page = None
    _render_redaction_result = None
    _render_status_panel = None
    _renumber_mapping_placeholders = None
    _restore_risk_reasons = None
    _should_apply_auto_prefill = None
    _suggest_manual_mapping_entry = None
    suggest_case_location_from_filenames = None
    _suggest_case_location_from_relative_paths = None
    send_redacted_to_discord = None
    attach_to_bound_discord_thread = None
    app = None
    create_discord_thread = None
    health = None
    _safe_public_error_message = None
    index = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class MockJsonRequest:
    def __init__(self, data: dict) -> None:
        self.data = data

    async def json(self) -> dict:
        return self.data


class MockUploadFile:
    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self.data = data

    async def read(self) -> bytes:
        return self.data


@unittest.skipIf(_decode_text_bytes is None, f"Web 依赖未安装：{_IMPORT_ERROR}")
class WebAppUploadTests(unittest.TestCase):
    def test_health_shape_stays_stable(self) -> None:
        self.assertEqual(health(), {"status": "ok", "bind_host": "127.0.0.1", "network": "offline"})

    def test_status_endpoint_returns_machine_readable_components(self) -> None:
        from fastapi.testclient import TestClient

        payload = {
            "status": "ok",
            "overall_state": "degraded",
            "expected_model": "mlx-community/Qwen3.5-9B-MLX-4bit",
            "components": [
                {
                    "id": "mlx_server",
                    "label": "MLX 本地模型",
                    "state": "skipped",
                    "message": "已跳过 MLX。",
                    "action": "取消 LEGAL_REDACTOR_SKIP_MLX=1",
                }
            ],
        }
        with patch("legal_redactor.web_app._status_payload", return_value=payload):
            response = TestClient(app).get("/api/status")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["components"][0]["id"], "mlx_server")

    def test_index_includes_status_panel_without_secret_values(self) -> None:
        payload = {
            "status": "ok",
            "overall_state": "degraded",
            "expected_model": "mlx-community/Qwen3.5-9B-MLX-4bit",
            "components": [
                {
                    "id": "office_api",
                    "label": "Office 还原 API",
                    "state": "ready",
                    "message": "还原 API 凭证存在。",
                    "action": "无需处理",
                    "details": {"api_token": "super-secret-token"},
                }
            ],
        }
        with (
            patch("legal_redactor.web_app._status_payload", return_value=payload),
            patch("legal_redactor._samples.load_all_samples", return_value=({}, set())),
        ):
            page = index()

        self.assertIn("系统状态", page)
        self.assertIn("Office 还原 API", page)
        self.assertIn('id="case-root-input"', page)
        self.assertIn("data-auto-value=", page)
        self.assertIn('id="source-directory-files"', page)
        self.assertIn('name="case_folder_files"', page)
        self.assertIn('id="upload-relative-paths-input"', page)
        self.assertIn('id="redact-form"', page)
        self.assertIn('id="redact-progress"', page)
        self.assertIn("已用时", page)
        self.assertNotIn("super-secret-token", page)

    def test_status_panel_renders_state_labels(self) -> None:
        html_text = _render_status_panel(
            {
                "components": [
                    {
                        "id": "recognition_mode",
                        "label": "识别模式",
                        "state": "degraded",
                        "message": "当前将退回规则识别。",
                        "action": "修复 MLX",
                    }
                ]
            }
        )

        self.assertIn("降级", html_text)
        self.assertIn("识别模式", html_text)

    def test_decode_upload_text_accepts_gb18030(self) -> None:
        text = "河北成城房地产开发有限公司与南村商贸公司。"
        self.assertEqual(text, _decode_text_bytes(text.encode("gb18030"), "sample.txt"))

    def test_decode_upload_text_accepts_utf8_sig(self) -> None:
        text = "张三与张四。"
        self.assertEqual(text, _decode_text_bytes(text.encode("utf-8-sig"), "sample.txt"))

    def test_restore_map_text_requires_json_or_file(self) -> None:
        with self.assertRaises(ValueError):
            import asyncio

            asyncio.run(_read_restore_map_text("", None))

    def test_restore_map_text_uses_pasted_json(self) -> None:
        import asyncio

        self.assertEqual("{}", asyncio.run(_read_restore_map_text("{}", None)))

    def test_read_upload_text_rejects_invalid_docx_cleanly(self) -> None:
        import asyncio

        with self.assertRaises(ValueError) as ctx:
            asyncio.run(_read_upload_text(MockUploadFile("bad.docx", b"not a zip file")))

        self.assertIn("不是有效的 .docx", str(ctx.exception))

    def test_read_upload_text_converts_legacy_doc_with_textutil(self) -> None:
        import asyncio

        completed = subprocess.CompletedProcess(
            args=["textutil"],
            returncode=0,
            stdout="张三与李四".encode("utf-8"),
            stderr=b"",
        )
        with patch("legal_redactor.web_app.subprocess.run", return_value=completed) as run:
            text = asyncio.run(_read_upload_text(MockUploadFile("legacy.doc", b"doc bytes")))

        self.assertEqual(text, "张三与李四")
        self.assertIn("-convert", run.call_args.args[0])
        self.assertIn("txt", run.call_args.args[0])


    def test_optional_case_redaction_persists_manifest_and_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            redaction_map = RedactionMap.create(
                [
                    MappingEntry(
                        type="person",
                        original="张三",
                        masked="【PERSON_001】",
                        role=None,
                        source="test",
                        confidence=1.0,
                        restore_by_default=True,
                    )
                ]
            )
            documents = [
                RedactedDocument(
                    source_file="judgment.txt",
                    original_text="张三",
                    redacted_text="【PERSON_001】",
                )
            ]

            _persist_optional_case_redaction(
                tmpdir,
                "2025 8765",
                "https://discord.com/channels/1/2/3",
                documents,
                redaction_map,
            )

            self.assertTrue(os.path.exists(os.path.join(tmpdir, "2025 8765", "manifest.json")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "2025 8765", "redacted", "redacted.txt")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "2025 8765", "mapping", "redaction_map.enc")))

    def test_optional_case_redaction_persists_local_case_without_thread(self) -> None:
        from legal_redactor.cases import load_manifest

        with tempfile.TemporaryDirectory() as tmpdir:
            redaction_map = RedactionMap.create([])
            documents = [
                RedactedDocument(
                    source_file="judgment.txt",
                    original_text="张三",
                    redacted_text="【PERSON_001】",
                )
            ]

            _persist_optional_case_redaction(
                tmpdir,
                "2025 8765",
                "",
                documents,
                redaction_map,
            )

            manifest = load_manifest(os.path.join(tmpdir, "2025 8765"))
            self.assertEqual(manifest.discord_thread_url, "")
            self.assertEqual(manifest.discord_thread_id, "")
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "2025 8765", "redacted", "redacted.txt")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "2025 8765", "mapping", "redaction_map.enc")))

    def test_optional_case_redaction_prefers_source_dir_over_configured_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            configured_root = os.path.join(tmpdir, "configured-root")
            source_case_dir = os.path.join(tmpdir, "uploaded-documents", "2025 8765")
            os.makedirs(source_case_dir)
            redaction_map = RedactionMap.create([])
            documents = [
                RedactedDocument(
                    source_file="judgment.txt",
                    original_text="张三",
                    redacted_text="【PERSON_001】",
                )
            ]

            _persist_optional_case_redaction(
                configured_root,
                "2025 8765",
                "https://discord.com/channels/1/2/3",
                documents,
                redaction_map,
                source_dir=source_case_dir,
            )

            self.assertTrue(os.path.exists(os.path.join(source_case_dir, "manifest.json")))
            self.assertTrue(os.path.exists(os.path.join(source_case_dir, "mapping", "redaction_map.enc")))
            self.assertFalse(os.path.exists(os.path.join(configured_root, "2025 8765", "manifest.json")))

    def test_optional_case_batch_redaction_uses_safe_output_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            redaction_map = RedactionMap.create(
                [
                    MappingEntry(
                        type="person",
                        original="张三",
                        masked="【PERSON_001】",
                        role=None,
                        source="test",
                        confidence=1.0,
                        restore_by_default=True,
                    )
                ]
            )
            documents = [
                RedactedDocument(source_file="2026 3624 张三.txt", original_text="张三", redacted_text="【PERSON_001】"),
                RedactedDocument(source_file="2026 3624 李四.txt", original_text="李四", redacted_text="李四"),
            ]

            _persist_optional_case_redaction(
                tmpdir,
                "2025 8765",
                "https://discord.com/channels/1/2/3",
                documents,
                redaction_map,
            )

            redacted_dir = os.path.join(tmpdir, "2025 8765", "redacted")
            self.assertTrue(os.path.exists(os.path.join(redacted_dir, "document-1.redacted.txt")))
            self.assertTrue(os.path.exists(os.path.join(redacted_dir, "document-2.redacted.txt")))
            self.assertFalse(os.path.exists(os.path.join(redacted_dir, "2026 3624 张三.redacted.txt")))

    def test_suggest_case_location_from_uploaded_filename(self) -> None:
        from pathlib import Path
        from legal_redactor.cases import create_or_update_manifest

        with tempfile.TemporaryDirectory() as tmpdir:
            case_dir = Path(tmpdir) / "2026 3624"
            case_dir.mkdir()
            source = case_dir / "judgment.docx"
            source.write_text("placeholder", encoding="utf-8")
            create_or_update_manifest(
                tmpdir,
                "2026 3624",
                "https://discord.com/channels/1/2/3",
            )

            result = suggest_case_location_from_filenames(["judgment.docx"], [Path(tmpdir)])

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["case_folder"], "2026 3624")
            self.assertEqual(result["case_root"], str(Path(tmpdir).resolve()))
            self.assertEqual(result["discord_thread_url"], "https://discord.com/channels/1/2/3")
            self.assertEqual(result["workflow_state"], "bound_thread")
            self.assertIn({"kind": "filename_match", "filename": "judgment.docx"}, result["evidence"])
            self.assertEqual(result["manifest"]["case_folder"], "2026 3624")

    def test_suggest_case_location_prefers_directory_with_most_batch_matches(self) -> None:
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_a = root / "2026 5987"
            case_b = root / "2026 1111"
            case_a.mkdir()
            case_b.mkdir()
            (case_a / "起诉状.doc").write_text("a", encoding="utf-8")
            (case_a / "证据目录.pdf").write_text("b", encoding="utf-8")
            (case_b / "起诉状.doc").write_text("c", encoding="utf-8")

            result = suggest_case_location_from_filenames(
                ["起诉状.doc", "证据目录.pdf"],
                [root],
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["case_folder"], "2026 5987")
            self.assertEqual(result["case_root"], str(root.resolve()))

    def test_suggest_case_location_api_rejects_forged_state(self) -> None:
        from fastapi.testclient import TestClient

        response = TestClient(app).post(
            "/api/suggest-case-location",
            json={"filenames": ["a.docx"], "state": "sent_discord"},
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["code"], "INVALID_INPUT")
        self.assertEqual(data["fields"], ["state"])

    def test_suggest_case_location_api_returns_ok_shape(self) -> None:
        from pathlib import Path
        from fastapi.testclient import TestClient
        from legal_redactor.cases import create_or_update_manifest

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_path = root / "2026 3624"
            case_path.mkdir()
            (case_path / "judgment.docx").write_text("placeholder", encoding="utf-8")
            create_or_update_manifest(root, "2026 3624", "https://discord.com/channels/1/2/3")

            response = TestClient(app).post(
                "/api/suggest-case-location",
                json={"filenames": ["judgment.docx"], "case_root": tmpdir},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["case_folder"], "2026 3624")
        self.assertEqual(data["workflow_state"], "bound_thread")
        self.assertEqual(data["manifest"]["case_folder"], "2026 3624")

    def test_suggest_case_location_api_does_not_scope_to_default_root_value(self) -> None:
        from pathlib import Path
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as default_root, tempfile.TemporaryDirectory() as search_root:
            root = Path(search_root)
            case_path = root / "2026 7777"
            case_path.mkdir()
            (case_path / "judgment.docx").write_text("placeholder", encoding="utf-8")

            with (
                patch.dict(os.environ, {"LEGAL_REDACTOR_CASE_ROOT": default_root}),
                patch("legal_redactor.cases.case_location_search_roots", return_value=[root]),
            ):
                response = TestClient(app).post(
                    "/api/suggest-case-location",
                    json={"filenames": ["judgment.docx"], "case_root": default_root},
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["case_folder"], "2026 7777")
        self.assertEqual(data["case_root"], str(root.resolve()))

    def test_suggest_case_location_api_keeps_manual_root_scope(self) -> None:
        from pathlib import Path
        from fastapi.testclient import TestClient

        with (
            tempfile.TemporaryDirectory() as default_root,
            tempfile.TemporaryDirectory() as manual_root,
            tempfile.TemporaryDirectory() as search_root,
        ):
            root = Path(search_root)
            case_path = root / "2026 7777"
            case_path.mkdir()
            (case_path / "judgment.docx").write_text("placeholder", encoding="utf-8")

            with (
                patch.dict(os.environ, {"LEGAL_REDACTOR_CASE_ROOT": default_root}),
                patch("legal_redactor.cases.case_location_search_roots", return_value=[root]),
            ):
                response = TestClient(app).post(
                    "/api/suggest-case-location",
                    json={"filenames": ["judgment.docx"], "case_root": manual_root},
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "not_found")
        self.assertEqual(data["workflow_state"], "not_saved")

    def test_suggest_case_location_from_relative_paths_uses_folder_name(self) -> None:
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_path = root / "2026 8888"
            case_path.mkdir()

            result = _suggest_case_location_from_relative_paths(
                ["2026 8888/judgment.docx", "2026 8888/evidence/证据目录.pdf"],
                [root],
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["case_folder"], "2026 8888")
        self.assertEqual(result["case_root"], str(root.resolve()))
        self.assertEqual(result["matched_dir"], str(case_path.resolve()))
        self.assertIn({"kind": "upload_relative_path", "case_folder": "2026 8888"}, result["evidence"])

    def test_suggest_case_location_api_prefers_relative_folder_over_same_filename(self) -> None:
        from pathlib import Path
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            old_case = root / "2026 1111"
            selected_case = root / "2026 8888"
            old_case.mkdir()
            selected_case.mkdir()
            (old_case / "judgment.docx").write_text("old", encoding="utf-8")

            response = TestClient(app).post(
                "/api/suggest-case-location",
                json={
                    "filenames": ["judgment.docx"],
                    "relative_paths": ["2026 8888/judgment.docx"],
                    "case_root": tmpdir,
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["case_folder"], "2026 8888")
        self.assertEqual(data["case_root"], str(root.resolve()))

    def test_read_input_documents_skips_unsupported_case_folder_files(self) -> None:
        import asyncio

        docs = asyncio.run(
            _read_input_documents(
                "",
                None,
                [],
                [
                    MockUploadFile("2026 8888/judgment.txt", "张三".encode("utf-8")),
                    MockUploadFile("2026 8888/photo.jpg", b"not text"),
                    MockUploadFile("2026 8888/._judgment.txt", b"appledouble"),
                ],
            )
        )

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].source_file, "2026 8888/judgment.txt")
        self.assertEqual(docs[0].text, "张三")

    def test_suggest_case_location_api_returns_ambiguous_shape(self) -> None:
        from pathlib import Path
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "2026 1001").mkdir()
            (root / "2026 1002").mkdir()
            (root / "2026 1001" / "judgment.docx").write_text("a", encoding="utf-8")
            (root / "2026 1002" / "judgment.docx").write_text("b", encoding="utf-8")

            response = TestClient(app).post(
                "/api/suggest-case-location",
                json={"filenames": ["judgment.docx"], "case_root": tmpdir},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ambiguous")
        self.assertEqual(data["workflow_state"], "not_saved")
        self.assertEqual(len(data["candidates"]), 2)
        self.assertEqual(data["evidence"][0]["kind"], "ambiguous_case_directory")

    def test_suggest_case_location_api_returns_not_found_shape(self) -> None:
        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as tmpdir:
            response = TestClient(app).post(
                "/api/suggest-case-location",
                json={"filenames": ["missing.docx"], "case_root": tmpdir},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "not_found")
        self.assertEqual(data["workflow_state"], "not_saved")
        self.assertEqual(data["evidence"], [])

    def test_suggest_case_location_api_returns_conflict_shape(self) -> None:
        from pathlib import Path
        from fastapi.testclient import TestClient
        from legal_redactor.cases import create_or_update_manifest

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            case_path = root / "2026 3624"
            case_path.mkdir()
            (case_path / "judgment.docx").write_text("placeholder", encoding="utf-8")
            create_or_update_manifest(root, "2026 3624", "https://discord.com/channels/1/2/3")

            response = TestClient(app).post(
                "/api/suggest-case-location",
                json={
                    "filenames": ["judgment.docx"],
                    "case_root": tmpdir,
                    "discord_thread_url": "https://discord.com/channels/1/2/4",
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "conflict")
        self.assertTrue(data["conflict"])
        self.assertEqual(data["conflict_code"], "thread_mismatch")

    def test_redact_form_rejects_forged_workflow_state(self) -> None:
        from fastapi.testclient import TestClient

        response = TestClient(app).post(
            "/redact",
            data={"text": "张三", "status": "success"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("INVALID_INPUT", response.text)
        self.assertIn("status", response.text)

    def test_redact_failure_hint_does_not_blame_hanlp_when_disabled(self) -> None:
        from fastapi.testclient import TestClient

        class FakePipeline:
            def __init__(self, config) -> None:
                self.config = config

            def redact(self, text, source_file=None, base_redaction_map=None):
                raise RuntimeError("simulated failure")

        with (
            patch("legal_redactor.web_app.ensure_mlx_server_ready", return_value=SimpleNamespace(state="ready")),
            patch("legal_redactor.web_app.RedactionPipeline", FakePipeline),
        ):
            response = TestClient(app).post("/redact", data={"text": "张三"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("当前未启用 HanLP", response.text)
        self.assertNotIn("取消勾选 HanLP", response.text)

    def test_analyze_page_uses_pipeline_analyze(self) -> None:
        from fastapi.testclient import TestClient

        class FakePipeline:
            def __init__(self, config) -> None:
                self.config = config

            def analyze(self, text):
                return {
                    "entity_groups": [
                        {
                            "id": 1,
                            "type": "person",
                            "role": "原告",
                            "full_name": "张三",
                            "aliases": [],
                        }
                    ],
                    "locations": [],
                }

        with (
            patch("legal_redactor.web_app.ensure_mlx_server_ready", return_value=SimpleNamespace(state="ready")),
            patch("legal_redactor.web_app.RedactionPipeline", FakePipeline),
        ):
            response = TestClient(app).post("/analyze", data={"text": "张三"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("分级确认", response.text)
        self.assertIn("张三", response.text)

    def test_apply_edited_map_rejects_forged_workflow_state(self) -> None:
        from fastapi.testclient import TestClient

        response = TestClient(app).post(
            "/redact/apply-edited-map",
            data={"status": "success"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("INVALID_INPUT", response.text)
        self.assertIn("status", response.text)

    def test_redact_route_can_save_local_case_without_thread(self) -> None:
        from fastapi.testclient import TestClient
        from legal_redactor.cases import load_manifest

        class FakePipeline:
            def __init__(self, config) -> None:
                self.config = config

            def redact(self, text, source_file=None, base_redaction_map=None):
                return RedactionResult(
                    original_text=text,
                    redacted_text="【PERSON_001】",
                    redaction_map=RedactionMap.create([]),
                    candidates=[],
                    review_candidates=[],
                    leaks=[],
                    mode="test",
                    warnings=[],
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("legal_redactor.web_app.RedactionPipeline", FakePipeline):
                response = TestClient(app).post(
                    "/redact",
                    data={
                        "text": "张三",
                        "case_root": tmpdir,
                        "case_folder": "2026 3624",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertIn('data-workflow-state="saved_local"', response.text)
            manifest = load_manifest(os.path.join(tmpdir, "2026 3624"))
            self.assertEqual(manifest.discord_thread_url, "")
            self.assertEqual(manifest.discord_thread_id, "")

    def test_redact_route_falls_back_to_offline_rules_when_mlx_unavailable_and_saves_case(self) -> None:
        from pathlib import Path
        from fastapi.testclient import TestClient
        from legal_redactor.config import PipelineConfig
        from legal_redactor.cases import load_manifest

        configs = []

        class FakePipeline:
            def __init__(self, config) -> None:
                self.config = config
                configs.append(config)

            def redact(self, text, source_file=None, base_redaction_map=None):
                assert text == "原告张三。"
                assert base_redaction_map is None
                assert self.config.enable_local_llm is False
                return RedactionResult(
                    original_text=text,
                    redacted_text="原告张某1。",
                    redaction_map=RedactionMap.create(
                        [
                            MappingEntry(
                                type="person",
                                original="张三",
                                masked="张某1",
                                role=None,
                                source="test",
                                confidence=1.0,
                                restore_by_default=True,
                            )
                        ]
                    ),
                    candidates=[],
                    review_candidates=[],
                    leaks=[],
                    mode="test",
                    warnings=[],
                )

        unavailable = SimpleNamespace(state="error", message="mlx missing", action="start mlx")
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch("legal_redactor.web_app.ensure_mlx_server_ready", return_value=unavailable),
                patch("legal_redactor.web_app.PipelineConfig.from_llm_mode", side_effect=lambda *args, **kwargs: PipelineConfig.max_effect(*args[1:], **kwargs)),
                patch("legal_redactor.web_app.RedactionPipeline", FakePipeline),
            ):
                response = TestClient(app).post(
                    "/redact",
                    data={
                        "text": "原告张三。",
                        "case_root": tmpdir,
                        "case_folder": "2026 3624",
                    },
                )

            self.assertEqual(response.status_code, 200)
            self.assertIn("原告张某1。", response.text)
            self.assertEqual(len(configs), 1)
            self.assertFalse(configs[0].enable_local_llm)
            manifest = load_manifest(Path(tmpdir) / "2026 3624")
            self.assertEqual(manifest.case_folder, "2026 3624")
            self.assertTrue((Path(tmpdir) / "2026 3624" / "redacted" / "redacted.txt").exists())
            self.assertTrue((Path(tmpdir) / "2026 3624" / "mapping" / "redaction_map.enc").exists())

    def test_redact_confirmed_falls_back_to_offline_rules_when_mlx_unavailable(self) -> None:
        from fastapi.testclient import TestClient
        from legal_redactor.config import PipelineConfig

        configs = []

        class FakePipeline:
            def __init__(self, config) -> None:
                self.config = config
                configs.append(config)

            def apply_redaction_map(self, text, redaction_map):
                return text.replace("张三", "张某1")

            def scan_high_risk_leaks(self, text):
                return []

            def analyze(self, text):
                assert self.config.enable_local_llm is False
                return {"entity_groups": [], "locations": [], "warnings": []}

        unavailable = SimpleNamespace(state="error", message="mlx missing", action="start mlx")
        bundle = json.dumps([{"source_file": "a.txt", "text": "原告张三。"}], ensure_ascii=False)
        analysis = json.dumps(
            {
                "entity_groups": [
                    {
                        "id": "g1",
                        "type": "person",
                        "full_name": "张三",
                        "aliases": [],
                        "role": "原告",
                    }
                ],
                "locations": [],
            },
            ensure_ascii=False,
        )
        with (
            patch("legal_redactor.web_app.ensure_mlx_server_ready", return_value=unavailable),
            patch(
                "legal_redactor.web_app.PipelineConfig.from_llm_mode",
                side_effect=lambda *args, **kwargs: PipelineConfig.max_effect(*args[1:], **kwargs),
            ),
            patch("legal_redactor.web_app.RedactionPipeline", FakePipeline),
        ):
            response = TestClient(app).post(
                "/redact/confirmed",
                data={
                    "bundle_json": bundle,
                    "analysis_json": analysis,
                    "group_g1_enabled": "1",
                    "round": "0",
                    "action": "continue",
                    "previous_map_json": "{}",
                    "previous_deselected_json": "[]",
                },
            )

        self.assertEqual(response.status_code, 200)
        # first offline apply pipeline + second offline analyze pipeline
        self.assertGreaterEqual(len(configs), 2)
        self.assertTrue(all(cfg.enable_local_llm is False for cfg in configs))

    def test_clear_samples_api_returns_delete_stats_and_rebuilds_auto_file(self) -> None:
        from pathlib import Path
        from fastapi.testclient import TestClient
        from legal_redactor._samples import AUTO_SAMPLE_FILE, save_sample_auto

        with tempfile.TemporaryDirectory() as tmpdir:
            samples_dir = Path(tmpdir)
            save_sample_auto(
                [{"action": "add", "type": "manual", "original": "胖哥公司", "masked": "乙公司"}],
                source="web-test",
                samples_dir=samples_dir,
            )
            with patch("legal_redactor._samples.DEFAULT_SAMPLES_DIR", samples_dir):
                response = TestClient(app).post("/api/samples/clear")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "ok")
            self.assertGreaterEqual(payload["removed_entries"], 1)
            self.assertGreaterEqual(payload["removed_files"], 1)
            self.assertEqual(payload["sample_file"], AUTO_SAMPLE_FILE)
            auto_path = samples_dir / AUTO_SAMPLE_FILE
            self.assertTrue(auto_path.exists())
            data = json.loads(auto_path.read_text(encoding="utf-8"))
            self.assertEqual(data["entries"], [])
            self.assertEqual(data["total"], 0)

    def test_legacy_cli_redact_writes_encrypted_map_file(self) -> None:
        from pathlib import Path
        from legal_redactor import cli

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "judgment.txt"
            output_dir = root / "out"
            input_path.write_text("原告张三。", encoding="utf-8")
            encrypted_map_calls = []

            def fake_redact(self, text, source_file=None):
                return RedactionResult(
                    original_text=text,
                    redacted_text="原告张某1。",
                    redaction_map=RedactionMap.create(
                        [MappingEntry("person", "张三", "张某1", None, "test", 1.0, True)]
                    ),
                    candidates=[],
                    review_candidates=[],
                    leaks=[],
                    mode="test",
                    warnings=[],
                )

            with (
                patch("legal_redactor.cli.RedactionPipeline.redact", fake_redact),
                patch("legal_redactor.cli.save_redaction_map_auto", side_effect=lambda path, redaction_map: encrypted_map_calls.append(Path(path))),
            ):
                exit_code = cli.main(["redact", str(input_path), "--out", str(output_dir), "--no-llm"])

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_dir / "judgment.redacted.txt").exists())
            self.assertEqual(encrypted_map_calls, [output_dir / "redaction_map.enc"])
            self.assertFalse((output_dir / "redaction_map.json").exists())

    def test_redact_route_directory_upload_prefers_inferred_root_over_default_root(self) -> None:
        from pathlib import Path
        from fastapi.testclient import TestClient
        from legal_redactor.cases import load_manifest

        class FakePipeline:
            def __init__(self, config) -> None:
                self.config = config

            def redact(self, text, source_file=None, base_redaction_map=None):
                return RedactionResult(
                    original_text=text,
                    redacted_text="【PERSON_001】",
                    redaction_map=RedactionMap.create([]),
                    candidates=[],
                    review_candidates=[],
                    leaks=[],
                    mode="test",
                    warnings=[],
                )

        with tempfile.TemporaryDirectory() as default_root, tempfile.TemporaryDirectory() as actual_root:
            actual = Path(actual_root)
            (actual / "2026 8888").mkdir()
            with (
                patch.dict(os.environ, {"LEGAL_REDACTOR_CASE_ROOT": default_root}),
                patch("legal_redactor.web_app.case_location_search_roots", return_value=[actual]),
                patch("legal_redactor.web_app.RedactionPipeline", FakePipeline),
            ):
                response = TestClient(app).post(
                    "/redact",
                    data={
                        "case_root": default_root,
                        "upload_relative_paths": json.dumps(["2026 8888/judgment.txt"], ensure_ascii=False),
                    },
                    files=[
                        (
                            "case_folder_files",
                            ("2026 8888/judgment.txt", "张三".encode("utf-8"), "text/plain"),
                        )
                    ],
                )

            self.assertEqual(response.status_code, 200)
            self.assertIn('data-workflow-state="saved_local"', response.text)
            manifest = load_manifest(actual / "2026 8888")
            self.assertEqual(manifest.case_folder, "2026 8888")
            self.assertFalse((Path(default_root) / "2026 8888").exists())

    def test_suggest_manual_person_mapping_continues_same_surname_counter(self) -> None:
        existing = [
            MappingEntry(
                type="person",
                original="张三",
                masked="张某甲",
                role=None,
                source="test",
                confidence=1.0,
                restore_by_default=True,
            )
        ]

        entry = _suggest_manual_mapping_entry("张四", "person", existing)

        self.assertEqual(entry.type, "person")
        self.assertEqual(entry.original, "张四")
        self.assertEqual(entry.masked, "张某乙")
        self.assertEqual(entry.source, "manual_selection")

    def test_suggest_manual_org_and_location_mapping(self) -> None:
        existing = [
            MappingEntry(
                type="organization",
                original="甲公司原名",
                masked="甲公司",
                role=None,
                source="test",
                confidence=1.0,
                restore_by_default=True,
            ),
            MappingEntry(
                type="location",
                original="石家庄市",
                masked="甲市",
                role=None,
                source="test",
                confidence=1.0,
                restore_by_default=True,
            ),
        ]

        org = _suggest_manual_mapping_entry("河北成城房地产开发有限公司", "organization", existing)
        loc = _suggest_manual_mapping_entry("裕华区", "location", existing)

        self.assertEqual(org.masked, "乙公司")
        self.assertEqual(loc.masked, "乙区")

    def test_renumber_mapping_placeholders_compacts_current_rows(self) -> None:
        entries = [
            MappingEntry(
                type="organization",
                original="河北成城房地产开发有限公司",
                masked="丁公司",
                role=None,
                source="rule",
                confidence=1.0,
                restore_by_default=True,
            ),
            MappingEntry(
                type="organization",
                original="明显误识别机构",
                masked="14机构",
                role=None,
                source="manual",
                confidence=1.0,
                restore_by_default=True,
            ),
            MappingEntry(
                type="person",
                original="张三",
                masked="张某丁",
                role=None,
                source="rule",
                confidence=1.0,
                restore_by_default=True,
            ),
        ]

        renumbered = _renumber_mapping_placeholders(entries)

        self.assertEqual([entry.masked for entry in renumbered], ["甲公司", "乙机构", "张某甲"])

    def test_renumber_mapping_placeholders_keeps_distinct_companies_separate(self) -> None:
        entries = [
            MappingEntry(
                type="organization",
                original="安徽拓欧建设集团有限公司",
                masked="丁省丁公司",
                role=None,
                source="rule",
                confidence=1.0,
                restore_by_default=True,
            ),
            MappingEntry(
                type="organization",
                original="河北成城房地产开发有限公司",
                masked="丁公司",
                role=None,
                source="rule",
                confidence=1.0,
                restore_by_default=True,
            ),
        ]

        renumbered = _renumber_mapping_placeholders(entries)

        self.assertEqual([entry.masked for entry in renumbered], ["甲省丁公司", "乙公司"])

    def test_renumber_mapping_placeholders_keeps_aliases_in_same_group(self) -> None:
        entries = [
            MappingEntry(
                type="organization",
                original="拓欧",
                masked="丁",
                role=None,
                source="rule",
                confidence=1.0,
                restore_by_default=True,
            ),
            MappingEntry(
                type="organization",
                original="拓欧公司",
                masked="丁公司",
                role=None,
                source="rule",
                confidence=1.0,
                restore_by_default=True,
            ),
            MappingEntry(
                type="location",
                original="裕华区",
                masked="8区",
                role=None,
                source="rule",
                confidence=1.0,
                restore_by_default=True,
            ),
        ]

        renumbered = _renumber_mapping_placeholders(entries)

        self.assertEqual([entry.masked for entry in renumbered], ["甲", "甲公司", "甲区"])

    def test_apply_edited_map_can_renumber_placeholders(self) -> None:
        from fastapi.testclient import TestClient

        response = TestClient(app).post(
            "/redact/apply-edited-map",
            data={
                "original_text": "河北成城房地产开发有限公司与张三签订合同。",
                "map_version": "1.0",
                "map_created_at": "2026-06-30T10:00:00+08:00",
                "map_mode": "normal",
                "map_source_file": "",
                "map_type": ["organization", "person"],
                "map_original": ["河北成城房地产开发有限公司", "张三"],
                "map_masked": ["丁公司", "张某丁"],
                "map_role": ["", ""],
                "map_source": ["rule", "rule"],
                "map_confidence": ["1.0", "1.0"],
                "map_reason": ["", ""],
                "map_restore_by_default": ["1", "1"],
                "remap_placeholders": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("甲公司与张某甲签订合同", response.text)
        self.assertIn("已按当前保留的映射重新排列占位符", response.text)
        self.assertNotIn("丁公司与张某丁签订合同", response.text)

    def test_case_creation_command_formats_case_folder_for_hermes(self) -> None:
        command = _case_creation_command("2026 5987 劳动争议纠纷", "lr_test")

        self.assertEqual(
            command,
            "新建案件，（2026）5987 劳动争议纠纷\n请求ID：lr_test\n案件目录：2026 5987 劳动争议纠纷",
        )

    def test_case_creation_command_uses_manual_case_cause(self) -> None:
        command = _case_creation_command("2026 5987", "lr_test", "劳动争议纠纷")

        self.assertEqual(
            command,
            "新建案件，（2026）5987 劳动争议纠纷\n请求ID：lr_test\n案件目录：2026 5987",
        )

    def test_case_creation_command_does_not_leak_local_paths(self) -> None:
        command = _case_creation_command(
            "2026 5987",
            "lr_test",
            "劳动争议纠纷",
            case_root="/Users/jannerchang/Documents/legal-redactor-cases",
            source_dir="/Volumes/案件资料/2026 5987",
        )

        self.assertNotIn("case_root", command)
        self.assertNotIn("source_dir", command)
        self.assertNotIn("/Users/", command)
        self.assertNotIn("/Volumes/", command)
        self.assertEqual(
            command,
            "新建案件，（2026）5987 劳动争议纠纷\n请求ID：lr_test\n案件目录：2026 5987",
        )

    def test_create_discord_thread_posts_hermes_command(self) -> None:
        import asyncio

        calls = []

        def fake_post(channel_id: str, content: str) -> dict[str, str]:
            calls.append((channel_id, content))
            return {"message_id": "m1", "channel_id": channel_id}

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("legal_redactor.web_app._discord_command_channel_id", return_value="1501248343823880345"):
                with patch("legal_redactor.web_app._post_discord_channel_message", side_effect=fake_post):
                    response = asyncio.run(
                        create_discord_thread(
                            MockJsonRequest(
                                {
                                    "case_root": tmpdir,
                                    "case_folder": "2026 5987",
                                    "case_cause": "劳动争议纠纷",
                                    "request_id": "lr_test",
                                }
                            )
                        )
                    )
            manifest = load_manifest(os.path.join(tmpdir, "2026 5987"))

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["workflow_state"], "waiting_hermes")
        self.assertEqual(data["request_id"], "lr_test")
        self.assertEqual(manifest.hermes_request_id, "lr_test")
        self.assertEqual(manifest.hermes_command_message_id, "m1")
        self.assertEqual(calls, [("1501248343823880345", _case_creation_command("2026 5987", "lr_test", "劳动争议纠纷"))])

    def test_create_discord_thread_reuses_pending_hermes_request(self) -> None:
        import asyncio

        calls = []

        def fake_post(channel_id: str, content: str) -> dict[str, str]:
            calls.append((channel_id, content))
            return {"message_id": "m1", "channel_id": channel_id}

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("legal_redactor.web_app._discord_command_channel_id", return_value="1501248343823880345"):
                with patch("legal_redactor.web_app._post_discord_channel_message", side_effect=fake_post):
                    first = asyncio.run(
                        create_discord_thread(
                            MockJsonRequest(
                                {
                                    "case_root": tmpdir,
                                    "case_folder": "2026 5987",
                                    "case_cause": "劳动争议纠纷",
                                    "request_id": "lr_test",
                                }
                            )
                        )
                    )
                    second = asyncio.run(
                        create_discord_thread(
                            MockJsonRequest(
                                {
                                    "case_root": tmpdir,
                                    "case_folder": "2026 5987",
                                    "case_cause": "劳动争议纠纷",
                                    "request_id": "lr_second",
                                }
                            )
                        )
                    )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        data = json.loads(second.body.decode("utf-8"))
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["workflow_state"], "waiting_hermes")
        self.assertEqual(data["request_id"], "lr_test")
        self.assertEqual(data["command_message_id"], "m1")
        self.assertEqual(len(calls), 1)

    def test_create_discord_thread_rejects_forged_state(self) -> None:
        import asyncio

        response = asyncio.run(
            create_discord_thread(
                MockJsonRequest(
                    {
                        "case_folder": "2026 5987",
                        "status": "success",
                    }
                )
            )
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(data["code"], "INVALID_INPUT")
        self.assertEqual(data["fields"], ["status"])

    def test_discord_create_thread_error_does_not_relay_http_body(self) -> None:
        import asyncio

        def fail(*args, **kwargs):
            raise urllib.error.HTTPError(
                "https://discord.com/api/v10/channels/1/messages",
                403,
                "Forbidden",
                {},
                io.BytesIO(b'{"message":"/Users/jannerchang/private secret-token-value"}'),
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"LEGAL_REDACTOR_DISCORD_BOT_TOKEN": "bot-token"}):
                with patch("legal_redactor.web_app._discord_command_channel_id", return_value="1"):
                    with patch("legal_redactor.web_app.urllib.request.urlopen", side_effect=fail):
                        response = asyncio.run(
                            create_discord_thread(
                                MockJsonRequest(
                                    {
                                        "case_root": tmpdir,
                                        "case_folder": "2026 5987",
                                        "case_cause": "劳动争议纠纷",
                                    }
                                )
                            )
                        )

        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(data["code"], "discord_api_error")
        self.assertNotIn("/Users", data["message"])
        self.assertNotIn("secret-token-value", data["message"])

    def test_send_redacted_to_discord_uses_custom_message(self) -> None:
        import asyncio

        calls = []

        def fake_post(thread_id: str, filename: str, content: str, message: str = "") -> dict[str, str]:
            calls.append((thread_id, filename, content, message))
            return {"message_id": "m2", "channel_id": thread_id}

        with patch("legal_redactor.web_app._post_discord_thread_file", side_effect=fake_post):
            response = asyncio.run(
                send_redacted_to_discord(
                    MockJsonRequest(
                        {
                            "discord_thread_url": "https://discord.com/channels/1/2/3",
                            "filename": "redacted.txt",
                            "content": "脱敏内容",
                            "message": "请按我填写的附言发送。",
                        }
                    )
                )
            )

        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["status"], "success")
        self.assertEqual(calls, [("3", "redacted.txt", "脱敏内容", "请按我填写的附言发送。")])

    def test_public_error_message_scrubs_cross_platform_paths(self) -> None:
        cases = {
            "/Users/alice/private/case.docx": ["alice", "case.docx"],
            "/tmp/legal-redactor/secret/map.enc": ["legal-redactor", "map.enc"],
            r"C:\Users\alice\private\case.docx": ["alice", "case.docx"],
            r"\\server\share\private\case.docx": ["server", "share", "case.docx"],
        }

        for path, forbidden_parts in cases.items():
            message = _safe_public_error_message(f"案件保存失败：{path} permission denied")
            self.assertIn("<local-path>", message)
            for part in forbidden_parts:
                self.assertNotIn(part, message)

        legal_text = "合同编号 A\\B-001 无法解析"
        self.assertEqual(_safe_public_error_message(legal_text), legal_text)

    def test_send_redacted_to_discord_falls_back_when_message_contains_path(self) -> None:
        import asyncio

        calls = []

        def fake_post(thread_id: str, filename: str, content: str, message: str = "") -> dict[str, str]:
            calls.append((thread_id, filename, content, message))
            return {"message_id": "m2", "channel_id": thread_id}

        with patch("legal_redactor.web_app._post_discord_thread_file", side_effect=fake_post):
            response = asyncio.run(
                send_redacted_to_discord(
                    MockJsonRequest(
                        {
                            "discord_thread_url": "https://discord.com/channels/1/2/3",
                            "filename": "redacted.txt",
                            "content": "脱敏内容",
                            "message": "请看 /Users/jannerchang/private/case.docx",
                        }
                    )
                )
            )

        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["status"], "success")
        self.assertEqual(calls, [("3", "redacted.txt", "脱敏内容", "脱敏文件已生成，请见附件：redacted.txt")])

    def test_attach_bound_discord_thread_waits_for_manifest(self) -> None:
        import asyncio

        with tempfile.TemporaryDirectory() as tmpdir:
            response = asyncio.run(
                attach_to_bound_discord_thread(
                    MockJsonRequest(
                        {
                            "case_root": tmpdir,
                            "case_folder": "2026 5987 劳动争议纠纷",
                            "filename": "redacted.txt",
                            "content": "脱敏内容",
                            "map_json": redaction_map_to_json(RedactionMap.create([])),
                        }
                    )
                )
            )

        self.assertEqual(response.status_code, 202)
        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["workflow_state"], "waiting_hermes")

    def test_attach_bound_discord_thread_sends_file_and_persists(self) -> None:
        import asyncio
        from legal_redactor.cases import create_or_update_manifest

        calls = []
        redaction_map = RedactionMap.create(
            [
                MappingEntry(
                    type="person",
                    original="张三",
                    masked="【PERSON_001】",
                    role=None,
                    source="test",
                    confidence=1.0,
                    restore_by_default=True,
                )
            ]
        )

        def fake_post(thread_id: str, filename: str, content: str, message: str = "") -> dict[str, str]:
            calls.append((thread_id, filename, content, message))
            return {"message_id": "m2", "channel_id": thread_id}

        with tempfile.TemporaryDirectory() as tmpdir:
            create_or_update_manifest(
                tmpdir,
                "2026 5987 劳动争议纠纷",
                "https://discord.com/channels/1/2/3",
                source_dir="/cases/2026 5987 劳动争议纠纷",
            )
            with patch("legal_redactor.web_app._post_discord_thread_file", side_effect=fake_post):
                response = asyncio.run(
                    attach_to_bound_discord_thread(
                        MockJsonRequest(
                            {
                                "case_root": tmpdir,
                                "case_folder": "2026 5987 劳动争议纠纷",
                                "source_dir": "/cases/2026 5987 劳动争议纠纷",
                                "filename": "redacted.txt",
                                "content": "【PERSON_001】",
                                "message": "请见附件",
                                "map_json": redaction_map_to_json(redaction_map),
                            }
                        )
                    )
                )

            data = json.loads(response.body.decode("utf-8"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["workflow_state"], "sent_discord")
            self.assertEqual(data["thread_url"], "https://discord.com/channels/1/2/3")
            self.assertEqual(calls, [("3", "redacted.txt", "【PERSON_001】", "请见附件")])
            self.assertNotIn("/cases/", calls[0][3])
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "2026 5987 劳动争议纠纷", "redacted", "redacted.txt")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "2026 5987 劳动争议纠纷", "mapping", "redaction_map.enc")))

    def test_discord_thread_file_error_does_not_relay_http_body(self) -> None:
        import asyncio

        def fail(*args, **kwargs):
            raise urllib.error.HTTPError(
                "https://discord.com/api/v10/channels/3/messages",
                500,
                "Server Error",
                {},
                io.BytesIO(b'{"message":"/Volumes/cases secret-token-value"}'),
            )

        with patch.dict(os.environ, {"LEGAL_REDACTOR_DISCORD_BOT_TOKEN": "bot-token"}):
            with patch("legal_redactor.web_app.urllib.request.urlopen", side_effect=fail):
                response = asyncio.run(
                    send_redacted_to_discord(
                        MockJsonRequest(
                            {
                                "discord_thread_url": "https://discord.com/channels/1/2/3",
                                "filename": "redacted.txt",
                                "content": "脱敏内容",
                            }
                        )
                    )
                )

        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(data["code"], "discord_api_error")
        self.assertNotIn("/Volumes", data["message"])
        self.assertNotIn("secret-token-value", data["message"])

    def test_attach_bound_discord_thread_rejects_forged_state(self) -> None:
        import asyncio

        with tempfile.TemporaryDirectory() as tmpdir:
            response = asyncio.run(
                attach_to_bound_discord_thread(
                    MockJsonRequest(
                        {
                            "case_root": tmpdir,
                            "case_folder": "2026 5987 劳动争议纠纷",
                            "filename": "redacted.txt",
                            "content": "脱敏内容",
                            "map_json": redaction_map_to_json(RedactionMap.create([])),
                            "sent": True,
                        }
                    )
                )
            )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(data["code"], "INVALID_INPUT")
        self.assertEqual(data["fields"], ["sent"])

    def test_redaction_result_preserves_save_dir_in_edit_form(self) -> None:
        redaction_map = RedactionMap.create(
            [
                MappingEntry(
                    type="person",
                    original="张三",
                    masked="【PERSON_001】",
                    role=None,
                    source="test",
                    confidence=1.0,
                    restore_by_default=True,
                )
            ]
        )

        html = _render_redaction_result(
            "脱敏结果",
            "张三",
            "【PERSON_001】",
            redaction_map,
            [],
            [],
            [],
            save_dir="/tmp/case",
            discord_thread_url="https://discord.com/channels/1/2/3",
        )

        self.assertIn('name="save_dir" value="/tmp/case"', html)
        self.assertIn('name="discord_thread_url" value="https://discord.com/channels/1/2/3"', html)
        self.assertIn('data-workflow-state="bound_thread"', html)
        self.assertIn("案件流程状态", html)

    def test_redaction_result_waits_long_enough_for_slow_hermes_thread_creation(self) -> None:
        redaction_map = RedactionMap.create(
            [
                MappingEntry(
                    type="person",
                    original="张三",
                    masked="【PERSON_001】",
                    role=None,
                    source="test",
                    confidence=1.0,
                    restore_by_default=True,
                )
            ]
        )

        page_html = _render_redaction_result(
            "脱敏结果",
            "张三",
            "【PERSON_001】",
            redaction_map,
            [],
            [],
            [],
            case_root="/Volumes/SANDISK/案件资料",
            case_folder="2026 4343",
            source_dir="/Volumes/SANDISK/案件资料/2026 4343",
        )

        self.assertIn("var maxAttempts = 200;", page_html)
        self.assertIn("await discordWait(3000);", page_html)

    def test_redaction_result_renders_m5_mapping_filters_and_summary_panel(self) -> None:
        redaction_map = RedactionMap.create(
            [
                MappingEntry(
                    type="person",
                    original="张三",
                    masked="张某1",
                    role=None,
                    source="rule",
                    confidence=0.6,
                    restore_by_default=True,
                    reason="置信度低",
                ),
                MappingEntry(
                    type="person",
                    original="李四",
                    masked="李某1",
                    role=None,
                    source="manual_selection",
                    confidence=1.0,
                    restore_by_default=False,
                    reason="手工新增",
                ),
                MappingEntry(
                    type="organization",
                    original="甲公司",
                    masked="乙公司",
                    role=None,
                    source="sample_library:add",
                    confidence=1.0,
                    restore_by_default=True,
                ),
                MappingEntry(
                    type="case_number",
                    original="（2025）冀01民终123号",
                    masked="",
                    role=None,
                    source="court_case_number_parser",
                    confidence=1.0,
                    restore_by_default=False,
                ),
            ]
        )

        html = _render_redaction_result(
            "结果",
            "张三与李四在甲公司工作。",
            "张某1与李某1在乙公司工作。",
            redaction_map,
            [
                SimpleNamespace(
                    type="organization",
                    text="甲公司",
                    start=6,
                    end=9,
                    source="review",
                    confidence=1.0,
                    risk_level="medium",
                    auto_redact=True,
                    role=None,
                    reason="复核",
                    suggested_mask_type=None,
                    needs_review=True,
                )
            ],
            [],
            [],
        )

        self.assertIn('id="mapping-review-toolbar"', html)
        self.assertIn('data-map-filter="low_confidence"', html)
        self.assertIn('data-map-filter="manual_added"', html)
        self.assertIn('data-map-filter="restore_risk"', html)
        self.assertIn('data-map-filter="sample_reused"', html)
        self.assertIn('id="sample-summary-panel"', html)
        self.assertIn('data-map-row="1"', html)
        self.assertIn("low_confidence", html)
        self.assertIn("manual_added", html)
        self.assertIn("restore_risk", html)
        self.assertIn("sample_reused", html)
        self.assertIn('data-restore-risk-codes="empty_mask"', html)
        self.assertNotIn("restore_disabled", html)
        self.assertIn('id="mapping-review-candidates"', html)
        self.assertIn("甲公司", html)
        self.assertIn("reviewCandidateIndex[original]", html)

    def test_mapping_add_row_js_renumbers_filter_metadata(self) -> None:
        html = _page("结果", "")

        self.assertIn("c.dataset.mapRow=String(n)", html)
        self.assertIn("c.dataset.categories=''", html)
        self.assertIn("row.dataset.mapRow=String(index)", html)
        self.assertIn("tr.dataset.categories='manual_added'", html)
        self.assertIn("restoreRiskReasonsForRow", html)
        self.assertIn("baseline&&baseline.masked&&baseline.masked!==masked", html)
        self.assertIn("if(deleted)cats.push('delete_candidate')", html)
        self.assertIn("filterMappingRows(activeMappingFilter())", html)
        self.assertIn("function readCurrentMappingJson()", html)
        self.assertIn("readCurrentMappingJson()", html)
        self.assertIn("function ensureAppliedMappingForText()", html)
        self.assertIn("function prepareCurrentMapDownload(link)", html)
        self.assertIn("if (!ensureAppliedMappingForText()) return", html)
        self.assertNotIn("mapping-json-output').value}}], this)", html)
        self.assertIn("DOMContentLoaded", html)

    def test_mapping_review_classifier_skips_pipeline_sources_for_manual_added(self) -> None:
        for source in ("local_llm", "court_case_number_parser", "sample_library:add", "geoname_hierarchy"):
            with self.subTest(source=source):
                entry = MappingEntry(
                    type="organization",
                    original="测试公司",
                    masked="甲公司",
                    role=None,
                    source=source,
                    confidence=0.95,
                    restore_by_default=True,
                )
                categories = _classify_mapping_review_row(entry)
                self.assertNotIn("manual_added", categories)

        manual = MappingEntry(
            type="person",
            original="王五",
            masked="王某甲",
            role=None,
            source="manual_selection",
            confidence=1.0,
            restore_by_default=True,
        )
        self.assertIn("manual_added", _classify_mapping_review_row(manual))

        new_row = MappingEntry(
            type="person",
            original="赵六",
            masked="赵某甲",
            role=None,
            source="court_case_number_parser",
            confidence=1.0,
            restore_by_default=True,
        )
        self.assertIn("manual_added", _classify_mapping_review_row(new_row, is_new_row=True))

    def test_mapping_review_classifier_marks_modified_delete_and_restore_reasons(self) -> None:
        original = MappingEntry(
            type="person",
            original="李四",
            masked="李某1",
            role=None,
            source="rule",
            confidence=1.0,
            restore_by_default=True,
        )
        edited = MappingEntry(
            type="person",
            original="李四",
            masked="李某特制掩码",
            role=None,
            source="rule",
            confidence=1.0,
            restore_by_default=False,
        )

        categories = _classify_mapping_review_row(edited, original_entry=original, deleted=True)
        reason_codes = {item["reason_code"] for item in _restore_risk_reasons(edited, deleted=True)}
        not_deleted_categories = _classify_mapping_review_row(edited, original_entry=original, deleted=False)

        self.assertIn("modified", categories)
        self.assertIn("delete_candidate", categories)
        self.assertIn("restore_risk", categories)
        self.assertEqual(reason_codes, {"delete_candidate"})
        self.assertNotIn("restore_risk", not_deleted_categories)

    def test_case_workflow_panel_renders_all_states(self) -> None:
        cases = [
            ("not_saved", {}),
            ("saved_local", {"case_folder": "2026 3624", "saved_local": True}),
            ("bound_thread", {"case_folder": "2026 3624", "discord_thread_url": "https://discord.com/channels/1/2/3"}),
            ("sent_discord", {"case_folder": "2026 3624", "attach_status": "sent"}),
            ("waiting_hermes", {"case_folder": "2026 3624", "hermes_requested": True}),
            ("attach_failed", {"case_folder": "2026 3624", "attach_error": "boom"}),
        ]

        for state, kwargs in cases:
            with self.subTest(state=state):
                html = _render_case_workflow_panel(**kwargs)
                self.assertIn(f'data-workflow-state="{state}"', html)
                self.assertIn(f"workflow-{state}", html)
                self.assertIn("案件流程状态", html)

    def test_case_workflow_panel_renders_safe_restore_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = create_or_update_manifest(tmpdir, "2026 3624", "https://discord.com/channels/1/2/3")
            case_path = os.path.join(tmpdir, "2026 3624")
            redaction_map = RedactionMap.create(
                [
                    MappingEntry(
                        type="person",
                        original="张三",
                        masked="【PERSON_001】",
                        role=None,
                        source="test",
                        confidence=1.0,
                        restore_by_default=True,
                    )
                ]
            )
            save_redaction_map(os.path.join(case_path, "mapping", "redaction_map.enc"), redaction_map)
            restored_path = os.path.join(case_path, "restored", "judgment.restored.txt")
            os.makedirs(os.path.dirname(restored_path), exist_ok=True)
            with open(restored_path, "w", encoding="utf-8") as fh:
                fh.write("张三 restored full text /Users/private")
            write_last_restore_metadata(
                case_path,
                manifest,
                {
                    "status": "restored",
                    "restored_filename": "judgment.restored.txt",
                    "restored_relative_path": "restored/judgment.restored.txt",
                    "replacement_count": 1,
                    "unresolved_placeholder_count": 2,
                    "requested_at": None,
                    "completed_at": None,
                    "duration_ms": None,
                    "timing_reason": "missing_timestamp",
                    "metadata_status": "written",
                },
            )

            html = _render_case_workflow_panel(case_root=tmpdir, case_folder="2026 3624")

        self.assertIn("还原状态", html)
        self.assertIn("judgment.restored.txt", html)
        self.assertIn("未解析占位符", html)
        self.assertIn("2", html)
        self.assertNotIn("张三", html)
        self.assertNotIn("/Users", html)

    def test_auto_prefill_preserves_manual_values(self) -> None:
        self.assertTrue(_should_apply_auto_prefill("", ""))
        self.assertTrue(_should_apply_auto_prefill(" /tmp/old ", "/tmp/old"))
        self.assertFalse(_should_apply_auto_prefill("/tmp/manual", "/tmp/old"))
        self.assertFalse(_should_apply_auto_prefill("2026 9999", "2026 3624"))

    def test_case_creation_command_scrubs_path_like_cause(self) -> None:
        command = _case_creation_command(
            "2026 3624",
            "req-1",
            "/Users/jannerchang/private /Volumes/cases",
        )

        self.assertIn("案件目录：2026 3624", command)
        self.assertNotIn("/Users", command)
        self.assertNotIn("/Volumes", command)

    def test_create_thread_rejects_path_like_case_folder_before_posting(self) -> None:
        import asyncio

        with patch("legal_redactor.web_app._post_discord_channel_message") as post:
            response = asyncio.run(
                create_discord_thread(
                    MockJsonRequest(
                        {
                            "case_folder": "/Users/jannerchang/cases/2026 3624",
                            "case_cause": "劳动争议",
                        }
                    )
                )
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(post.called)
        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(data["code"], "invalid_case_folder")
        self.assertNotIn("/Users", data["message"])


if __name__ == "__main__":
    unittest.main()


# ── Security: XSS prevention in _diagnose_sample_entry ──────────────────

class TestDiagnoseSampleEntryXSS:
    """Ensure user-controlled sample values are HTML-escaped in diagnosis output."""

    def test_delete_entry_does_not_leak_user_input(self):
        from legal_redactor.web_app import _diagnose_sample_entry

        # The 'original' field is only used for regex matching, not displayed.
        # Verify no raw HTML from user input leaks into the output.
        entry = {
            "action": "delete",
            "original": "<script>alert(1)</script>",
            "masked": "",
        }
        result = _diagnose_sample_entry(entry)
        assert "<script>" not in result
        assert "alert(1)" not in result

    def test_modify_entry_escapes_masked_values(self):
        from legal_redactor.web_app import _diagnose_sample_entry

        entry = {
            "action": "modify",
            "original": "test",
            "old_masked": "<img src=x onerror=alert(1)>",
            "new_masked": "<svg onload=alert(1)>",
        }
        result = _diagnose_sample_entry(entry)
        assert "<img" not in result
        assert "<svg" not in result
        assert "&lt;img" in result
        assert "&lt;svg" in result

    def test_add_entry_escapes_masked_value(self):
        from legal_redactor.web_app import _diagnose_sample_entry

        entry = {
            "action": "add",
            "original": "safe_name",
            "masked": "<body onload=alert(1)>",
        }
        result = _diagnose_sample_entry(entry)
        assert "<body" not in result
        assert "&lt;body" in result

    def test_keep_entry_has_no_user_values(self):
        from legal_redactor.web_app import _diagnose_sample_entry

        entry = {"action": "keep"}
        result = _diagnose_sample_entry(entry)
        assert "确认无误" in result

    def test_manual_reason_is_escaped(self):
        from legal_redactor.web_app import _diagnose_sample_entry

        entry = {
            "action": "delete",
            "original": "test",
            "reason": "<iframe src=evil></iframe>",
        }
        result = _diagnose_sample_entry(entry)
        assert "<iframe" not in result
        assert "&lt;iframe" in result
