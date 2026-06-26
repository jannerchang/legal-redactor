from __future__ import annotations

import os
import re
from pathlib import Path

from .cases import (
    CaseError,
    CaseNotFoundError,
    CaseManifest,
    create_or_update_manifest,
    default_case_root,
    find_case_by_discord_thread,
    manifest_public_status,
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

app = FastAPI(title="legal-redactor Office restore API", version="0.1.0")


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
        raise HTTPException(status_code=500, detail={"code": "missing_server_token"})
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail={"code": "unauthorized"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/cases/by-discord-thread/{thread_id}")
def case_status_by_thread(thread_id: str, _: None = Depends(require_api_token)) -> dict:
    try:
        case_path, manifest = find_case_by_thread(thread_id)
    except CaseError as exc:
        raise _http_error(exc) from exc
    return {"ok": True, **manifest_public_status(case_path, manifest)}


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
        raise CaseNotFoundError("案件映射表不存在")

    redaction_map = load_redaction_map_auto(mapping_path)
    restored_text = restore_text(draft_text, redaction_map)
    unresolved = find_unresolved_placeholders(restored_text, redaction_map)

    restored_dir = case_path / manifest.restored_dir
    restored_dir.mkdir(parents=True, exist_ok=True)
    output_path = _next_restore_path(restored_dir, "judgment.restored", ".txt")
    output_path.write_text(restored_text, encoding="utf-8")

    replacement_count = sum(1 for entry in redaction_map.mappings if entry.masked and entry.masked in draft_text)
    return {
        "ok": True,
        "case_folder": manifest.case_folder,
        "restored_file": str(output_path),
        "unresolved_placeholders": unresolved,
        "replacement_count": replacement_count,
    }


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
    manifest = create_or_update_manifest(
        effective_case_root,
        case_folder,
        discord_thread_url,
        source_dir=source_dir,
    )
    case_path, manifest = find_case_by_discord_thread(effective_case_root, manifest.discord_thread_id)
    return {"ok": True, **manifest_public_status(case_path, manifest)}


def find_case_by_thread(thread_id: str) -> tuple[Path, CaseManifest]:
    matches: dict[Path, CaseManifest] = {}
    for root in _bind_case_root_candidates(get_case_root()):
        try:
            case_path, manifest = find_case_by_discord_thread(root, thread_id)
        except CaseNotFoundError:
            continue
        matches[case_path.resolve()] = manifest
    if not matches:
        raise CaseNotFoundError("未找到绑定该 Discord 帖子的案件")
    return max(matches.items(), key=lambda item: item[1].updated_at or "")


def _case_root_for_bind(
    configured_case_root: str | Path,
    case_folder: str,
    *,
    source_dir: str | None = None,
    case_root_override: str | Path | None = None,
) -> Path:
    if case_root_override and str(case_root_override).strip():
        return Path(case_root_override).expanduser()

    source_value = (source_dir or "").strip()
    if source_value:
        source_path = Path(source_value).expanduser()
        if source_path.exists():
            if source_path.name == case_folder.strip():
                return source_path.parent
            if (source_path / case_folder.strip()).exists():
                return source_path

    configured = Path(configured_case_root).expanduser()
    for candidate in _bind_case_root_candidates(configured):
        if (candidate / case_folder.strip()).exists():
            return candidate
    return configured


def _bind_case_root_candidates(configured_case_root: Path) -> list[Path]:
    candidates: list[Path] = [
        configured_case_root,
        default_case_root(),
        Path("~/Documents/legal-redactor-cases").expanduser(),
    ]
    volumes = Path("/Volumes")
    if volumes.exists():
        for volume in volumes.iterdir():
            if volume.name.startswith("."):
                continue
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
    status = 404 if isinstance(exc, CaseNotFoundError) else 400
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})
