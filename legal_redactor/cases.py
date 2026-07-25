from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from .io import save_redaction_map_auto
from .models import RedactedDocument, RedactionMap


MANIFEST_FILENAME = "manifest.json"
LAST_RESTORE_METADATA_FILENAME = "last_restore_metadata.json"
DEFAULT_CASES_DIR = "~/Documents/legal-redactor-cases"
DISCORD_THREAD_RE = re.compile(r"^https://(?:canary\.|ptb\.)?discord(?:app)?\.com/channels/\d+/\d+(?:/\d+)?")
CASE_WORKFLOW_STATES = frozenset(
    {
        "not_saved",
        "saved_local",
        "bound_thread",
        "sent_discord",
        "waiting_hermes",
        "attach_failed",
    }
)
FORGED_WORKFLOW_DECISION_FIELDS = frozenset(
    {
        "state",
        "status",
        "bound",
        "sent",
        "conflict_result",
        "workflow_state",
    }
)
REMOTE_FORBIDDEN_KEYS = frozenset(
    {
        "restored_text",
        "restored_file",
        "draft_text",
        "original",
        "masked",
        "mapping",
        "redaction_map",
        "map_entries",
        "case_root",
        "source_dir",
        "api_token",
        "authorization",
        "token",
        "body",
        "traceback",
        "sample_entries",
        "unresolved_placeholders",
    }
)
REMOTE_FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"/Users/"),
    re.compile(r"/Volumes/"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"secret-token[^\s,;\"']*", re.IGNORECASE),
)


_REMOTE_PATH_KEYS = ("relative_path", "filename")
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_UNC_PATH_RE = re.compile(r"^(?:\\\\|//)[^\\/]+(?:[\\/]|$)")


def _remote_path_issue(key: str, value: str) -> str | None:
    lower = key.lower()
    text = value.strip()
    if not text:
        return None
    if "filename" in lower:
        if (
            Path(text).name != text
            or PurePosixPath(text).name != text
            or _WINDOWS_ABSOLUTE_PATH_RE.match(text)
            or _UNC_PATH_RE.match(text)
            or "\\" in text
            or "/" in text
        ):
            return "filename must be basename"
        return None
    if not any(marker in lower for marker in _REMOTE_PATH_KEYS):
        return None
    if _UNC_PATH_RE.match(text) or text.startswith("\\\\"):
        return "path must not be remote or network path"
    if text.startswith(("/", "~")) or _WINDOWS_ABSOLUTE_PATH_RE.match(text):
        return "path must be relative"
    if "\\" in text:
        return "path must use posix separators"
    parts = PurePosixPath(text).parts
    if any(part in {"..", ""} for part in parts):
        return "path must not escape case folder"
    if parts and parts[0] in {"private", "Users", "Volumes", "var"}:
        return "path must not expose local system path"
    return None


class CaseError(ValueError):
    code = "case_error"


class InvalidCaseFolderError(CaseError):
    code = "invalid_case_folder"


class InvalidDiscordThreadError(CaseError):
    code = "invalid_discord_thread"


class CaseNotFoundError(CaseError):
    code = "case_not_found"


class DuplicateDiscordThreadError(CaseError):
    code = "duplicate_thread"


class MissingMapError(CaseError):
    code = "missing_map"


class InvalidWorkflowInputError(CaseError):
    code = "INVALID_INPUT"

    def __init__(self, fields: list[str]) -> None:
        self.fields = fields
        super().__init__("请求包含不能由浏览器提交的工作流决策字段")


@dataclass
class RedactedFileRecord:
    filename: str
    sha256: str | None = None
    discord_attachment_id: str | None = None


