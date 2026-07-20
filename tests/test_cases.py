from __future__ import annotations

import pytest

from legal_redactor.cases import (
    CASE_WORKFLOW_STATES,
    DuplicateDiscordThreadError,
    InvalidCaseFolderError,
    InvalidDiscordThreadError,
    assert_remote_payload_safe,
    case_root_from_source_dir,
    case_thread_binding_status,
    case_workflow_state,
    compute_restore_duration_ms,
    create_or_update_manifest,
    find_case_by_discord_thread,
    invalid_workflow_decision_fields,
    load_last_restore_metadata,
    load_manifest,
    manifest_public_status,
    parse_discord_thread_id,
    record_hermes_thread_request,
    restore_status_summary,
    sanitize_case_relative_path,
    suggest_case_location_from_filenames,
    validate_case_folder_name,
    write_last_restore_metadata,
)


def test_validate_case_folder_name_rejects_path_traversal() -> None:
    for value in ["", "..", "../2025", "/tmp/case", "2025/8765", "2025\\8765"]:
        with pytest.raises(InvalidCaseFolderError):
            validate_case_folder_name(value)


def test_parse_discord_thread_id() -> None:
    assert (
        parse_discord_thread_id("https://discord.com/channels/111/222/333")
        == "333"
    )
    assert (
        parse_discord_thread_id("https://discordapp.com/channels/111/222/333")
        == "333"
    )


def test_create_manifest_schema(tmp_path) -> None:
    manifest = create_or_update_manifest(
        tmp_path,
        "2025 8765",
        "https://discord.com/channels/111/222/333",
        source_dir="/materials/2025 8765",
    )

    loaded = load_manifest(tmp_path / "2025 8765")
    assert loaded.schema_version == 1
    assert loaded.case_folder == manifest.case_folder == "2025 8765"
    assert loaded.discord_thread_id == "333"
    assert loaded.mapping_file == "mapping/redaction_map.enc"


def test_create_or_update_manifest_rejects_thread_mismatch(tmp_path) -> None:
    create_or_update_manifest(tmp_path, "2025 8765", "https://discord.com/channels/111/222/333")

    with pytest.raises(InvalidDiscordThreadError):
        create_or_update_manifest(tmp_path, "2025 8765", "https://discord.com/channels/111/222/444")

    loaded = load_manifest(tmp_path / "2025 8765")
    assert loaded.discord_thread_id == "333"
    assert loaded.discord_thread_url == "https://discord.com/channels/111/222/333"


def test_record_hermes_request_marks_manifest_waiting(tmp_path) -> None:
    manifest = record_hermes_thread_request(
        tmp_path,
        "2025 8765",
        "lr_test",
        command_message_id="m1",
        command_channel_id="c1",
    )

    loaded = load_manifest(tmp_path / "2025 8765")
    assert manifest.hermes_request_id == loaded.hermes_request_id == "lr_test"
    assert loaded.hermes_command_message_id == "m1"
    assert loaded.hermes_command_channel_id == "c1"
    assert loaded.discord_thread_url == ""
    assert case_workflow_state(manifest=loaded) == "waiting_hermes"


def test_workflow_state_vocabulary_is_fixed() -> None:
    assert CASE_WORKFLOW_STATES == {
        "not_saved",
        "saved_local",
        "bound_thread",
        "sent_discord",
        "waiting_hermes",
        "attach_failed",
    }
    assert case_workflow_state() == "not_saved"
    assert case_workflow_state(saved_local=True) == "saved_local"
    assert case_workflow_state(discord_thread_url="https://discord.com/channels/1/2/3") == "bound_thread"
    assert case_workflow_state(hermes_requested=True) == "waiting_hermes"
    assert case_workflow_state(attach_status="sent") == "sent_discord"
    assert case_workflow_state(attach_error="boom") == "attach_failed"


def test_invalid_workflow_decision_fields_are_detected() -> None:
    fields = invalid_workflow_decision_fields(
        {
            "filenames": ["a.docx"],
            "state": "sent_discord",
            "status": "success",
            "bound": True,
            "sent": True,
            "conflict_result": "ignore",
            "workflow_state": "bound_thread",
        }
    )

    assert fields == ["bound", "conflict_result", "sent", "state", "status", "workflow_state"]


