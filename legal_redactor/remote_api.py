from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .cases import (
    CaseError,
    CaseNotFoundError,
    CaseManifest,
    DuplicateDiscordThreadError,
    InvalidDiscordThreadError,
    MissingMapError,
    assert_remote_payload_safe,
    case_location_search_roots,
    case_dir,
    case_root_from_source_dir,
    create_or_update_manifest,
    default_case_root,
    find_case_by_discord_thread,
    load_manifest,
    manifest_public_status,
    parse_discord_thread_id,
    restore_status_summary,
    sanitize_case_relative_path,
    write_last_restore_metadata,
)
from .io import load_redaction_map_auto
from .local_config import config_value, load_json_config
from .restore import restore_text

try:
    from fastapi import Depends, FastAPI, Header, HTTPException
    from pydantic import BaseModel
except ImportError as exc:
    raise RuntimeError("启动远程 API 需要先安装依赖：pip install -r requirements.txt") from exc


PLACEHOLDER_RE = re.compile(r"【[^】]{1,80}】")

app = FastAPI(title="legal-redactor Office restore API", version="0.2.1")


class RestoreTextRequest(BaseModel):
    draft_text: str


class BindDiscordThreadRequest(BaseModel):
    case_folder: str
    discord_thread_url: str
    source_dir: str | None = None
    case_root: str | None = None


def get_case_root() -> Path:
    config = load_json_config("LEGAL_REDACTOR_API_CONFIG", "api.local.json")
    configured = config_value(config, "case_root")
    return Path(configured).expanduser() if configured else default_case_root()