@dataclass
class CaseManifest:
    schema_version: int
    case_folder: str
    created_at: str
    updated_at: str
    source_dir: str | None
    discord_thread_url: str
    discord_thread_id: str
    hermes_request_id: str = ""
    hermes_requested_at: str = ""
    hermes_command_message_id: str = ""
    hermes_command_channel_id: str = ""
    redacted_dir: str = "redacted"
    mapping_dir: str = "mapping"
    restored_dir: str = "restored"
    mapping_file: str = "mapping/redaction_map.enc"
    redacted_files: list[RedactedFileRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["redacted_files"] = [asdict(item) for item in self.redacted_files]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "CaseManifest":
        records = [
            RedactedFileRecord(
                filename=str(item.get("filename", "")),
                sha256=item.get("sha256"),
                discord_attachment_id=item.get("discord_attachment_id"),
            )
            for item in data.get("redacted_files", [])
        ]
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            case_folder=str(data["case_folder"]),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            source_dir=data.get("source_dir"),
            discord_thread_url=str(data.get("discord_thread_url", "")),
            discord_thread_id=str(data["discord_thread_id"]),
            hermes_request_id=str(data.get("hermes_request_id", "")),
            hermes_requested_at=str(data.get("hermes_requested_at", "")),
            hermes_command_message_id=str(data.get("hermes_command_message_id", "")),
            hermes_command_channel_id=str(data.get("hermes_command_channel_id", "")),
            redacted_dir=str(data.get("redacted_dir", "redacted")),
            mapping_dir=str(data.get("mapping_dir", "mapping")),
            restored_dir=str(data.get("restored_dir", "restored")),
            mapping_file=str(data.get("mapping_file", "mapping/redaction_map.enc")),
            redacted_files=records,
        )


def default_case_root() -> Path:
    return Path(os.environ.get("LEGAL_REDACTOR_CASE_ROOT", DEFAULT_CASES_DIR)).expanduser()


def validate_case_folder_name(case_folder: str) -> str:
    value = case_folder.strip()
    if not value:
        raise InvalidCaseFolderError("案件文件夹名不能为空")
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise InvalidCaseFolderError("案件文件夹名不能包含路径分隔符")
    if Path(value).is_absolute() or ".." in Path(value).parts:
        raise InvalidCaseFolderError("案件文件夹名不能是绝对路径或包含上级目录")
    return value


def case_dir(case_root: str | Path, case_folder: str) -> Path:
    safe_name = validate_case_folder_name(case_folder)
    root = Path(case_root).expanduser().resolve()
    target = (root / safe_name).resolve()
    if root != target and root not in target.parents:
        raise InvalidCaseFolderError("案件目录越过 case root")
    return target


def case_root_from_source_dir(source_dir: str | Path | None, case_folder: str) -> Path | None:
    """Infer a case root from the uploaded/source document location."""

    source_value = str(source_dir or "").strip()
    if not source_value:
        return None
    folder = validate_case_folder_name(case_folder)
    source_path = Path(source_value).expanduser()
    if not source_path.exists():
        return None
    if source_path.is_file():
        source_path = source_path.parent
    if source_path.name == folder:
        return source_path.parent
    if (source_path / folder).exists():
        return source_path
    return None


def parse_discord_thread_id(url: str) -> str:
    value = url.strip()
    if not DISCORD_THREAD_RE.match(value):
        raise InvalidDiscordThreadError("Discord 帖子链接格式不正确")
    parsed = urlparse(value)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3 or parts[0] != "channels":
        raise InvalidDiscordThreadError("Discord 帖子链接缺少 thread id")
    return parts[-1]


def load_manifest(path_or_case_dir: str | Path) -> CaseManifest:
    path = Path(path_or_case_dir)
    if path.is_dir():
        path = path / MANIFEST_FILENAME
    return CaseManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_manifest(case_path: str | Path, manifest: CaseManifest) -> Path:
    directory = Path(case_path)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / MANIFEST_FILENAME
    manifest.updated_at = _now_iso()
    payload = json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False) as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)
    tmp_path.replace(target)
    return target


def invalid_workflow_decision_fields(payload: Mapping[str, object]) -> list[str]:
    """Return browser-submitted fields that must be server-computed."""

    return sorted(
        str(key)
        for key in payload.keys()
        if str(key) in FORGED_WORKFLOW_DECISION_FIELDS
    )


def raise_for_forged_workflow_fields(payload: Mapping[str, object]) -> None:
    fields = invalid_workflow_decision_fields(payload)
    if fields:
        raise InvalidWorkflowInputError(fields)


def assert_remote_payload_safe(payload: object) -> None:
    """Reject fields and values that must not leave the Office authority boundary."""

    issues: list[str] = []
    _collect_remote_payload_issues(payload, "$", issues)
    if issues:
        raise ValueError("; ".join(issues))


