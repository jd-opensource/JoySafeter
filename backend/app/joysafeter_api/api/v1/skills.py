import posixpath
import re
import zipfile
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill, JoySafeterSkillUsageLog
from app.joysafeter_domain.schemas.base import CursorPaginatedResponse as PaginatedResponse
from app.joysafeter_domain.schemas.joysafeter_skill import (
    CreateSkillFileRequest,
    CreateSkillRequest,
    CreateSkillVersionRequest,
    SkillFileResponse,
    SkillLifecycleTransitionResponse,
    SkillResponse,
    SkillSecurityScanResponse,
    SkillUsageResponse,
    SkillVersionFileResponse,
    SkillVersionResponse,
    UpdateSkillFileRequest,
    UpdateSkillRequest,
)
from app.joysafeter_domain.services.joysafeter_skill_service import (
    SkillLifecycleService,
    SkillPromotionService,
    SkillService,
    SkillVersionService,
)
from app.joysafeter_shared.common.app_errors import (
    AccessDeniedError,
    InvalidRequestError,
    NotFoundError,
)
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    JoySafeterRole,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.config.settings import settings
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.ids import (
    SkillFileId,
    SkillId,
    SkillSecurityScanId,
    SkillUsageId,
    SkillVersionId,
)
from app.joysafeter_shared.skill.yaml_parser import extract_metadata_from_frontmatter, parse_skill_md

router = APIRouter(tags=["joysafeter-skills"])


class SkillListResponse(PaginatedResponse[SkillResponse, SkillId]):
    pass


class SkillSecurityScanListResponse(PaginatedResponse[SkillSecurityScanResponse, SkillSecurityScanId]):
    pass


class SkillFileListResponse(BaseModel):
    data: list[SkillFileResponse]


class SkillVersionListResponse(PaginatedResponse[SkillVersionResponse, SkillVersionId]):
    pass


class SkillVersionFileListResponse(BaseModel):
    data: list[SkillVersionFileResponse]


class SkillDeleteResponse(BaseModel):
    id: SkillId
    type: Literal["skill_deleted"] = "skill_deleted"


class SkillFileDeleteResponse(BaseModel):
    id: SkillFileId
    type: Literal["skill_file_deleted"] = "skill_file_deleted"


class SkillVersionDeleteResponse(BaseModel):
    type: Literal["skill_version_deleted"] = "skill_version_deleted"


class SkillBatchRescanResponse(BaseModel):
    scheduled: list[SkillId]
    count: int
    limit: int
    truncated: bool


# Skill ZIP import limits — runtime values pulled from settings via accessors so
# env-driven overrides take effect without a restart of any caller module.
# Defaults / overrides live in `joysafeter_shared.config.settings.Settings`:
#   SKILL_IMPORT_MAX_ZIP_BYTES, SKILL_IMPORT_MAX_FILES,
#   SKILL_IMPORT_MAX_FILE_BYTES, SKILL_IMPORT_MAX_TOTAL_FILE_BYTES
def _max_import_zip_bytes() -> int:
    return settings.skill_import_max_zip_bytes


def _max_import_files() -> int:
    return settings.skill_import_max_files


def _max_import_file_bytes() -> int:
    return settings.skill_import_max_file_bytes


def _max_import_total_file_bytes() -> int:
    return settings.skill_import_max_total_file_bytes


ZIP_IMPORT_DIAGNOSTIC_SAMPLE_SIZE = 8
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _validate_sha256_hex(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not _SHA256_HEX_RE.fullmatch(normalized):
        raise InvalidRequestError(
            code="SKILL_USAGE_HASH_INVALID",
            message=f"{field} must be a SHA-256 hex digest.",
            data={"field": field},
            user_action="fix_input",
        )
    return normalized


FILE_TYPE_BY_EXT = {
    ".md": "markdown",
    ".txt": "text",
    ".rst": "text",
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".html": "html",
    ".css": "css",
    ".scss": "css",
    ".toml": "toml",
    ".xml": "xml",
    ".svg": "xml",
}

ZIP_SYSTEM_FILE_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}


def _flush_async_scans(svc: SkillService, background_tasks: BackgroundTasks) -> None:
    """Forward any deferred security scans to FastAPI's BG queue.

    Called by write endpoints (PUT skill, POST/PUT/DELETE skill file)
    right before they return. The service collected pending scan
    descriptors when ``_dispatch_security_scan`` saw oversized payloads;
    those rows are already marked ``security_status='scanning'`` and
    are waiting for SkillSpector to land a verdict. Spawning the BG
    task here means the actual scan runs AFTER the response goes out
    so the user isn't blocked waiting on it.

    No-op when nothing was deferred — small-skill writes stay synchronous
    end-to-end.
    """
    from app.joysafeter_domain.services.joysafeter_skill_security import (
        run_scan_in_background,
    )

    for descriptor in svc.drain_pending_async_scans():
        background_tasks.add_task(run_scan_in_background, **descriptor)