def require_api_token(authorization: str | None = Header(default=None)) -> None:
    config = load_json_config("LEGAL_REDACTOR_API_CONFIG", "api.local.json")
    expected = os.environ.get("LEGAL_REDACTOR_API_TOKEN") or config_value(config, "api_token")
    if not expected:
        raise HTTPException(status_code=500, detail=_error_detail("missing_server_token", 500, "Office API token is not configured", "configure_office_api_token"))
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail=_error_detail("unauthorized", 401, "Unauthorized", "check_api_token"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/cases/by-discord-thread/{thread_id}")
def case_status_by_thread(thread_id: str, _: None = Depends(require_api_token)) -> dict:
    try:
        case_path, manifest = find_case_by_thread(thread_id)
    except CaseError as exc:
        raise _http_error(exc) from exc
    return _remote_status_response(case_path, manifest)


@app.post("/cases/bind-discord-thread")
def bind_discord_thread(
    payload: BindDiscordThreadRequest,
    _: None = Depends(require_api_token),
) -> dict:
    try:
        return bind_discord_thread_to_case(
            get_case_root(),
            payload.case_folder,
            payload.discord_thread_url,
            source_dir=payload.source_dir,
            case_root_override=payload.case_root,
        )
    except CaseError as exc:
        raise _http_error(exc) from exc


@app.post("/cases/by-discord-thread/{thread_id}/restore-text")
def restore_text_by_thread(
    thread_id: str,
    payload: RestoreTextRequest,
    _: None = Depends(require_api_token),
) -> dict:
    try:
        case_path, manifest = find_case_by_thread(thread_id)
        return restore_text_for_case(case_path, manifest, payload.draft_text)
    except CaseError as exc:
        raise _http_error(exc) from exc


def restore_text_for_thread(case_root: str | Path, thread_id: str, draft_text: str) -> dict:
    case_path, manifest = find_case_by_discord_thread(case_root, thread_id)
    return restore_text_for_case(case_path, manifest, draft_text)


def restore_text_for_case(case_path: str | Path, manifest: CaseManifest, draft_text: str) -> dict:
    case_path = Path(case_path)
    mapping_path = case_path / manifest.mapping_file
    if not mapping_path.exists():
        raise MissingMapError("案件映射表不存在")

    requested_at = _utc_now_iso()
    redaction_map = load_redaction_map_auto(mapping_path)
    restored_text = restore_text(draft_text, redaction_map)
    unresolved = find_unresolved_placeholders(restored_text, redaction_map)

    restored_dir = case_path / manifest.restored_dir
    restored_dir.mkdir(parents=True, exist_ok=True)
    output_path = _next_restore_path(restored_dir, "judgment.restored", ".txt")
    output_path.write_text(restored_text, encoding="utf-8")

    replacement_count = sum(1 for entry in redaction_map.mappings if entry.masked and entry.masked in draft_text)
    completed_at = _utc_now_iso()
    duration_ms = _duration_ms(requested_at, completed_at)
    metadata = write_last_restore_metadata(
        case_path,
        manifest,
        {
            "status": "restored",
            "restored_filename": output_path.name,
            "restored_relative_path": sanitize_case_relative_path(case_path, output_path),
            "replacement_count": replacement_count,
            "unresolved_placeholder_count": len(unresolved),
            "requested_at": requested_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "timing_reason": None,
            "metadata_status": "written",
        },
    )
    response = _remote_status_response(
        case_path,
        manifest,
        restore_override=metadata,
        code_override="restored",
        next_action_override="open_office_restored_file",
    )
    assert_remote_payload_safe(response)
    return response


def bind_discord_thread_to_case(
    case_root: str | Path,
    case_folder: str,
    discord_thread_url: str,
    *,
    source_dir: str | None = None,
    case_root_override: str | Path | None = None,
) -> dict:
    effective_case_root = _case_root_for_bind(
        case_root,
        case_folder,
        source_dir=source_dir,
        case_root_override=case_root_override,
    )
    _ensure_thread_bind_can_write(effective_case_root, case_folder, discord_thread_url)
    manifest = create_or_update_manifest(
        effective_case_root,
        case_folder,
        discord_thread_url,
        source_dir=source_dir,
    )
    case_path, manifest = find_case_by_discord_thread(effective_case_root, manifest.discord_thread_id)
    response = {"ok": True, **manifest_public_status(case_path, manifest)}
    assert_remote_payload_safe(response)
    return response


def find_case_by_thread(thread_id: str) -> tuple[Path, CaseManifest]:
    matches: dict[Path, CaseManifest] = {}
    for root in _bind_case_root_candidates(get_case_root()):
        for case_path, manifest in _find_case_matches_by_thread(root, thread_id):
            matches[case_path.resolve()] = manifest
    if not matches:
        raise CaseNotFoundError("未找到绑定该 Discord 帖子的案件")
    selected = _select_best_thread_match(matches)
    if selected is None:
        raise DuplicateDiscordThreadError("多个案件绑定了同一个 Discord 帖子")
    return selected


def _find_case_matches_by_thread(
    root: str | Path,
    thread_id: str,
    *,
    max_depth: int = 5,
    max_entries: int = 50000,
) -> list[tuple[Path, CaseManifest]]:
    root_path = Path(root).expanduser()
    if not root_path.exists():
        return []
    matches: list[tuple[Path, CaseManifest]] = []
    visited = 0
    for current, dirs, files in os.walk(root_path):
        visited += len(dirs) + len(files)
        if visited > max_entries:
            break
        current_path = Path(current)
        try:
            depth = len(current_path.resolve().relative_to(root_path.resolve()).parts)
        except (OSError, ValueError):
            depth = 0
        dirs[:] = [
            item
            for item in dirs
            if not item.startswith(".")
            and item not in {"__pycache__", ".git", ".venv", ".ff-state", "node_modules"}
        ]
        if depth >= max_depth:
            dirs[:] = []
        if "manifest.json" not in files:
            continue
        try:
            manifest = load_manifest(current_path)
        except Exception:
            continue
        if manifest.discord_thread_id == str(thread_id):
            matches.append((current_path, manifest))
    return matches


def _select_best_thread_match(matches: dict[Path, CaseManifest]) -> tuple[Path, CaseManifest] | None:
    if len(matches) == 1:
        return next(iter(matches.items()))

    with_mapping = [
        (path, manifest)
        for path, manifest in matches.items()
        if (path / manifest.mapping_file).exists()
    ]
    if len(with_mapping) == 1:
        return with_mapping[0]
    if len(with_mapping) > 1:
        return None

    with_case_artifacts = [
        (path, manifest)
        for path, manifest in matches.items()
        if (path / manifest.redacted_dir).exists() or (path / manifest.restored_dir).exists()
    ]
    if len(with_case_artifacts) == 1:
        return with_case_artifacts[0]
    if len(with_case_artifacts) > 1:
        return None

    return None


def _case_root_for_bind(
    configured_case_root: str | Path,
    case_folder: str,
    *,
    source_dir: str | None = None,
    case_root_override: str | Path | None = None,
) -> Path:
    source_root = case_root_from_source_dir(source_dir, case_folder)
    if source_root is not None:
        return source_root

    configured = Path(configured_case_root).expanduser()
    override_root = Path(case_root_override).expanduser() if case_root_override and str(case_root_override).strip() else None
    candidates = _bind_case_root_candidates(configured)
    if override_root is not None and override_root.exists():
        candidates = [override_root, *candidates]

    existing = [
        candidate
        for candidate in candidates
        if (candidate / case_folder.strip()).exists()
    ]
    if existing:
        return max(existing, key=lambda candidate: _case_directory_score(candidate / case_folder.strip()))
    if override_root is not None and override_root.exists():
        return override_root
    return configured


def _ensure_thread_bind_can_write(
    effective_case_root: str | Path,
    case_folder: str,
    discord_thread_url: str,
) -> None:
    requested_url = discord_thread_url.strip()
    if not requested_url:
        return
    thread_id = parse_discord_thread_id(requested_url)
    target_case_path = case_dir(effective_case_root, case_folder).resolve()
    for root in _bind_case_root_candidates(Path(effective_case_root).expanduser()):
        for bound_case_path, _ in _find_case_matches_by_thread(root, thread_id):
            if bound_case_path.resolve() != target_case_path:
                raise DuplicateDiscordThreadError("该 Discord 帖子已绑定到其他案件")


def _bind_case_root_candidates(configured_case_root: Path) -> list[Path]:
    candidates: list[Path] = [
        configured_case_root,
        default_case_root(),
        Path("~/Documents/legal-redactor-cases").expanduser(),
    ]
    candidates.extend(case_location_search_roots())
    volumes = Path("/Volumes")
    if volumes.exists():
        for volume in volumes.iterdir():
            if volume.name.startswith("."):
                continue
            candidates.append(volume)
            case_materials = volume / "案件资料"
            if case_materials.exists():
                candidates.append(case_materials)
    roots: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)
    return roots