def sanitize_case_relative_path(case_path: str | Path, target_path: str | Path | None) -> str | None:
    if target_path is None or str(target_path).strip() == "":
        return None
    case_dir_path = Path(case_path).expanduser().resolve()
    raw_target = Path(str(target_path)).expanduser()
    candidate = raw_target if raw_target.is_absolute() else case_dir_path / raw_target
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate.absolute()
    try:
        relative = resolved.relative_to(case_dir_path)
    except ValueError:
        return raw_target.name or resolved.name
    value = relative.as_posix()
    if not value or value == "." or value.startswith("../") or "/../" in value:
        return raw_target.name or resolved.name
    return value


def compute_restore_duration_ms(
    requested_at: str | None,
    completed_at: str | None,
) -> tuple[int | None, str | None]:
    requested = _parse_iso_datetime(requested_at)
    completed = _parse_iso_datetime(completed_at)
    if requested is None or completed is None:
        return None, "missing_timestamp"
    delta = completed - requested
    if delta.total_seconds() < 0:
        return None, "missing_timestamp"
    return int(delta.total_seconds() * 1000), None


def restore_metadata_path(case_path: str | Path, manifest: CaseManifest) -> Path:
    return Path(case_path) / manifest.restored_dir / LAST_RESTORE_METADATA_FILENAME


def load_last_restore_metadata(case_path: str | Path, manifest: CaseManifest) -> dict | None:
    target = restore_metadata_path(case_path, manifest)
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_last_restore_metadata(
    case_path: str | Path,
    manifest: CaseManifest,
    metadata: Mapping[str, object],
) -> dict:
    directory = Path(case_path) / manifest.restored_dir
    directory.mkdir(parents=True, exist_ok=True)
    restored_relative_path = sanitize_case_relative_path(case_path, metadata.get("restored_relative_path") or metadata.get("restored_path"))
    restored_filename = str(metadata.get("restored_filename") or Path(restored_relative_path or "").name or "")
    duration_ms = _nullable_int(metadata.get("duration_ms"))
    timing_reason = metadata.get("timing_reason")
    if duration_ms is None and timing_reason is None:
        duration_ms, timing_reason = compute_restore_duration_ms(
            _nullable_str(metadata.get("requested_at")),
            _nullable_str(metadata.get("completed_at")),
        )
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": str(metadata.get("status") or "restored"),
        "restored_filename": restored_filename or None,
        "restored_relative_path": restored_relative_path,
        "replacement_count": _nullable_int(metadata.get("replacement_count")),
        "unresolved_placeholder_count": _nullable_int(metadata.get("unresolved_placeholder_count")),
        "requested_at": _nullable_str(metadata.get("requested_at")),
        "completed_at": _nullable_str(metadata.get("completed_at")),
        "duration_ms": duration_ms,
        "timing_reason": timing_reason,
        "metadata_status": str(metadata.get("metadata_status") or "written"),
    }
    assert_remote_payload_safe(payload)
    target = restore_metadata_path(case_path, manifest)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False) as tmp:
        tmp.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(target)
    return payload