def _add_zip_diagnostic_sample(values: list[str], value: str) -> None:
    if value and len(values) < ZIP_IMPORT_DIAGNOSTIC_SAMPLE_SIZE:
        values.append(value)


def _is_system_zip_member(raw_parts: list[str]) -> bool:
    if not raw_parts:
        return False
    lower_parts = [part.lower() for part in raw_parts]
    file_name = lower_parts[-1]
    return (
        "__macosx" in lower_parts
        or file_name.startswith("._")
        or file_name in ZIP_SYSTEM_FILE_NAMES
        or any(part == ".ds_store" for part in lower_parts)
    )


def _normalize_zip_member_path(raw_name: str) -> str | None:
    name = raw_name.replace("\\", "/").strip()
    if not name or name.endswith("/"):
        return None
    raw_parts = [part for part in name.split("/") if part]
    if _is_system_zip_member(raw_parts):
        return None
    normalized = posixpath.normpath(name)
    if normalized in {"", "."}:
        return None
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise InvalidRequestError(
            "ZIP contains an unsafe file path",
            code="SKILL_IMPORT_ZIP_PATH_UNSAFE",
            data={"path": raw_name},
        )
    return path.as_posix()


def _strip_common_root(paths: list[str]) -> list[str]:
    if any(path == "SKILL.md" for path in paths):
        return paths
    first_parts = [path.split("/", 1)[0] for path in paths if "/" in path]
    if not first_parts or len(first_parts) != len(paths):
        return paths
    root = first_parts[0]
    if any(part != root for part in first_parts):
        return paths
    return [path.split("/", 1)[1] for path in paths]


