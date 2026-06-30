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
    from legal_redactor.cases import create_or_update_manifest, write_last_restore_metadata
    from legal_redactor.io import redaction_map_to_json, save_redaction_map
    from legal_redactor.models import MappingEntry, RedactedDocument, RedactionMap, RedactionResult
    from legal_redactor.web_app import (
        _case_creation_command,
        _classify_mapping_review_row,
        _decode_text_bytes,
        _persist_optional_case_redaction,
        _read_restore_map_text,
        _read_upload_text,
        _render_case_workflow_panel,
        _page,
        _render_redaction_result,
        _render_status_panel,
        _restore_risk_reasons,
        _should_apply_auto_prefill,
        _suggest_manual_mapping_entry,
        _suggest_case_location_from_filenames,
        send_redacted_to_discord,
        attach_to_bound_discord_thread,
        app,
        create_discord_thread,
        health,
        index,
    )
except RuntimeError as exc:  # Web deps are optional for non-Web unit runs.
    _case_creation_command = None
    _classify_mapping_review_row = None
    _decode_text_bytes = None
    _persist_optional_case_redaction = None
    _read_restore_map_text = None
    _read_upload_text = None
    _render_case_workflow_panel = None
    _page = None
    _render_redaction_result = None
    _render_status_panel = None
    _restore_risk_reasons = None
    _should_apply_auto_prefill = None
    _suggest_manual_mapping_entry = None
    _suggest_case_location_from_filenames = None
    send_redacted_to_discord = None
    attach_to_bound_discord_thread = None
    app = None
    create_discord_thread = None
    health = None
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

    def test_save_to_local_endpoint(self) -> None:
        import asyncio
        from legal_redactor.web_app import save_to_local

        with tempfile.TemporaryDirectory() as tmpdir:
            payload = {
                "directory": tmpdir,
                "files": [
                    {"filename": "test1.txt", "content": "Hello World"},
                    {"filename": "test2.json", "content": '{"a": 1}'}
                ]
            }
            response = asyncio.run(save_to_local(MockJsonRequest(payload)))
            self.assertEqual(response.status_code, 200)

            data = json.loads(response.body.decode("utf-8"))
            self.assertEqual(data["status"], "success")

            # 校验物理文件确实存在且内容正确
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "test1.txt")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "test2.json")))

            with open(os.path.join(tmpdir, "test1.txt"), "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "Hello World")
            with open(os.path.join(tmpdir, "test2.json"), "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), '{"a": 1}')

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

            result = _suggest_case_location_from_filenames(["judgment.docx"], [Path(tmpdir)])

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

            result = _suggest_case_location_from_filenames(
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

        with patch("legal_redactor.web_app._discord_command_channel_id", return_value="1501248343823880345"):
            with patch("legal_redactor.web_app._post_discord_channel_message", side_effect=fake_post):
                response = asyncio.run(
                    create_discord_thread(
                        MockJsonRequest(
                            {
                                "case_folder": "2026 5987",
                                "case_cause": "劳动争议纠纷",
                                "request_id": "lr_test",
                            }
                        )
                    )
                )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(data["status"], "pending")
        self.assertEqual(data["workflow_state"], "waiting_hermes")
        self.assertEqual(data["request_id"], "lr_test")
        self.assertEqual(calls, [("1501248343823880345", _case_creation_command("2026 5987", "lr_test", "劳动争议纠纷"))])

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

        with patch.dict(os.environ, {"LEGAL_REDACTOR_DISCORD_BOT_TOKEN": "bot-token"}):
            with patch("legal_redactor.web_app._discord_command_channel_id", return_value="1"):
                with patch("legal_redactor.web_app.urllib.request.urlopen", side_effect=fail):
                    response = asyncio.run(
                        create_discord_thread(
                            MockJsonRequest(
                                {
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
            self.assertEqual(calls, [("3", "redacted.txt", "【PERSON_001】", "脱敏文件已生成，请见附件：redacted.txt")])
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
        self.assertIn('data-restore-risk-codes="restore_disabled"', html)
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

        self.assertIn("modified", categories)
        self.assertIn("delete_candidate", categories)
        self.assertIn("restore_risk", categories)
        self.assertEqual(reason_codes, {"delete_candidate", "restore_disabled"})

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