def restore_status_summary(case_path: str | Path, manifest: CaseManifest) -> dict:
    directory = Path(case_path)
    mapping_present = (directory / manifest.mapping_file).exists()
    base: dict[str, object] = {
        "status": "no_restore_yet",
        "restored_filename": None,
        "restored_relative_path": None,
        "replacement_count": None,
        "unresolved_placeholder_count": None,
        "requested_at": None,
        "completed_at": None,
        "duration_ms": None,
        "timing_reason": "metadata_missing",
        "metadata_status": "missing",
    }
    if not mapping_present:
        latest_restored = _latest_restored_file(directory / manifest.restored_dir)
        if latest_restored is not None:
            base["restored_filename"] = latest_restored.name
            base["restored_relative_path"] = sanitize_case_relative_path(directory, latest_restored)
        base["status"] = "missing_map"
        assert_remote_payload_safe(base)
        return base

    metadata = load_last_restore_metadata(directory, manifest)
    if metadata:
        status = str(metadata.get("status") or "restored")
        if status not in {"restored", "restore_failed", "metadata_unknown", "no_restore_yet", "missing_map"}:
            status = "restored"
        duration_ms = _nullable_int(metadata.get("duration_ms"))
        timing_reason = _nullable_str(metadata.get("timing_reason"))
        if duration_ms is None and timing_reason is None:
            duration_ms, timing_reason = compute_restore_duration_ms(
                _nullable_str(metadata.get("requested_at")),
                _nullable_str(metadata.get("completed_at")),
            )
        summary = {
            "status": status,
            "restored_filename": _safe_filename(metadata.get("restored_filename")),
            "restored_relative_path": sanitize_case_relative_path(directory, metadata.get("restored_relative_path")),
            "replacement_count": _nullable_int(metadata.get("replacement_count")),
            "unresolved_placeholder_count": _nullable_int(metadata.get("unresolved_placeholder_count")),
            "requested_at": _nullable_str(metadata.get("requested_at")),
            "completed_at": _nullable_str(metadata.get("completed_at")),
            "duration_ms": duration_ms,
            "timing_reason": timing_reason,
            "metadata_status": str(metadata.get("metadata_status") or "present"),
        }
        assert_remote_payload_safe(summary)
        return summary

    latest_restored = _latest_restored_file(directory / manifest.restored_dir)
    if latest_restored is not None:
        base.update(
            {
                "status": "metadata_unknown",
                "restored_filename": latest_restored.name,
                "restored_relative_path": sanitize_case_relative_path(directory, latest_restored),
                "timing_reason": "metadata_missing",
            }
        )
    assert_remote_payload_safe(base)
    return base


def create_or_update_manifest(
    case_root: str | Path,
    case_folder: str,
    discord_thread_url: str,
    *,
    source_dir: str | None = None,
    redacted_files: list[RedactedFileRecord] | None = None,
) -> CaseManifest:
    requested_thread_url = discord_thread_url.strip()
    thread_id = parse_discord_thread_id(requested_thread_url) if requested_thread_url else ""
    case_path = case_dir(case_root, case_folder)
    existing = case_path / MANIFEST_FILENAME
    if existing.exists():
        manifest = load_manifest(existing)
        if requested_thread_url and manifest.discord_thread_id and manifest.discord_thread_id != thread_id:
            raise InvalidDiscordThreadError("已有案件绑定了不同的 Discord 帖子")
        if requested_thread_url:
            manifest.discord_thread_url = requested_thread_url
            manifest.discord_thread_id = thread_id
        manifest.source_dir = source_dir or manifest.source_dir
        if redacted_files is not None:
            manifest.redacted_files = redacted_files
    else:
        now = _now_iso()
        manifest = CaseManifest(
            schema_version=1,
            case_folder=validate_case_folder_name(case_folder),
            created_at=now,
            updated_at=now,
            source_dir=source_dir,
            discord_thread_url=requested_thread_url,
            discord_thread_id=thread_id,
            redacted_files=redacted_files or [],
        )
    save_manifest(case_path, manifest)
    return manifest


def record_hermes_thread_request(
    case_root: str | Path,
    case_folder: str,
    request_id: str,
    *,
    source_dir: str | None = None,
    command_message_id: str = "",
    command_channel_id: str = "",
) -> CaseManifest:
    manifest = create_or_update_manifest(case_root, case_folder, "", source_dir=source_dir)
    if not manifest.discord_thread_url:
        manifest.hermes_request_id = str(request_id).strip()
        manifest.hermes_requested_at = _now_iso()
        manifest.hermes_command_message_id = str(command_message_id or "")
        manifest.hermes_command_channel_id = str(command_channel_id or "")
        save_manifest(case_dir(case_root, case_folder), manifest)
    return manifest