def _file_type_for_path(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    return FILE_TYPE_BY_EXT.get(suffix, "text")


def _build_skill_files_from_zip(zip_bytes: bytes) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    max_zip_bytes = _max_import_zip_bytes()
    if len(zip_bytes) > max_zip_bytes:
        raise InvalidRequestError(
            "ZIP file is too large",
            code="SKILL_IMPORT_ZIP_TOO_LARGE",
            data={"max_bytes": max_zip_bytes},
        )

    try:
        archive = zipfile.ZipFile(BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise InvalidRequestError(
            "Invalid ZIP file",
            code="SKILL_IMPORT_ZIP_INVALID",
        ) from exc

    entries: list[tuple[str, zipfile.ZipInfo]] = []
    with archive:
        diagnostics: dict[str, Any] = {
            "total_members": 0,
            "skipped_directories": 0,
            "skipped_system_files": 0,
            "skipped_empty_names": 0,
            "sample_members": [],
            "sample_skipped_system_files": [],
        }
        for info in archive.infolist():
            diagnostics["total_members"] += 1
            raw_name = info.filename or ""
            _add_zip_diagnostic_sample(diagnostics["sample_members"], raw_name)

            normalized_name = raw_name.replace("\\", "/").strip()
            raw_parts = [part for part in normalized_name.split("/") if part]
            if not normalized_name:
                diagnostics["skipped_empty_names"] += 1
            elif normalized_name.endswith("/") or info.is_dir():
                diagnostics["skipped_directories"] += 1
            elif _is_system_zip_member(raw_parts):
                diagnostics["skipped_system_files"] += 1
                _add_zip_diagnostic_sample(diagnostics["sample_skipped_system_files"], raw_name)

            normalized = _normalize_zip_member_path(info.filename)
            if normalized is None:
                continue
            entries.append((normalized, info))

        if not entries:
            raise InvalidRequestError(
                "ZIP does not contain any importable files",
                code="SKILL_IMPORT_ZIP_EMPTY",
                data=diagnostics,
            )
        max_files = _max_import_files()
        if len(entries) > max_files:
            raise InvalidRequestError(
                "ZIP contains too many files",
                code="SKILL_IMPORT_ZIP_TOO_MANY_FILES",
                data={"max_files": max_files},
            )

        max_file_bytes = _max_import_file_bytes()
        max_total_file_bytes = _max_import_total_file_bytes()

        stripped_paths = _strip_common_root([path for path, _ in entries])
        files: list[dict[str, Any]] = []
        total_size = 0
        skill_md_content: str | None = None

        for (original_path, info), relative_path in zip(entries, stripped_paths):
            if not relative_path or relative_path.startswith("../") or "/../" in relative_path:
                raise InvalidRequestError(
                    "ZIP contains an unsafe file path",
                    code="SKILL_IMPORT_ZIP_PATH_UNSAFE",
                    data={"path": original_path},
                )
            if info.file_size > max_file_bytes:
                raise InvalidRequestError(
                    "ZIP contains a file that is too large",
                    code="SKILL_IMPORT_FILE_TOO_LARGE",
                    data={"path": relative_path, "max_bytes": max_file_bytes},
                )

            raw = archive.read(info)

            # Verify actual decompressed size (ZIP headers can lie)
            if len(raw) > max_file_bytes:
                raise InvalidRequestError(
                    "ZIP contains a file that is too large (decompressed)",
                    code="SKILL_IMPORT_FILE_TOO_LARGE",
                    data={"path": relative_path, "max_bytes": max_file_bytes},
                )
            total_size += len(raw)
            if total_size > max_total_file_bytes:
                raise InvalidRequestError(
                    "ZIP uncompressed content is too large",
                    code="SKILL_IMPORT_TOTAL_TOO_LARGE",
                    data={"max_bytes": max_total_file_bytes},
                )
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise InvalidRequestError(
                    "ZIP contains non-text files",
                    code="SKILL_IMPORT_BINARY_FILE",
                    data={"path": relative_path},
                ) from exc

            path_obj = PurePosixPath(relative_path)
            file_name = path_obj.name
            directory = path_obj.parent.as_posix()
            if directory == ".":
                directory = ""
            elif directory:
                directory = f"{directory}/"

            if relative_path == "SKILL.md":
                skill_md_content = content

            files.append(
                {
                    "path": directory,
                    "file_name": file_name,
                    "file_type": _file_type_for_path(relative_path),
                    "content": content,
                    "size": len(content),
                }
            )

    if not skill_md_content:
        raise InvalidRequestError(
            "ZIP must contain SKILL.md at the root or inside a single top-level folder",
            code="SKILL_IMPORT_SKILL_MD_REQUIRED",
            data={"files": [file["path"] + file["file_name"] for file in files[:ZIP_IMPORT_DIAGNOSTIC_SAMPLE_SIZE]]},
        )

    frontmatter, body = parse_skill_md(skill_md_content)
    metadata = extract_metadata_from_frontmatter(frontmatter)
    name = metadata.get("name")
    if not name:
        raise InvalidRequestError(
            "SKILL.md frontmatter must include name",
            code="SKILL_IMPORT_NAME_REQUIRED",
        )
    description = metadata.get("description") or ""

    payload = {
        "name": name,
        "description": description,
        "content": body.strip() if body else "",
        "tags": metadata.get("tags") if isinstance(metadata.get("tags"), list) else [],
        "license": metadata.get("license"),
        "files": files,
    }
    return files, payload, skill_md_content

    # ── Skills CRUD ──────────────────────────────────────────────────────


@router.post("", status_code=201)
async def create_skill(
    req: CreateSkillRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillResponse:
    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    files_data = None
    if req.files:
        files_data = [f if isinstance(f, dict) else f for f in req.files]
    skill = await svc.create_skill(
        created_by_id=auth_ctx.user_id,
        name=req.name,
        description=req.description,
        content=req.content,
        tags=req.tags or None,
        source_type=req.source_type,
        source_url=req.source_url or None,
        license=req.license or None,
        files=files_data,
        project_id=auth_ctx.project_id,
    )
    skill = await svc.get_skill(skill.id, current_user_id=auth_ctx.user_id, project_id=auth_ctx.project_id)
    # Flush any async scan descriptors the service queued. Without
    # this, a skill whose total payload exceeds ``skill_security_async_threshold_bytes``
    # would land with ``security_status='scanning'`` and stay stuck forever.
    _flush_async_scans(svc, background_tasks)
    return SkillResponse.model_validate(skill)


@router.post("/import-zip", status_code=201)
async def import_skill_zip(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillResponse:
    filename = file.filename or ""
    if filename and not filename.lower().endswith(".zip"):
        raise InvalidRequestError(
            "Only ZIP files are supported",
            code="SKILL_IMPORT_ZIP_ONLY",
        )

    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    zip_bytes = await file.read()
    files_data, payload, _skill_md_content = _build_skill_files_from_zip(zip_bytes)
    skill = await svc.create_skill(
        created_by_id=auth_ctx.user_id,
        name=str(payload["name"]),
        description=str(payload.get("description") or ""),
        content=str(payload.get("content") or ""),
        tags=payload.get("tags") or None,
        source_type="zip",
        source_url=filename or None,
        license=payload.get("license") or None,
        files=files_data,
        project_id=auth_ctx.project_id,
    )
    skill = await svc.get_skill(skill.id, current_user_id=auth_ctx.user_id, project_id=auth_ctx.project_id)
    # See ``create_skill``; ZIP imports go through the same service path.
    _flush_async_scans(svc, background_tasks)
    return SkillResponse.model_validate(skill)


@router.get("")
async def list_skills(
    limit: int = Query(10, ge=1, le=100),
    after_id: Optional[SkillId] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SkillListResponse:
    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    skills, has_more = await svc.list_skills(
        current_user_id=auth_ctx.user_id,
        project_id=auth_ctx.project_id,
        limit=limit,
        after_id=after_id,
    )
    data = [SkillResponse.model_validate(s) for s in skills]
    return SkillListResponse(
        data=data,
        has_more=has_more,
        first_id=data[0].id if data else None,
        last_id=data[-1].id if data else None,
    )


@router.get("/security-scans/{scan_id}")
async def get_skill_security_scan(
    scan_id: SkillSecurityScanId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SkillSecurityScanResponse:
    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    scan = await svc.get_security_scan(
        scan_id,
        current_user_id=auth_ctx.user_id,
        project_id=auth_ctx.project_id,
    )
    return SkillSecurityScanResponse.model_validate(scan)


@router.get("/{skill_id}")
async def get_skill(
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SkillResponse:
    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    skill = await svc.get_skill(skill_id, current_user_id=auth_ctx.user_id, project_id=auth_ctx.project_id)
    resp = SkillResponse.model_validate(skill)
    return resp


@router.get("/{skill_id}/security-scans/latest")
async def get_latest_skill_security_scan(
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SkillSecurityScanResponse:
    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    scan = await svc.get_latest_security_scan(
        skill_id,
        current_user_id=auth_ctx.user_id,
        project_id=auth_ctx.project_id,
    )
    return SkillSecurityScanResponse.model_validate(scan)


@router.get("/{skill_id}/security-scans")
async def list_skill_security_scans(
    skill_id: SkillId,
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[SkillSecurityScanId] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SkillSecurityScanListResponse:
    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    scans, has_more = await svc.list_security_scans(
        skill_id,
        current_user_id=auth_ctx.user_id,
        project_id=auth_ctx.project_id,
        limit=limit,
        after_id=after_id,
    )
    data = [SkillSecurityScanResponse.model_validate(scan) for scan in scans]
    return SkillSecurityScanListResponse(
        data=data,
        has_more=has_more,
        first_id=data[0].id if data else None,
        last_id=data[-1].id if data else None,
    )


@router.get("/usage/search")
async def search_skill_usage(
    limit: int = Query(50, ge=1, le=100),
    artifact_hash: Optional[str] = Query(None, min_length=64, max_length=64),
    target_hash: Optional[str] = Query(None, min_length=64, max_length=64),
    security_scan_id: Optional[SkillSecurityScanId] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[SkillUsageResponse, SkillUsageId]:
    artifact_hash = _validate_sha256_hex(artifact_hash, "artifact_hash")
    target_hash = _validate_sha256_hex(target_hash, "target_hash")

    if not any((artifact_hash, target_hash, security_scan_id)):
        raise InvalidRequestError(
            code="SKILL_USAGE_FILTER_REQUIRED",
            message="At least one usage filter is required.",
            data={"filters": ["artifact_hash", "target_hash", "security_scan_id"]},
            user_action="fix_input",
        )

    stmt = select(JoySafeterSkillUsageLog)
    if auth_ctx.project_id is not None:
        stmt = stmt.where(JoySafeterSkillUsageLog.project_id == auth_ctx.project_id)
    if artifact_hash:
        stmt = stmt.where(JoySafeterSkillUsageLog.artifact_hash == artifact_hash)
    if target_hash:
        stmt = stmt.where(JoySafeterSkillUsageLog.target_hash == target_hash)
    if security_scan_id:
        stmt = stmt.where(JoySafeterSkillUsageLog.security_scan_id == security_scan_id)

    stmt = stmt.order_by(JoySafeterSkillUsageLog.created_at.desc(), JoySafeterSkillUsageLog.id.desc()).limit(limit + 1)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    has_more = len(rows) > limit
    data = [SkillUsageResponse.model_validate(row) for row in rows[:limit]]
    return PaginatedResponse[SkillUsageResponse, SkillUsageId](
        data=data,
        has_more=has_more,
        first_id=data[0].id if data else None,
        last_id=data[-1].id if data else None,
    )


@router.get("/{skill_id}/usage")
async def list_skill_usage(
    skill_id: SkillId,
    limit: int = Query(50, ge=1, le=100),
    artifact_hash: Optional[str] = Query(None, min_length=64, max_length=64),
    target_hash: Optional[str] = Query(None, min_length=64, max_length=64),
    security_scan_id: Optional[SkillSecurityScanId] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[SkillUsageResponse, SkillUsageId]:
    artifact_hash = _validate_sha256_hex(artifact_hash, "artifact_hash")
    target_hash = _validate_sha256_hex(target_hash, "target_hash")

    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    await svc.get_skill(skill_id, current_user_id=auth_ctx.user_id, project_id=auth_ctx.project_id)

    stmt = select(JoySafeterSkillUsageLog).where(JoySafeterSkillUsageLog.skill_id == skill_id)
    if auth_ctx.project_id is not None:
        stmt = stmt.where(JoySafeterSkillUsageLog.project_id == auth_ctx.project_id)
    if artifact_hash:
        stmt = stmt.where(JoySafeterSkillUsageLog.artifact_hash == artifact_hash)
    if target_hash:
        stmt = stmt.where(JoySafeterSkillUsageLog.target_hash == target_hash)
    if security_scan_id:
        stmt = stmt.where(JoySafeterSkillUsageLog.security_scan_id == security_scan_id)

    stmt = stmt.order_by(JoySafeterSkillUsageLog.created_at.desc(), JoySafeterSkillUsageLog.id.desc()).limit(limit + 1)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    has_more = len(rows) > limit
    data = [SkillUsageResponse.model_validate(row) for row in rows[:limit]]
    return PaginatedResponse[SkillUsageResponse, SkillUsageId](
        data=data,
        has_more=has_more,
        first_id=data[0].id if data else None,
        last_id=data[-1].id if data else None,
    )


@router.post("/{skill_id}/security-scans/rescan")
async def rescan_skill_security(
    background_tasks: BackgroundTasks,
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillSecurityScanResponse:
    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    # Async dispatch: returns immediately with a scanning-state row;
    # the actual (potentially slow, LLM-backed) scan runs in the
    # background. The client polls security-scans/latest for the verdict.
    scan = await svc.rescan_skill_async(skill_id, current_user_id=auth_ctx.user_id)
    _flush_async_scans(svc, background_tasks)
    return SkillSecurityScanResponse.model_validate(scan)


@router.put("/{skill_id}")
async def update_skill(
    req: UpdateSkillRequest,
    background_tasks: BackgroundTasks,
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillResponse:
    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    skill = await svc.update_skill(
        skill_id,
        current_user_id=auth_ctx.user_id,
        name=req.name,
        description=req.description,
        content=req.content,
        tags=req.tags,
        source_type=req.source_type,
        source_url=req.source_url,
        license=req.license,
    )
    skill = await svc.get_skill(skill.id, current_user_id=auth_ctx.user_id, project_id=auth_ctx.project_id)
    _flush_async_scans(svc, background_tasks)
    return SkillResponse.model_validate(skill)


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillDeleteResponse:
    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    await svc.delete_skill(skill_id, current_user_id=auth_ctx.user_id)
    return SkillDeleteResponse(id=skill_id)

    # ── Skill Lifecycle Transitions ─────────────────────────────────────
    # Each endpoint maps to a single edge on the state machine in
    # ``SkillLifecycleService``. The service does the auth + validity check;
    # the route just wires the HTTP shell and uniformly handles the four
    # domain errors any transition can raise.


async def _run_transition(transition_coro) -> SkillLifecycleTransitionResponse:
    result = await transition_coro
    return SkillLifecycleTransitionResponse.model_validate(result)


@router.post("/{skill_id}/submit-review")
async def submit_skill_for_review(
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillLifecycleTransitionResponse:
    """draft -> pending_review."""
    svc = SkillLifecycleService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    return await _run_transition(svc.submit_for_review(skill_id, current_user_id=auth_ctx.user_id))


@router.post("/{skill_id}/approve")
async def approve_skill(
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillLifecycleTransitionResponse:
    """pending_review -> approved (self-approve allowed)."""
    svc = SkillLifecycleService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    return await _run_transition(svc.approve(skill_id, current_user_id=auth_ctx.user_id))


@router.post("/{skill_id}/reject")
async def reject_skill(
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillLifecycleTransitionResponse:
    """pending_review -> rejected."""
    svc = SkillLifecycleService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    return await _run_transition(svc.reject(skill_id, current_user_id=auth_ctx.user_id))


@router.post("/{skill_id}/archive")
async def archive_skill(
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillLifecycleTransitionResponse:
    """approved -> archived."""
    svc = SkillLifecycleService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    return await _run_transition(svc.archive(skill_id, current_user_id=auth_ctx.user_id))


@router.post("/{skill_id}/unarchive")
async def unarchive_skill(
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillLifecycleTransitionResponse:
    """archived -> approved."""
    svc = SkillLifecycleService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    return await _run_transition(svc.unarchive(skill_id, current_user_id=auth_ctx.user_id))


@router.post("/{skill_id}/reopen")
async def reopen_skill(
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillLifecycleTransitionResponse:
    """rejected -> draft (resubmit cycle)."""
    svc = SkillLifecycleService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    return await _run_transition(svc.reopen(skill_id, current_user_id=auth_ctx.user_id))

    # ── Admin: batch rescan ────────────────────────────────────────────
    # Single endpoint for "the SkillSpector ruleset changed; re-evaluate the
    # corpus". Filters by ``ruleset_version`` so an upgrade from v2.2 to v2.3
    # can run "rescan all skills whose last verdict came from < v2.3" without
    # touching skills already on v2.3. Per-request scheduling cap keeps a
    # stray call from filling the BG queue.


_MAX_RESCAN_BATCH = 50


@router.post("/admin/rescan-all")
async def admin_rescan_all_skills(
    background_tasks: BackgroundTasks,
    ruleset_below: Optional[str] = Query(
        None,
        description=(
            "Only rescan skills whose latest scan's ``ruleset_version`` is "
            "strictly less than this string (lexicographic compare on the "
            "version label). Pass empty / omit to rescan every skill that "
            "still has NULL ``ruleset_version``."
        ),
    ),
    limit: int = Query(
        _MAX_RESCAN_BATCH,
        ge=1,
        le=_MAX_RESCAN_BATCH,
        description="Maximum number of skills to schedule in this request.",
    ),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillBatchRescanResponse:
    """Schedule background rescans for skills whose verdict is older
    than the named ruleset version.

    Returns the IDs that were queued so the operator can correlate to
    the resulting ``SkillSecurityScan`` rows.

    Authorization: requires JoySafeter ``admin`` or ``owner`` role.
    """
    if auth_ctx.role.rank < JoySafeterRole.ADMIN.rank:
        raise AccessDeniedError(
            "Batch rescan requires admin or owner role",
            code="SKILL_ADMIN_PERMISSION_DENIED",
        )

        # Pick skills whose latest scan is on an older ruleset. The query
        # joins to ``skills.security_scan_id`` so we never rescan a skill
        # that's already on the target ruleset (avoids a thundering herd
        # when an operator hits this twice).
    from sqlalchemy import or_ as _or
    from sqlalchemy import select as _select

    from app.joysafeter_domain.models.joysafeter_skill import (
        JoySafeterSkillLifecycleStatus,
        JoySafeterSkillSecurityScan,
    )
    from app.joysafeter_domain.services.joysafeter_skill_security import (
        run_scan_in_background,
    )

    join_clause = JoySafeterSkill.security_scan_id == JoySafeterSkillSecurityScan.id
    # Org-scope gate: ``JoySafeterRole.ADMIN`` is org-level, not
    # platform-level. A cross-org rescan would let one org's admin
    # consume another org's scanner quota and pollute audit logs
    # (``created_by_id`` would point at someone outside the target
    # org). We bound the candidate set to projects in the caller's
    # active org via a subquery on the projects table.
    org_project_ids = _select(Project.id).where(Project.org_id == auth_ctx.org_id).scalar_subquery()
    org_scope_filter = JoySafeterSkill.project_id.in_(org_project_ids)
    mutable_skill_filter = JoySafeterSkill.lifecycle_status != JoySafeterSkillLifecycleStatus.ARCHIVED.value

    if ruleset_below:
        ruleset_filter = _or(
            JoySafeterSkillSecurityScan.ruleset_version.is_(None),
            JoySafeterSkillSecurityScan.ruleset_version < ruleset_below,
        )
        # outer join: skills with NO security_scan_id should also be candidates
        query = (
            _select(JoySafeterSkill)
            .outerjoin(JoySafeterSkillSecurityScan, join_clause)
            .where(
                _or(
                    JoySafeterSkill.security_scan_id.is_(None),
                    ruleset_filter,
                ),
                org_scope_filter,
                mutable_skill_filter,
            )
            .limit(limit)
        )
    else:
        # No ruleset filter — pick rows whose latest scan has no
        # ruleset_version at all, which is "any legacy scan that
        # didn't track the ruleset".
        query = (
            _select(JoySafeterSkill)
            .outerjoin(JoySafeterSkillSecurityScan, join_clause)
            .where(
                _or(
                    JoySafeterSkill.security_scan_id.is_(None),
                    JoySafeterSkillSecurityScan.ruleset_version.is_(None),
                ),
                org_scope_filter,
                mutable_skill_filter,
            )
            .limit(limit)
        )
        # Eager-load files so the BG task has the content it needs without
        # re-querying. The BG task opens its own DB session, so passing the
        # ORM rows through would detach them — instead we capture the
        # plain Python primitives that ``run_scan_in_background`` requires.
    from sqlalchemy.orm import selectinload

    query = query.options(selectinload(JoySafeterSkill.files))
    result = await db.execute(query)
    skills = list(result.scalars().unique())

    scheduled: list[str] = []
    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    sec = svc.security_service
    for skill in skills:
        await sec.mark_scanning(skill.id)
        background_tasks.add_task(
            run_scan_in_background,
            skill_id=skill.id,
            trigger="manual_batch_rescan",
            created_by_id=auth_ctx.user_id,
            owner_id=skill.owner_id,
            project_id=skill.project_id,
            name=skill.name,
            description=skill.description,
            content=skill.content,
            tags=list(skill.tags or []),
            license=skill.license,
            files=sec.files_from_skill(skill),
        )
        scheduled.append(skill.id)
    await db.commit()
    return SkillBatchRescanResponse(
        scheduled=scheduled,
        count=len(scheduled),
        limit=limit,
        truncated=len(skills) == limit,
    )

    # ── Skill Files ──────────────────────────────────────────────────────


@router.post("/{skill_id}/files", status_code=201)
async def create_skill_file(
    req: CreateSkillFileRequest,
    background_tasks: BackgroundTasks,
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillFileResponse:
    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    file_type = req.file_type or "text"
    f = await svc.add_file(
        skill_id=skill_id,
        current_user_id=auth_ctx.user_id,
        path=req.path,
        file_name=req.file_name,
        file_type=file_type,
        content=req.content,
        size=len(req.content) if req.content else 0,
    )
    _flush_async_scans(svc, background_tasks)
    return SkillFileResponse.model_validate(f)


@router.get("/{skill_id}/files")
async def list_skill_files(
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SkillFileListResponse:
    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    skill = await svc.get_skill(skill_id, current_user_id=auth_ctx.user_id, project_id=auth_ctx.project_id)
    files = skill.files or []
    data = [SkillFileResponse.model_validate(f) for f in files]
    return SkillFileListResponse(data=data)


@router.get("/{skill_id}/files/{file_id}")
async def get_skill_file(
    skill_id: SkillId,
    file_id: SkillFileId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SkillFileResponse:
    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    skill = await svc.get_skill(skill_id, current_user_id=auth_ctx.user_id, project_id=auth_ctx.project_id)
    f = next((f for f in (skill.files or []) if f.id == file_id), None)
    if not f:
        raise NotFoundError(
            code="SKILL_FILE_NOT_FOUND",
            message="Skill file not found",
            data={"skill_id": str(skill_id), "file_id": str(file_id)},
            user_action="refresh",
        )
    return SkillFileResponse.model_validate(f)


@router.put("/{skill_id}/files/{file_id}")
async def update_skill_file(
    req: UpdateSkillFileRequest,
    background_tasks: BackgroundTasks,
    skill_id: SkillId,
    file_id: SkillFileId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillFileResponse:
    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    f = await svc.update_file(
        file_id=file_id,
        current_user_id=auth_ctx.user_id,
        content=req.content,
        path=req.path,
        file_name=req.file_name,
        expected_skill_id=skill_id,
    )
    _flush_async_scans(svc, background_tasks)
    return SkillFileResponse.model_validate(f)


@router.delete("/{skill_id}/files/{file_id}")
async def delete_skill_file(
    background_tasks: BackgroundTasks,
    skill_id: SkillId,
    file_id: SkillFileId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillFileDeleteResponse:
    svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    await svc.delete_file(
        file_id,
        current_user_id=auth_ctx.user_id,
        expected_skill_id=skill_id,
    )
    _flush_async_scans(svc, background_tasks)
    return SkillFileDeleteResponse(id=file_id)

    # ── Skill Versions ───────────────────────────────────────────────────


@router.post("/{skill_id}/versions", status_code=201)
async def create_skill_version(
    req: CreateSkillVersionRequest,
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillVersionResponse:
    svc = SkillVersionService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    version_str = req.version or ""
    if not version_str:
        from app.joysafeter_domain.repositories.joysafeter_skill_version import SkillVersionRepository

        repo = SkillVersionRepository(db)
        highest = await repo.get_highest_version_str(skill_id)
        if highest:
            import semver

            h = semver.Version.parse(highest)
            version_str = str(h.bump_patch())
        else:
            version_str = "0.1.0"
    sv = await svc.publish_version(
        skill_id=skill_id,
        current_user_id=auth_ctx.user_id,
        version_str=version_str,
        release_notes=req.release_notes or None,
    )
    return SkillVersionResponse.model_validate(sv)


@router.get("/{skill_id}/versions")
async def list_skill_versions(
    skill_id: SkillId,
    limit: int = Query(50, ge=1, le=100),
    after_id: Optional[SkillVersionId] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SkillVersionListResponse:
    svc = SkillVersionService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    versions, has_more = await svc.list_versions(
        skill_id,
        current_user_id=auth_ctx.user_id,
        project_id=auth_ctx.project_id,
        limit=limit,
        after_id=after_id,
    )
    data = [SkillVersionResponse.model_validate(v) for v in versions]
    return SkillVersionListResponse(
        data=data,
        has_more=has_more,
        first_id=data[0].id if data else None,
        last_id=data[-1].id if data else None,
    )


@router.get("/{skill_id}/versions/{version}")
async def get_skill_version(
    version: str,
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SkillVersionResponse:
    svc = SkillVersionService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    sv = await svc.get_version(
        skill_id,
        version,
        current_user_id=auth_ctx.user_id,
        project_id=auth_ctx.project_id,
    )
    return SkillVersionResponse.model_validate(sv)


@router.delete("/{skill_id}/versions/{version}")
async def delete_skill_version(
    version: str,
    skill_id: SkillId,
    force: bool = Query(False, description="Delete even if agents reference this version"),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillVersionDeleteResponse:
    svc = SkillVersionService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    await svc.delete_version(
        skill_id,
        version,
        current_user_id=auth_ctx.user_id,
        force=force,
    )
    return SkillVersionDeleteResponse()


@router.get("/{skill_id}/versions/{version}/files")
async def list_skill_version_files(
    version: str,
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SkillVersionFileListResponse:
    svc = SkillVersionService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    sv = await svc.get_version(
        skill_id,
        version,
        current_user_id=auth_ctx.user_id,
        project_id=auth_ctx.project_id,
    )
    files = sv.files or []
    data = [SkillVersionFileResponse.model_validate(f) for f in files]
    return SkillVersionFileListResponse(data=data)


@router.post("/{skill_id}/versions/restore/{version}")
async def restore_skill_from_version(
    version: str,
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillResponse:
    svc = SkillVersionService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    skill = await svc.restore_draft(skill_id, version, current_user_id=auth_ctx.user_id)
    return SkillResponse.model_validate(skill)


# ---------------------------------------------------------------------------
# Version-level tiered promotion
#
# A skill is a project resource; project editors publish project-tier versions
# freely. Exposing a version to the ``organization`` or ``public`` tier goes
# through a version-level, four-eyes approval: a skill ADMIN submits, the org
# OWNER/admin approves (approver != publisher). Security findings remain
# informational here; optional enforcement happens only when publishing the
# immutable version. The service (``SkillPromotionService``) owns every gate; the
# routes are thin HTTP shells.
# ---------------------------------------------------------------------------


class SubmitPromotionRequest(BaseModel):
    # The tier this version is being submitted for; only the promotable tiers
    # are accepted (a 422 at the boundary beats a service-layer conflict).
    target_tier: Literal["organization", "public"]


class RejectPromotionRequest(BaseModel):
    reason: Optional[str] = None


class TakedownRequest(BaseModel):
    # The tier pointer to clear.
    tier: Literal["organization", "public"]


@router.post("/{skill_id}/versions/{version}/submit-promotion")
async def submit_skill_promotion(
    req: SubmitPromotionRequest,
    version: str,
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillVersionResponse:
    """Submit a version for promotion to organization/public (requires skill ADMIN)."""
    version_svc = SkillVersionService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    target = await version_svc.get_version_for_management(
        skill_id,
        version,
        current_user_id=auth_ctx.user_id,
    )
    svc = SkillPromotionService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    promoted = await svc.submit_promotion(
        target_tier=req.target_tier,
        current_user_id=auth_ctx.user_id,
        version_id=target.id,
    )
    return SkillVersionResponse.model_validate(promoted)


@router.post("/{skill_id}/versions/{version}/approve-promotion")
async def approve_skill_promotion(
    version: str,
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillVersionResponse:
    """Approve a pending promotion (org OWNER only, four-eyes enforced in the service)."""
    version_svc = SkillVersionService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    target = await version_svc.get_version_for_management(
        skill_id,
        version,
        current_user_id=auth_ctx.user_id,
    )
    svc = SkillPromotionService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    approved = await svc.approve_promotion(version_id=target.id, current_user_id=auth_ctx.user_id)
    return SkillVersionResponse.model_validate(approved)


@router.post("/{skill_id}/versions/{version}/reject-promotion")
async def reject_skill_promotion(
    req: RejectPromotionRequest,
    version: str,
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillVersionResponse:
    """Reject a pending promotion (org OWNER only)."""
    version_svc = SkillVersionService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    target = await version_svc.get_version_for_management(
        skill_id,
        version,
        current_user_id=auth_ctx.user_id,
    )
    svc = SkillPromotionService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    rejected = await svc.reject_promotion(version_id=target.id, current_user_id=auth_ctx.user_id, reason=req.reason)
    return SkillVersionResponse.model_validate(rejected)


@router.post("/{skill_id}/takedown")
async def takedown_skill(
    req: TakedownRequest,
    skill_id: SkillId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillResponse:
    """Pull a skill down from a tier (org OWNER only); clears the pointer and
    recomputes visibility fail-closed to the highest remaining tier."""
    svc = SkillPromotionService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    await svc.takedown(skill_id=skill_id, tier=req.tier, current_user_id=auth_ctx.user_id)
    read_svc = SkillService(db, active_org_id=auth_ctx.org_id, caller_org_role=auth_ctx.role)
    skill = await read_svc.get_skill(
        skill_id,
        current_user_id=auth_ctx.user_id,
        project_id=auth_ctx.project_id,
    )
    return SkillResponse.model_validate(skill)
