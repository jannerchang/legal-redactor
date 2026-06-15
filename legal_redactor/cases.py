from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .io import save_redaction_map_auto
from .models import RedactedDocument, RedactionMap


MANIFEST_FILENAME = "manifest.json"
DEFAULT_CASES_DIR = "~/Documents/legal-redactor-cases"
DISCORD_THREAD_RE = re.compile(r"^https://(?:canary\.|ptb\.)?discord(?:app)?\.com/channels/\d+/\d+(?:/\d+)?")


class CaseError(ValueError):
    code = "case_error"


class InvalidCaseFolderError(CaseError):
    code = "invalid_case_folder"


class InvalidDiscordThreadError(CaseError):
    code = "invalid_discord_thread"


class CaseNotFoundError(CaseError):
    code = "case_not_found"


class DuplicateDiscordThreadError(CaseError):
    code = "duplicate_discord_thread"


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


def create_or_update_manifest(
    case_root: str | Path,
    case_folder: str,
    discord_thread_url: str,
    *,
    source_dir: str | None = None,
    redacted_files: list[RedactedFileRecord] | None = None,
) -> CaseManifest:
    thread_id = parse_discord_thread_id(discord_thread_url)
    case_path = case_dir(case_root, case_folder)
    existing = case_path / MANIFEST_FILENAME
    if existing.exists():
        manifest = load_manifest(existing)
        if manifest.discord_thread_id and manifest.discord_thread_id != thread_id:
            raise InvalidDiscordThreadError("已有案件绑定了不同的 Discord 帖子")
        manifest.discord_thread_url = discord_thread_url.strip()
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
            discord_thread_url=discord_thread_url.strip(),
            discord_thread_id=thread_id,
            redacted_files=redacted_files or [],
        )
    save_manifest(case_path, manifest)
    return manifest


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
        filename = _redacted_filename(index=index, multiple_documents=multiple_documents)
        output_path = redacted_dir / filename
        output_path.write_text(document.redacted_text, encoding="utf-8")
        records.append(RedactedFileRecord(filename=filename))

    save_redaction_map_auto(mapping_path, redaction_map)
    manifest.redacted_files = records
    save_manifest(directory, manifest)
    return manifest


def manifest_public_status(case_path: str | Path, manifest: CaseManifest) -> dict:
    directory = Path(case_path)
    mapping_path = directory / manifest.mapping_file
    restored_dir = directory / manifest.restored_dir
    latest_restored = None
    if restored_dir.exists():
        files = sorted((p for p in restored_dir.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            latest_restored = {"filename": files[0].name, "path": str(files[0])}
    return {
        "case_folder": manifest.case_folder,
        "discord_thread_id": manifest.discord_thread_id,
        "redacted_file_count": len(manifest.redacted_files),
        "mapping_present": mapping_path.exists(),
        "latest_restored": latest_restored,
    }


def _redacted_filename(*, index: int, multiple_documents: bool) -> str:
    if multiple_documents:
        return f"document-{index}.redacted.txt"
    return "redacted.txt"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