def case_thread_binding_status(
    case_root: str | Path,
    case_folder: str,
    discord_thread_url: str = "",
) -> dict:
    """Preflight a case/thread binding without writing local manifest state."""

    case_path = case_dir(case_root, case_folder)
    requested_url = discord_thread_url.strip()
    requested_id = parse_discord_thread_id(requested_url) if requested_url else ""
    manifest = None
    if (case_path / MANIFEST_FILENAME).exists():
        manifest = load_manifest(case_path)
        if requested_id and manifest.discord_thread_id and manifest.discord_thread_id != requested_id:
            return {
                "conflict": True,
                "code": "thread_mismatch",
                "message": "已有案件绑定了不同的 Discord 帖子",
                "workflow_state": case_workflow_state(manifest=manifest),
                "manifest": manifest_safe_summary(case_path, manifest),
            }

    if requested_id:
        try:
            bound_case_path, bound_manifest = find_case_by_discord_thread(case_root, requested_id)
        except CaseNotFoundError:
            pass
        else:
            if bound_case_path.resolve() != case_path.resolve():
                return {
                    "conflict": True,
                    "code": "duplicate_thread",
                    "message": "该 Discord 帖子已绑定到其他案件",
                    "workflow_state": case_workflow_state(manifest=manifest),
                    "bound_case": {
                        "case_folder": bound_manifest.case_folder,
                        "discord_thread_url": bound_manifest.discord_thread_url,
                        "discord_thread_id": bound_manifest.discord_thread_id,
                    },
                    "manifest": manifest_safe_summary(case_path, manifest) if manifest else None,
                }

    return {
        "conflict": False,
        "code": "ok" if manifest else "missing_manifest",
        "workflow_state": case_workflow_state(
            manifest=manifest,
            discord_thread_url=requested_url,
            saved_local=bool(manifest),
        ),
        "manifest": manifest_safe_summary(case_path, manifest) if manifest else None,
    }


def find_case_by_discord_thread(case_root: str | Path, discord_thread_id: str) -> tuple[Path, CaseManifest]:
    root = Path(case_root).expanduser()
    matches: list[tuple[Path, CaseManifest]] = []
    if not root.exists():
        raise CaseNotFoundError("案件根目录不存在")
    for manifest_path in root.glob(f"*/{MANIFEST_FILENAME}"):
        try:
            manifest = load_manifest(manifest_path)
        except Exception:
            continue
        if manifest.discord_thread_id == str(discord_thread_id):
            matches.append((manifest_path.parent, manifest))
    if not matches:
        raise CaseNotFoundError("未找到绑定该 Discord 帖子的案件")
    if len(matches) > 1:
        raise DuplicateDiscordThreadError("多个案件绑定了同一个 Discord 帖子")
    return matches[0]


def persist_case_redaction(
    case_root: str | Path,
    case_folder: str,
    discord_thread_url: str,
    documents: list[RedactedDocument],
    redaction_map: RedactionMap,
    *,
    source_dir: str | None = None,
) -> CaseManifest:
    manifest = create_or_update_manifest(case_root, case_folder, discord_thread_url, source_dir=source_dir)
    directory = case_dir(case_root, case_folder)
    redacted_dir = directory / manifest.redacted_dir
    mapping_path = directory / manifest.mapping_file
    redacted_dir.mkdir(parents=True, exist_ok=True)
    (directory / manifest.mapping_dir).mkdir(parents=True, exist_ok=True)
    (directory / manifest.restored_dir).mkdir(parents=True, exist_ok=True)

    records: list[RedactedFileRecord] = []
    multiple_documents = len(documents) > 1
    for index, document in enumerate(documents, start=1):
        filename = _redacted_filename(index=index, multiple_documents=multiple_documents, document=document)
        output_path = redacted_dir / filename
        temporary_path = redacted_dir / f".{filename}.tmp"
        if document.output_bytes is not None:
            temporary_path.write_bytes(document.output_bytes)
        else:
            temporary_path.write_text(document.redacted_text, encoding="utf-8")
        temporary_path.replace(output_path)
        records.append(RedactedFileRecord(filename=filename))

    save_redaction_map_auto(mapping_path, redaction_map)
    manifest.redacted_files = records
    save_manifest(directory, manifest)
    return manifest


def manifest_public_status(case_path: str | Path, manifest: CaseManifest) -> dict:
    return manifest_safe_summary(case_path, manifest)


def manifest_safe_summary(case_path: str | Path, manifest: CaseManifest) -> dict:
    directory = Path(case_path)
    mapping_path = directory / manifest.mapping_file
    restore = restore_status_summary(directory, manifest)
    latest_restored = None
    if restore.get("restored_filename"):
        latest_restored = {"filename": restore["restored_filename"]}
    return {
        "case_folder": manifest.case_folder,
        "discord_thread_url": manifest.discord_thread_url,
        "discord_thread_id": manifest.discord_thread_id,
        "hermes_request_id": manifest.hermes_request_id,
        "hermes_requested_at": manifest.hermes_requested_at,
        "workflow_state": case_workflow_state(manifest=manifest),
        "redacted_file_count": len(manifest.redacted_files),
        "mapping_present": mapping_path.exists(),
        "latest_restored": latest_restored,
        "restore": restore,
    }