def test_find_case_by_discord_thread_rejects_duplicates(tmp_path) -> None:
    create_or_update_manifest(tmp_path, "case-a", "https://discord.com/channels/1/2/3")
    create_or_update_manifest(tmp_path, "case-b", "https://discord.com/channels/1/2/3")

    with pytest.raises(DuplicateDiscordThreadError):
        find_case_by_discord_thread(tmp_path, "3")


def test_case_root_from_source_dir_requires_existing_source(tmp_path) -> None:
    source_case = tmp_path / "uploaded" / "case-a"
    source_case.mkdir(parents=True)

    assert case_root_from_source_dir(source_case, "case-a") == tmp_path / "uploaded"
    assert case_root_from_source_dir(tmp_path / "missing" / "case-a", "case-a") is None


def test_case_thread_binding_status_reports_manifest_conflict(tmp_path) -> None:
    create_or_update_manifest(tmp_path, "case-a", "https://discord.com/channels/1/2/3")

    status = case_thread_binding_status(
        tmp_path,
        "case-a",
        "https://discord.com/channels/1/2/4",
    )

    assert status["conflict"] is True
    assert status["code"] == "thread_mismatch"
    assert status["workflow_state"] == "bound_thread"


def test_case_thread_binding_status_reports_duplicate_thread(tmp_path) -> None:
    create_or_update_manifest(tmp_path, "case-a", "https://discord.com/channels/1/2/3")

    status = case_thread_binding_status(
        tmp_path,
        "case-b",
        "https://discord.com/channels/1/2/3",
    )

    assert status["conflict"] is True
    assert status["code"] == "duplicate_thread"
    assert status["bound_case"]["case_folder"] == "case-a"


def test_manifest_public_status_omits_local_paths_and_sensitive_values(tmp_path) -> None:
    manifest = create_or_update_manifest(tmp_path, "case-a", "https://discord.com/channels/1/2/3")
    restored_dir = tmp_path / "case-a" / "restored"
    restored_dir.mkdir()
    (restored_dir / "judgment.restored.txt").write_text("张三", encoding="utf-8")

    status = manifest_public_status(tmp_path / "case-a", manifest)

    assert status["workflow_state"] == "bound_thread"
    assert status["latest_restored"] == {"filename": "judgment.restored.txt"}
    assert status["restore"]["status"] == "missing_map"
    assert str(tmp_path) not in str(status)
    assert "张三" not in str(status)


def test_restore_metadata_summary_is_content_free(tmp_path) -> None:
    manifest = create_or_update_manifest(tmp_path, "case-a", "https://discord.com/channels/1/2/3")
    case_path = tmp_path / "case-a"
    mapping_path = case_path / manifest.mapping_file
    mapping_path.parent.mkdir(parents=True)
    mapping_path.write_text("{}", encoding="utf-8")
    output_path = case_path / "restored" / "judgment.restored.txt"
    output_path.parent.mkdir()
    output_path.write_text("张三 restored full text", encoding="utf-8")

    metadata = write_last_restore_metadata(
        case_path,
        manifest,
        {
            "status": "restored",
            "restored_filename": output_path.name,
            "restored_relative_path": "restored/judgment.restored.txt",
            "replacement_count": 2,
            "unresolved_placeholder_count": 1,
            "requested_at": "2026-06-29T00:00:00+00:00",
            "completed_at": "2026-06-29T00:00:01.250000+00:00",
            "duration_ms": 1250,
            "timing_reason": None,
            "metadata_status": "written",
        },
    )

    stored = load_last_restore_metadata(case_path, manifest)
    summary = restore_status_summary(case_path, manifest)

    assert metadata["schema_version"] == 1
    assert stored["replacement_count"] == 2
    assert summary["status"] == "restored"
    assert summary["restored_filename"] == "judgment.restored.txt"
    assert summary["restored_relative_path"] == "restored/judgment.restored.txt"
    assert summary["unresolved_placeholder_count"] == 1
    assert summary["duration_ms"] == 1250
    assert "unresolved_placeholders" not in str(summary)
    assert "张三" not in str(stored)
    assert str(tmp_path) not in str(summary)
    assert_remote_payload_safe(summary)