def _case_directory_score(case_path: Path) -> int:
    score = 0
    if case_path.exists():
        score += 1
    manifest_path = case_path / "manifest.json"
    if manifest_path.exists():
        score += 2
        try:
            manifest = load_manifest(case_path)
        except Exception:
            manifest = None
        if manifest is not None:
            if (case_path / manifest.mapping_file).exists():
                score += 16
            if (case_path / manifest.redacted_dir).exists():
                score += 4
            if (case_path / manifest.restored_dir).exists():
                score += 2
    elif (case_path / "mapping" / "redaction_map.enc").exists():
        score += 16
    return score


def find_unresolved_placeholders(text: str, redaction_map) -> list[str]:
    known = {entry.masked for entry in redaction_map.mappings if entry.masked}
    unresolved = {masked for masked in known if masked in text}
    for match in PLACEHOLDER_RE.findall(text):
        if match not in known:
            unresolved.add(match)
    return sorted(unresolved)


def _next_restore_path(directory: Path, stem: str, suffix: str) -> Path:
    from datetime import datetime

    base = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    candidate = directory / f"{stem}.{base}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}.{base}.{counter}{suffix}"
        counter += 1
    return candidate


def _http_error(exc: CaseError) -> HTTPException:
    code, status, next_action = _case_error_contract(exc)
    return HTTPException(
        status_code=status,
        detail=_error_detail(code, status, _safe_case_error_message(exc), next_action),
    )


def _remote_status_response(
    case_path: str | Path,
    manifest: CaseManifest,
    *,
    restore_override: dict | None = None,
    code_override: str | None = None,
    next_action_override: str | None = None,
) -> dict:
    restore = restore_override or restore_status_summary(case_path, manifest)
    case = {
        "case_folder": manifest.case_folder,
        "discord_thread_id": manifest.discord_thread_id or None,
        "discord_thread_url": manifest.discord_thread_url or None,
        "workflow_state": manifest_public_status(case_path, manifest)["workflow_state"],
        "redacted_file_count": len(manifest.redacted_files),
        "mapping_present": (Path(case_path) / manifest.mapping_file).exists(),
    }
    code = code_override or _status_code_for_restore(case, restore)
    response = {
        "ok": True,
        "code": code,
        "case": case,
        "restore": restore,
        "next_action": next_action_override or _next_action_for_code(code, restore),
    }
    assert_remote_payload_safe(response)
    return response


def _status_code_for_restore(case: dict, restore: dict) -> str:
    if not case.get("mapping_present"):
        return "missing_map"
    status = str(restore.get("status") or "")
    if status == "restore_failed":
        return "restore_failed"
    if status in {"restored", "metadata_unknown"}:
        return "restored"
    if status == "no_restore_yet":
        return "no_restore_yet"
    return "ready"


def _next_action_for_code(code: str, restore: dict | None = None) -> str:
    return {
        "ready": "restore_ready",
        "missing_map": "upload_mapping",
        "no_restore_yet": "restore_ready",
        "restored": "open_office_restored_file",
        "restore_failed": "retry_restore",
        "missing_manifest": "check_case_manifest",
        "unbound_thread": "bind_discord_thread",
        "duplicate_thread": "resolve_duplicate_thread_binding",
        "invalid_request": "check_request",
        "unauthorized": "check_api_token",
        "missing_server_token": "configure_office_api_token",
    }.get(code, "check_office_api")


def _case_error_contract(exc: CaseError) -> tuple[str, int, str]:
    if isinstance(exc, MissingMapError):
        return "missing_map", 409, "upload_mapping"
    if isinstance(exc, DuplicateDiscordThreadError):
        return "duplicate_thread", 409, "resolve_duplicate_thread_binding"
    if isinstance(exc, InvalidDiscordThreadError):
        return "invalid_request", 400, "check_request"
    if isinstance(exc, CaseNotFoundError):
        message = str(exc)
        if "根目录" in message or "manifest" in message:
            return "missing_manifest", 404, "check_case_manifest"
        return "unbound_thread", 404, "bind_discord_thread"
    return "invalid_request", 400, "check_request"


def _error_detail(code: str, status: int, message: str, next_action: str) -> dict:
    detail = {
        "ok": False,
        "error": {
            "code": code,
            "status": status,
            "message": message,
            "next_action": next_action,
        },
    }
    assert_remote_payload_safe(detail)
    return detail


def _safe_case_error_message(exc: CaseError) -> str:
    if isinstance(exc, DuplicateDiscordThreadError):
        return "多个案件绑定了同一个 Discord 帖子"
    return str(exc)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_ms(start: str, end: str) -> int:
    started = datetime.fromisoformat(start)
    ended = datetime.fromisoformat(end)
    return max(0, int((ended - started).total_seconds() * 1000))