def case_workflow_state(
    *,
    saved_local: bool = False,
    manifest: CaseManifest | None = None,
    discord_thread_url: str = "",
    hermes_requested: bool = False,
    attach_status: str = "",
    attach_error: str | None = None,
) -> str:
    if attach_error or attach_status == "failed":
        return "attach_failed"
    if attach_status == "sent":
        return "sent_discord"
    if manifest and manifest.discord_thread_url:
        return "bound_thread"
    if discord_thread_url.strip():
        return "bound_thread"
    if hermes_requested or (manifest and manifest.hermes_request_id):
        return "waiting_hermes"
    if saved_local or manifest is not None:
        return "saved_local"
    return "not_saved"


def case_workflow_public(
    *,
    case_root: str | Path | None = None,
    case_folder: str = "",
    discord_thread_url: str = "",
    saved_local: bool = False,
    hermes_requested: bool = False,
    attach_status: str = "",
    attach_error: str | None = None,
) -> dict:
    manifest = None
    manifest_summary = None
    root_value = str(case_root or "").strip()
    folder_value = case_folder.strip()
    if root_value and folder_value:
        try:
            path = case_dir(root_value, folder_value)
            if (path / MANIFEST_FILENAME).exists():
                manifest = load_manifest(path)
                manifest_summary = manifest_safe_summary(path, manifest)
        except Exception:
            manifest = None
    state = case_workflow_state(
        saved_local=saved_local,
        manifest=manifest,
        discord_thread_url=discord_thread_url,
        hermes_requested=hermes_requested,
        attach_status=attach_status,
        attach_error=attach_error,
    )
    return {
        "workflow_state": state,
        "case_folder": folder_value,
        "discord_thread_url": discord_thread_url.strip() or (manifest.discord_thread_url if manifest else ""),
        "discord_thread_id": (manifest.discord_thread_id if manifest else ""),
        "manifest": manifest_summary,
        "message": workflow_state_message(state, attach_error=attach_error),
    }


def workflow_state_message(state: str, *, attach_error: str | None = None) -> str:
    if state not in CASE_WORKFLOW_STATES:
        state = "not_saved"
    if state == "not_saved":
        return "尚未保存到案件库"
    if state == "saved_local":
        return "已保存到本地案件库"
    if state == "bound_thread":
        return "已绑定 Discord 帖子"
    if state == "sent_discord":
        return "已发送脱敏附件到 Discord"
    if state == "waiting_hermes":
        return "正在等待 Hermes 建帖并写回链接"
    if state == "attach_failed":
        return f"附件发送失败：{attach_error}" if attach_error else "附件发送失败"
    return "尚未保存到案件库"


def suggest_case_location_from_filenames(
    filenames: list[str],
    search_roots: list[Path] | None = None,
    *,
    source_dir: str = "",
    discord_thread_url: str = "",
) -> dict[str, object]:
    source_value = source_dir.strip()
    if source_value:
        return suggest_case_location_from_source_dir(source_value, discord_thread_url=discord_thread_url)

    wanted = {Path(str(name)).name for name in filenames if str(name).strip()}
    wanted = {name for name in wanted if name and not name.startswith("._")}
    if not wanted:
        return {"status": "no_filename", "workflow_state": "not_saved"}

    roots = search_roots or case_location_search_roots()
    matches: list[tuple[Path, Path]] = []
    for root in roots:
        for path in find_matching_case_files(root, wanted):
            matches.append((path, case_dir_for_matched_file(root, path)))
        best_case_dir, ambiguous_dirs = best_case_location(matches, wanted)
        if best_case_dir is not None or ambiguous_dirs:
            break

    best_case_dir, ambiguous_dirs = best_case_location(matches, wanted)
    if ambiguous_dirs:
        return {
            "status": "ambiguous",
            "workflow_state": "not_saved",
            "confidence": 0.0,
            "matches": [str(path) for path in ambiguous_dirs[:8]],
            "candidates": [_case_candidate_summary(path, matches, wanted) for path in ambiguous_dirs[:8]],
            "evidence": [{"kind": "ambiguous_case_directory", "count": len(ambiguous_dirs)}],
        }
    if best_case_dir is None:
        return {"status": "not_found", "workflow_state": "not_saved", "evidence": []}

    result = _case_candidate_summary(best_case_dir, matches, wanted)
    result["status"] = "ok"
    requested_thread = discord_thread_url.strip()
    if requested_thread:
        try:
            binding = case_thread_binding_status(
                result["case_root"],
                result["case_folder"],
                requested_thread,
            )
        except CaseError as exc:
            result.update(
                {
                    "status": "conflict",
                    "conflict": True,
                    "conflict_code": getattr(exc, "code", "case_error"),
                    "conflict_message": str(exc),
                }
            )
        else:
            if binding.get("conflict"):
                result.update(
                    {
                        "status": "conflict",
                        "conflict": True,
                        "conflict_code": binding.get("code"),
                        "conflict_message": binding.get("message"),
                    }
                )
    return result


