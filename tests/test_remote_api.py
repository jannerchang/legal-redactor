from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from legal_redactor.cases import assert_remote_payload_safe, create_or_update_manifest, load_last_restore_metadata
from legal_redactor.io import save_redaction_map
from legal_redactor.models import MappingEntry, RedactionMap

from legal_redactor.remote_api import (
    RestoreTextRequest,
    bind_discord_thread_to_case,
    case_status_by_thread,
    find_case_by_thread,
    require_api_token,
    restore_text_by_thread,
    restore_text_for_thread,
)


def _map() -> RedactionMap:
    return RedactionMap.create(
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


def test_restore_text_for_thread_saves_file_without_mapping_values_in_response(tmp_path) -> None:
    create_or_update_manifest(tmp_path, "2025 8765", "https://discord.com/channels/1/2/3")
    mapping_path = tmp_path / "2025 8765" / "mapping" / "redaction_map.enc"
    save_redaction_map(mapping_path, _map())

    result = restore_text_for_thread(tmp_path, "3", "本院认为，【PERSON_001】应付款。")

    assert result["ok"] is True
    assert result["code"] == "restored"
    assert result["case"]["case_folder"] == "2025 8765"
    assert result["restore"]["replacement_count"] == 1
    assert result["restore"]["unresolved_placeholder_count"] == 0
    assert result["restore"]["restored_filename"].startswith("judgment.restored.")
    assert result["restore"]["restored_relative_path"].startswith("restored/judgment.restored.")
    assert result["next_action"] == "open_office_restored_file"
    assert "restored_file" not in result
    assert "restored_file" not in result["restore"]
    assert "unresolved_placeholders" not in str(result)
    assert "张三" not in str(result)
    assert "【PERSON_001】" not in str(result)
    assert str(tmp_path) not in str(result)
    assert (tmp_path / "2025 8765" / "restored").exists()
    restored_path = tmp_path / "2025 8765" / result["restore"]["restored_relative_path"]
    assert "张三" in restored_path.read_text(encoding="utf-8")
    metadata = load_last_restore_metadata(tmp_path / "2025 8765", create_or_update_manifest(tmp_path, "2025 8765", "https://discord.com/channels/1/2/3"))
    assert metadata["unresolved_placeholder_count"] == 0
    assert_remote_payload_safe(result)


def test_restore_text_for_thread_reports_unknown_placeholder(tmp_path) -> None:
    create_or_update_manifest(tmp_path, "case", "https://discord.com/channels/1/2/3")
    save_redaction_map(tmp_path / "case" / "mapping" / "redaction_map.enc", _map())

    result = restore_text_for_thread(tmp_path, "3", "另有【UNKNOWN_001】。")

    assert result["restore"]["unresolved_placeholder_count"] == 1
    assert "【UNKNOWN_001】" not in str(result)
    assert "unresolved_placeholders" not in str(result)


def test_bind_discord_thread_to_case_writes_manifest(tmp_path) -> None:
    result = bind_discord_thread_to_case(
        tmp_path,
        "2025 8765",
        "https://discord.com/channels/1/2/3",
        source_dir="/cases/2025 8765",
    )

    assert result["ok"] is True
    assert result["case_folder"] == "2025 8765"
    assert result["discord_thread_url"] == "https://discord.com/channels/1/2/3"
    assert result["discord_thread_id"] == "3"
    manifest_text = (tmp_path / "2025 8765" / "manifest.json").read_text(encoding="utf-8")
    assert "https://discord.com/channels/1/2/3" in manifest_text


def test_bind_discord_thread_to_case_rejects_duplicate_before_write(tmp_path) -> None:
    create_or_update_manifest(tmp_path, "case-a", "https://discord.com/channels/1/2/3")

    with pytest.raises(Exception) as raised:
        bind_discord_thread_to_case(
            tmp_path,
            "case-b",
            "https://discord.com/channels/1/2/3",
        )

    assert getattr(raised.value, "code", "") == "duplicate_thread"
    assert not (tmp_path / "case-b" / "manifest.json").exists()


def test_bind_discord_thread_to_case_rejects_cross_root_duplicate_before_write(tmp_path, monkeypatch) -> None:
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    create_or_update_manifest(root_a, "case-a", "https://discord.com/channels/1/2/3")
    monkeypatch.setattr("legal_redactor.remote_api._bind_case_root_candidates", lambda configured: [root_b, root_a])

    with pytest.raises(Exception) as raised:
        bind_discord_thread_to_case(
            root_b,
            "case-b",
            "https://discord.com/channels/1/2/3",
        )

    assert getattr(raised.value, "code", "") == "duplicate_thread"
    assert not (root_b / "case-b" / "manifest.json").exists()


def test_bind_discord_thread_to_case_prefers_source_dir_over_case_root_override(tmp_path) -> None:
    configured_root = tmp_path / "configured-root"
    uploaded_case = tmp_path / "uploaded-documents" / "case"
    uploaded_case.mkdir(parents=True)

    result = bind_discord_thread_to_case(
        configured_root,
        "case",
        "https://discord.com/channels/1/2/3",
        source_dir=str(uploaded_case),
        case_root_override=configured_root,
    )

    assert result["ok"] is True
    assert (uploaded_case / "manifest.json").exists()
    assert not (configured_root / "case" / "manifest.json").exists()


def test_case_status_by_thread_returns_discord_thread_url(tmp_path, monkeypatch) -> None:
    create_or_update_manifest(tmp_path, "2026 6372", "https://discord.com/channels/1498679306967056394/1520000496138457160")
    monkeypatch.setattr("legal_redactor.remote_api.get_case_root", lambda: tmp_path)
    monkeypatch.setattr("legal_redactor.remote_api._bind_case_root_candidates", lambda configured: [tmp_path])

    result = case_status_by_thread("1520000496138457160", None)

    assert result["ok"] is True
    assert result["code"] == "missing_map"
    assert result["case"]["case_folder"] == "2026 6372"
    assert result["case"]["discord_thread_id"] == "1520000496138457160"
    assert result["case"]["discord_thread_url"] == "https://discord.com/channels/1498679306967056394/1520000496138457160"
    assert result["restore"]["status"] == "missing_map"
    assert result["next_action"] == "upload_mapping"
    assert_remote_payload_safe(result)


def test_case_status_by_thread_reports_latest_restore_safely(tmp_path, monkeypatch) -> None:
    create_or_update_manifest(tmp_path, "case", "https://discord.com/channels/1/2/3")
    save_redaction_map(tmp_path / "case" / "mapping" / "redaction_map.enc", _map())
    restore_text_for_thread(tmp_path, "3", "本院认为，【PERSON_001】应付款。")
    monkeypatch.setattr("legal_redactor.remote_api.get_case_root", lambda: tmp_path)
    monkeypatch.setattr("legal_redactor.remote_api._bind_case_root_candidates", lambda configured: [tmp_path])

    result = case_status_by_thread("3", None)

    assert result["ok"] is True
    assert result["code"] == "restored"
    assert result["restore"]["status"] == "restored"
    assert result["restore"]["restored_relative_path"].startswith("restored/")
    assert str(tmp_path) not in str(result)
    assert "张三" not in str(result)
    assert_remote_payload_safe(result)


def test_case_status_by_thread_prefers_dynamic_root_with_mapping_over_empty_shell(tmp_path, monkeypatch) -> None:
    fixed_root = tmp_path / "configured"
    dynamic_search_root = tmp_path / "dynamic"
    real_case_root = dynamic_search_root / "uploaded-documents"
    create_or_update_manifest(fixed_root, "case", "https://discord.com/channels/1/2/3")
    create_or_update_manifest(real_case_root, "case", "https://discord.com/channels/1/2/3")
    save_redaction_map(real_case_root / "case" / "mapping" / "redaction_map.enc", _map())
    monkeypatch.setattr("legal_redactor.remote_api.get_case_root", lambda: fixed_root)
    monkeypatch.setattr("legal_redactor.remote_api._bind_case_root_candidates", lambda configured: [fixed_root, dynamic_search_root])

    case_path, manifest = find_case_by_thread("3")
    result = case_status_by_thread("3", None)

    assert case_path == (real_case_root / "case").resolve()
    assert manifest.case_folder == "case"
    assert result["ok"] is True
    assert result["case"]["mapping_present"] is True
    assert result["code"] == "no_restore_yet"


def test_case_status_by_thread_rejects_duplicate_thread_across_roots(tmp_path, monkeypatch) -> None:
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    create_or_update_manifest(root_a, "case-a", "https://discord.com/channels/1/2/3")
    create_or_update_manifest(root_b, "case-b", "https://discord.com/channels/1/2/3")
    monkeypatch.setattr("legal_redactor.remote_api.get_case_root", lambda: root_a)
    monkeypatch.setattr("legal_redactor.remote_api._bind_case_root_candidates", lambda configured: [root_a, root_b])

    with pytest.raises(HTTPException) as raised:
        case_status_by_thread("3", None)

    assert raised.value.status_code == 409
    assert raised.value.detail["error"]["code"] == "duplicate_thread"
    assert "case-a" not in str(raised.value.detail)
    assert "case-b" not in str(raised.value.detail)


def test_restore_by_thread_reports_missing_map_as_safe_error(tmp_path, monkeypatch) -> None:
    create_or_update_manifest(tmp_path, "case", "https://discord.com/channels/1/2/3")
    monkeypatch.setattr("legal_redactor.remote_api.get_case_root", lambda: tmp_path)

    with pytest.raises(HTTPException) as raised:
        restore_text_by_thread("3", RestoreTextRequest(draft_text="draft"), None)

    assert raised.value.status_code == 409
    assert raised.value.detail == {
        "ok": False,
        "error": {
            "code": "missing_map",
            "status": 409,
            "message": "案件映射表不存在",
            "next_action": "upload_mapping",
        },
    }


def test_require_api_token_rejects_wrong_token(monkeypatch) -> None:
    monkeypatch.setenv("LEGAL_REDACTOR_API_TOKEN", "secret")

    try:
        require_api_token("Bearer wrong")
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail["error"]["code"] == "unauthorized"
        assert exc.detail["error"]["status"] == 401
        assert "secret" not in str(exc.detail)
    else:
        raise AssertionError("expected HTTPException")


def test_require_api_token_reads_json_config(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "api.local.json"
    config_path.write_text(json.dumps({"api_token": "secret"}), encoding="utf-8")
    monkeypatch.delenv("LEGAL_REDACTOR_API_TOKEN", raising=False)
    monkeypatch.setenv("LEGAL_REDACTOR_API_CONFIG", str(config_path))

    require_api_token("Bearer secret")