def test_restore_path_and_timing_helpers_are_safe(tmp_path) -> None:
    case_path = tmp_path / "case-a"
    inside = case_path / "restored" / "judgment.restored.txt"
    outside = tmp_path / "other" / "secret.txt"

    assert sanitize_case_relative_path(case_path, inside) == "restored/judgment.restored.txt"
    assert sanitize_case_relative_path(case_path, outside) == "secret.txt"
    assert compute_restore_duration_ms("2026-06-29T00:00:00+00:00", "2026-06-29T00:00:01.250000+00:00") == (1250, None)
    assert compute_restore_duration_ms(None, "2026-06-29T00:00:01+00:00") == (None, "missing_timestamp")


def test_remote_payload_safety_rejects_forbidden_fields_and_values() -> None:
    assert_remote_payload_safe({"restore": {"restored_filename": "judgment.txt"}})
    assert_remote_payload_safe({"restore": {"restored_relative_path": "restored/judgment.txt"}})
    for payload in [
        {"restore": {"unresolved_placeholders": ["【PERSON_001】"]}},
        {"restore": {"restored_relative_path": "/Users/example/private.txt"}},
        {"restore": {"restored_relative_path": "../../secret.txt"}},
        {"restore": {"restored_relative_path": "/private/model.bin"}},
        {"restore": {"restored_relative_path": "C:\\Users\\private-user\\private-model\\model.bin"}},
        {"restore": {"restored_relative_path": "C:/Users/example/private-model/model.bin"}},
        {"restore": {"restored_relative_path": "\\\\server\\share\\private-model\\model.bin"}},
        {"restore": {"restored_relative_path": "//server/share/private-model/model.bin"}},
        {"restore": {"restored_relative_path": "\\\\fileserver"}},
        {"restore": {"restored_relative_path": "restored\\judgment.txt"}},
        {"restore": {"restored_filename": "dir/judgment.txt"}},
        {"restore": {"restored_filename": "\\\\server\\share\\x.txt"}},
    ]:
        with pytest.raises(ValueError):
            assert_remote_payload_safe(payload)



def test_suggest_case_location_returns_evidence_and_manifest_summary(tmp_path) -> None:
    case_path = tmp_path / "2026 3624"
    case_path.mkdir()
    (case_path / "judgment.docx").write_text("placeholder", encoding="utf-8")
    create_or_update_manifest(tmp_path, "2026 3624", "https://discord.com/channels/1/2/3")

    result = suggest_case_location_from_filenames(["judgment.docx"], [tmp_path])

    assert result["status"] == "ok"
    assert result["case_folder"] == "2026 3624"
    assert result["case_root"] == str(tmp_path.resolve())
    assert result["discord_thread_url"] == "https://discord.com/channels/1/2/3"
    assert result["workflow_state"] == "bound_thread"
    assert {"kind": "filename_match", "filename": "judgment.docx"} in result["evidence"]
    assert result["manifest"]["mapping_present"] is False


def test_suggest_case_location_reports_conflict_for_requested_thread(tmp_path) -> None:
    case_path = tmp_path / "2026 3624"
    case_path.mkdir()
    (case_path / "judgment.docx").write_text("placeholder", encoding="utf-8")
    create_or_update_manifest(tmp_path, "2026 3624", "https://discord.com/channels/1/2/3")

    result = suggest_case_location_from_filenames(
        ["judgment.docx"],
        [tmp_path],
        discord_thread_url="https://discord.com/channels/1/2/4",
    )

    assert result["status"] == "conflict"
    assert result["conflict"] is True
    assert result["conflict_code"] == "thread_mismatch"


def test_suggest_case_location_reports_invalid_requested_thread(tmp_path) -> None:
    case_path = tmp_path / "2026 3624"
    case_path.mkdir()
    (case_path / "judgment.docx").write_text("placeholder", encoding="utf-8")

    result = suggest_case_location_from_filenames(
        ["judgment.docx"],
        [tmp_path],
        discord_thread_url="not-a-url",
    )

    assert result["status"] == "conflict"
    assert result["conflict_code"] == "invalid_discord_thread"