def suggest_case_location_from_source_dir(
    source_dir: str,
    *,
    discord_thread_url: str = "",
) -> dict[str, object]:
    source_path = Path(source_dir).expanduser()
    case_path = source_path
    if source_path.is_file():
        case_path = source_path.parent
    result = {
        "status": "ok",
        "case_folder": case_path.name,
        "case_root": str(case_path.parent),
        "matched_dir": str(case_path),
        "confidence": 0.95,
        "evidence": [{"kind": "source_dir", "matched_dir": str(case_path)}],
    }
    evidence = list(result["evidence"])
    manifest_data = manifest_fields_for_case_dir(case_path)
    result.update(manifest_data)
    result["evidence"] = evidence + list(manifest_data.get("evidence", []))
    if discord_thread_url.strip():
        try:
            binding = case_thread_binding_status(result["case_root"], result["case_folder"], discord_thread_url)
        except CaseError as exc:
            result.update(
                {
                    "status": "conflict",
                    "conflict": True,
                    "conflict_code": getattr(exc, "code", "case_error"),
                    "conflict_message": str(exc),
                }
            )
        else:
            if binding.get("conflict"):
                result.update(
                    {
                        "status": "conflict",
                        "conflict": True,
                        "conflict_code": binding.get("code"),
                        "conflict_message": binding.get("message"),
                    }
                )
    result.setdefault("workflow_state", case_workflow_state(discord_thread_url=str(result.get("discord_thread_url", ""))))
    return result


def _case_candidate_summary(case_dir_path: Path, matches: list[tuple[Path, Path]], wanted: set[str]) -> dict[str, object]:
    resolved = case_dir_path.resolve()
    matched_files = sorted(
        {
            path.name
            for path, candidate in matches
            if candidate.resolve() == resolved
        }
    )
    confidence = round(len(matched_files) / max(len(wanted), 1), 2)
    result: dict[str, object] = {
        "case_folder": resolved.name,
        "case_root": str(resolved.parent),
        "matched_dir": str(resolved),
        "confidence": confidence,
        "ambiguous": False,
        "conflict": False,
        "evidence": [
            {"kind": "filename_match", "filename": filename}
            for filename in matched_files
        ],
    }
    evidence = list(result["evidence"])
    manifest_data = manifest_fields_for_case_dir(resolved)
    result.update(manifest_data)
    result["evidence"] = evidence + list(manifest_data.get("evidence", []))
    result.setdefault("workflow_state", case_workflow_state(discord_thread_url=str(result.get("discord_thread_url", ""))))
    return result


def manifest_fields_for_case_dir(case_dir_path: Path) -> dict[str, object]:
    try:
        manifest = load_manifest(case_dir_path)
    except FileNotFoundError:
        return {
            "workflow_state": "saved_local" if case_dir_path.exists() else "not_saved",
            "manifest": None,
        }
    except Exception as exc:
        return {
            "workflow_state": "saved_local" if case_dir_path.exists() else "not_saved",
            "manifest": {"status": "error", "message": str(exc)},
        }
    summary = manifest_safe_summary(case_dir_path, manifest)
    return {
        "discord_thread_url": manifest.discord_thread_url,
        "discord_thread_id": manifest.discord_thread_id,
        "workflow_state": summary["workflow_state"],
        "manifest": summary,
        "evidence": [
            {"kind": "manifest", "discord_thread_url_present": bool(manifest.discord_thread_url)}
        ],
    }


def case_location_search_roots() -> list[Path]:
    candidates: list[Path] = [
        default_case_root(),
        Path("~/Documents").expanduser(),
        Path("~/Downloads").expanduser(),
        Path("~/Desktop").expanduser(),
    ]
    volumes = Path("/Volumes")
    if volumes.exists():
        for volume in volumes.iterdir():
            if volume.name.startswith("."):
                continue
            candidates.append(volume)
            case_materials = volume / "案件资料"
            if case_materials.exists():
                candidates.insert(0, case_materials)

    seen: set[Path] = set()
    roots: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved.exists() and resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)
    return roots


def find_matching_case_files(root: Path, wanted: set[str], *, max_depth: int = 5, max_entries: int = 30000) -> list[Path]:
    matches: list[Path] = []
    root = root.resolve()
    visited = 0
    for current, dirs, files in os.walk(root):
        visited += len(dirs) + len(files)
        if visited > max_entries:
            break
        current_path = Path(current)
        depth = len(current_path.relative_to(root).parts)
        dirs[:] = [
            item
            for item in dirs
            if not item.startswith(".")
            and item not in {"__pycache__", ".git", ".venv", ".ff-state", "node_modules"}
        ]
        if depth >= max_depth:
            dirs[:] = []
        for filename in files:
            if filename in wanted:
                matches.append(current_path / filename)
    return matches


def best_case_location(
    matches: list[tuple[Path, Path]],
    wanted: set[str],
) -> tuple[Path | None, list[Path]]:
    if not matches:
        return None, []

    scores: dict[Path, set[str]] = {}
    for file_path, case_dir_path in matches:
        scores.setdefault(case_dir_path.resolve(), set()).add(file_path.name)
    ranked = sorted(scores.items(), key=lambda item: (-len(item[1]), str(item[0])))
    if not ranked:
        return None, []

    best_count = len(ranked[0][1])
    best_dirs = [path for path, names in ranked if len(names) == best_count]
    if len(best_dirs) == 1:
        return best_dirs[0], []
    return None, best_dirs


def case_dir_for_matched_file(root: Path, path: Path) -> Path:
    root = root.resolve()
    path = path.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError:
        return path.parent.resolve()
    if looks_like_case_root(root) and len(relative.parts) > 1:
        return (root / relative.parts[0]).resolve()
    return path.parent.resolve()


def looks_like_case_root(root: Path) -> bool:
    try:
        if root.resolve() == default_case_root().resolve():
            return True
    except OSError:
        pass
    return root.name in {"案件资料", "legal-redactor-cases"}


def _redacted_filename(*, index: int, multiple_documents: bool, document: RedactedDocument) -> str:
    extension = "xlsx" if document.output_bytes is not None else "txt"
    if multiple_documents:
        return f"document-{index}.redacted.{extension}"
    return f"redacted.{extension}"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _collect_remote_payload_issues(value: object, path: str, issues: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            item_path = f"{path}.{key_text}"
            if key_text in REMOTE_FORBIDDEN_KEYS:
                issues.append(f"forbidden key {item_path}")
            if isinstance(item, str):
                path_issue = _remote_path_issue(key_text, item)
                if path_issue:
                    issues.append(f"forbidden path at {item_path}: {path_issue}")
            _collect_remote_payload_issues(item, item_path, issues)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _collect_remote_payload_issues(item, f"{path}[{index}]", issues)
    elif isinstance(value, str):
        for pattern in REMOTE_FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(value):
                issues.append(f"forbidden value at {path}")
                break


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _nullable_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nullable_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _safe_filename(value: object) -> str | None:
    text = _nullable_str(value)
    if text is None:
        return None
    return Path(text).name


def _latest_restored_file(restored_dir: Path) -> Path | None:
    if not restored_dir.exists():
        return None
    files = sorted(
        (
            path
            for path in restored_dir.iterdir()
            if path.is_file() and path.name != LAST_RESTORE_METADATA_FILENAME
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None
