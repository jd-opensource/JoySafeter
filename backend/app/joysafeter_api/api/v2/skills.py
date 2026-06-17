import posixpath
import uuid
import zipfile
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v2.id_helpers import parse_skill_id, parse_skill_file_id, parse_skill_security_scan_id
from app.joysafeter_shared.common.app_errors import AccessDeniedError, InvalidRequestError, NotFoundError
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, get_joysafeter_auth_context, require_joysafeter_write
from app.joysafeter_shared.skill.yaml_parser import extract_metadata_from_frontmatter, is_system_file, parse_skill_md
from app.joysafeter_domain.schemas.joysafeter_skill import (
    CreateSkillFileRequest,
    CreateSkillRequest,
    CreateSkillVersionRequest,
    SkillFileResponse,
    SkillSecurityScanResponse,
    SkillResponse,
    SkillVersionFileResponse,
    SkillVersionResponse,
    UpdateSkillFileRequest,
    UpdateSkillRequest,
)
from app.joysafeter_api.services import SkillService
from app.joysafeter_api.services import SkillVersionService

router = APIRouter(tags=["joysafeter-skills"])

MAX_IMPORT_ZIP_BYTES = 10 * 1024 * 1024
MAX_IMPORT_FILES = 100
MAX_IMPORT_FILE_BYTES = 1024 * 1024
MAX_IMPORT_TOTAL_FILE_BYTES = 5 * 1024 * 1024
ZIP_IMPORT_DIAGNOSTIC_SAMPLE_SIZE = 8

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


def _handle_service_error(e: Exception):
    if isinstance(e, NotFoundError):
        return JSONResponse(status_code=404, content=e.to_payload())
    if isinstance(e, AccessDeniedError):
        return JSONResponse(status_code=403, content=e.to_payload())
    if isinstance(e, InvalidRequestError):
        return JSONResponse(status_code=400, content=e.to_payload())
    raise


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
    if len(zip_bytes) > MAX_IMPORT_ZIP_BYTES:
        raise InvalidRequestError(
            "ZIP file is too large",
            code="SKILL_IMPORT_ZIP_TOO_LARGE",
            data={"max_bytes": MAX_IMPORT_ZIP_BYTES},
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
        if len(entries) > MAX_IMPORT_FILES:
            raise InvalidRequestError(
                "ZIP contains too many files",
                code="SKILL_IMPORT_ZIP_TOO_MANY_FILES",
                data={"max_files": MAX_IMPORT_FILES},
            )

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
            if info.file_size > MAX_IMPORT_FILE_BYTES:
                raise InvalidRequestError(
                    "ZIP contains a file that is too large",
                    code="SKILL_IMPORT_FILE_TOO_LARGE",
                    data={"path": relative_path, "max_bytes": MAX_IMPORT_FILE_BYTES},
                )

            raw = archive.read(info)

            # Verify actual decompressed size (ZIP headers can lie)
            if len(raw) > MAX_IMPORT_FILE_BYTES:
                raise InvalidRequestError(
                    "ZIP contains a file that is too large (decompressed)",
                    code="SKILL_IMPORT_FILE_TOO_LARGE",
                    data={"path": relative_path, "max_bytes": MAX_IMPORT_FILE_BYTES},
                )
            total_size += len(raw)
            if total_size > MAX_IMPORT_TOTAL_FILE_BYTES:
                raise InvalidRequestError(
                    "ZIP uncompressed content is too large",
                    code="SKILL_IMPORT_TOTAL_TOO_LARGE",
                    data={"max_bytes": MAX_IMPORT_TOTAL_FILE_BYTES},
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
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillResponse:
    svc = SkillService(db)
    files_data = None
    if req.files:
        files_data = [f if isinstance(f, dict) else f for f in req.files]
    try:
        skill = await svc.create_skill(
            created_by_id=auth_ctx.user_id,
            name=req.name,
            description=req.description,
            content=req.content,
            tags=req.tags or None,
            source_type=req.source_type,
            source_url=req.source_url or None,
            is_public=req.is_public,
            license=req.license or None,
            files=files_data,
            project_id=auth_ctx.project_id,
        )
        skill = await svc.get_skill(skill.id, current_user_id=auth_ctx.user_id)
    except (NotFoundError, AccessDeniedError, InvalidRequestError) as e:
        return _handle_service_error(e)
    return SkillResponse.model_validate(skill)


@router.post("/import-zip", status_code=201)
async def import_skill_zip(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillResponse:
    filename = file.filename or ""
    if filename and not filename.lower().endswith(".zip"):
        return JSONResponse(
            status_code=400,
            content=InvalidRequestError(
                "Only ZIP files are supported",
                code="SKILL_IMPORT_ZIP_ONLY",
            ).to_payload(),
        )

    svc = SkillService(db)
    try:
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
            is_public=False,
            license=payload.get("license") or None,
            files=files_data,
            project_id=auth_ctx.project_id,
        )
        skill = await svc.get_skill(skill.id, current_user_id=auth_ctx.user_id)
    except (NotFoundError, AccessDeniedError, InvalidRequestError) as e:
        return _handle_service_error(e)
    return SkillResponse.model_validate(skill)


@router.get("")
async def list_skills(
    limit: int = Query(10, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    svc = SkillService(db)
    skills, has_more = await svc.list_skills(
        current_user_id=auth_ctx.user_id,
        project_id=auth_ctx.project_id,
        limit=limit,
        after_id=after_id,
    )
    data = [SkillResponse.model_validate(s) for s in skills]
    return {
        "data": data,
        "has_more": has_more,
        "first_id": str(data[0].id) if data else None,
        "last_id": str(data[-1].id) if data else None,
    }


@router.get("/security-scans/{scan_id}")
async def get_skill_security_scan(
    scan_id: uuid.UUID = Depends(parse_skill_security_scan_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SkillSecurityScanResponse:
    svc = SkillService(db)
    try:
        scan = await svc.get_security_scan(scan_id, current_user_id=auth_ctx.user_id)
    except (NotFoundError, AccessDeniedError) as e:
        return _handle_service_error(e)
    return SkillSecurityScanResponse.model_validate(scan)


@router.get("/{skill_id}")
async def get_skill(
    skill_id: uuid.UUID = Depends(parse_skill_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SkillResponse:
    svc = SkillService(db)
    try:
        skill = await svc.get_skill(skill_id, current_user_id=auth_ctx.user_id)
    except (NotFoundError, AccessDeniedError) as e:
        return _handle_service_error(e)
    return SkillResponse.model_validate(skill)


@router.get("/{skill_id}/security-scans/latest")
async def get_latest_skill_security_scan(
    skill_id: uuid.UUID = Depends(parse_skill_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SkillSecurityScanResponse:
    svc = SkillService(db)
    try:
        scan = await svc.get_latest_security_scan(skill_id, current_user_id=auth_ctx.user_id)
    except (NotFoundError, AccessDeniedError) as e:
        return _handle_service_error(e)
    return SkillSecurityScanResponse.model_validate(scan)


@router.get("/{skill_id}/security-scans")
async def list_skill_security_scans(
    skill_id: uuid.UUID = Depends(parse_skill_id),
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    svc = SkillService(db)
    try:
        scans, has_more = await svc.list_security_scans(
            skill_id,
            current_user_id=auth_ctx.user_id,
            limit=limit,
            after_id=after_id,
        )
    except (NotFoundError, AccessDeniedError) as e:
        return _handle_service_error(e)
    data = [SkillSecurityScanResponse.model_validate(scan) for scan in scans]
    return {
        "data": data,
        "has_more": has_more,
        "first_id": str(data[0].id) if data else None,
        "last_id": str(data[-1].id) if data else None,
    }


@router.post("/{skill_id}/security-scans/rescan")
async def rescan_skill_security(
    skill_id: uuid.UUID = Depends(parse_skill_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillSecurityScanResponse:
    svc = SkillService(db)
    try:
        scan = await svc.rescan_skill(skill_id, current_user_id=auth_ctx.user_id)
    except (NotFoundError, AccessDeniedError, InvalidRequestError) as e:
        return _handle_service_error(e)
    return SkillSecurityScanResponse.model_validate(scan)


@router.put("/{skill_id}")
async def update_skill(
    req: UpdateSkillRequest,
    skill_id: uuid.UUID = Depends(parse_skill_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillResponse:
    svc = SkillService(db)
    try:
        skill = await svc.update_skill(
            skill_id,
            current_user_id=auth_ctx.user_id,
            name=req.name,
            description=req.description,
            content=req.content,
            tags=req.tags,
            source_type=req.source_type,
            source_url=req.source_url,
            is_public=req.is_public,
            license=req.license,
        )
        skill = await svc.get_skill(skill.id, current_user_id=auth_ctx.user_id)
    except (NotFoundError, AccessDeniedError, InvalidRequestError) as e:
        return _handle_service_error(e)
    return SkillResponse.model_validate(skill)


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: uuid.UUID = Depends(parse_skill_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
):
    svc = SkillService(db)
    try:
        await svc.delete_skill(skill_id, current_user_id=auth_ctx.user_id)
    except (NotFoundError, AccessDeniedError) as e:
        return _handle_service_error(e)
    return {"id": f"skill_{skill_id}", "type": "skill_deleted"}


# ── Skill Files ──────────────────────────────────────────────────────

@router.post("/{skill_id}/files", status_code=201)
async def create_skill_file(
    req: CreateSkillFileRequest,
    skill_id: uuid.UUID = Depends(parse_skill_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillFileResponse:
    svc = SkillService(db)
    file_type = req.file_type or "text"
    try:
        f = await svc.add_file(
            skill_id=skill_id,
            current_user_id=auth_ctx.user_id,
            path=req.path,
            file_name=req.file_name,
            file_type=file_type,
            content=req.content,
            size=len(req.content) if req.content else 0,
        )
    except (NotFoundError, AccessDeniedError, InvalidRequestError) as e:
        return _handle_service_error(e)
    return SkillFileResponse.model_validate(f)


@router.get("/{skill_id}/files")
async def list_skill_files(
    skill_id: uuid.UUID = Depends(parse_skill_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    svc = SkillService(db)
    try:
        skill = await svc.get_skill(skill_id, current_user_id=auth_ctx.user_id)
    except (NotFoundError, AccessDeniedError) as e:
        return _handle_service_error(e)
    files = skill.files or []
    data = [SkillFileResponse.model_validate(f) for f in files]
    return {"data": data}


@router.get("/{skill_id}/files/{file_id}")
async def get_skill_file(
    skill_id: uuid.UUID = Depends(parse_skill_id),
    file_id: uuid.UUID = Depends(parse_skill_file_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SkillFileResponse:
    svc = SkillService(db)
    try:
        skill = await svc.get_skill(skill_id, current_user_id=auth_ctx.user_id)
    except (NotFoundError, AccessDeniedError) as e:
        return _handle_service_error(e)
    f = next((f for f in (skill.files or []) if f.id == file_id), None)
    if not f:
        raise HTTPException(404, "Skill file not found")
    return SkillFileResponse.model_validate(f)


@router.put("/{skill_id}/files/{file_id}")
async def update_skill_file(
    req: UpdateSkillFileRequest,
    skill_id: uuid.UUID = Depends(parse_skill_id),
    file_id: uuid.UUID = Depends(parse_skill_file_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillFileResponse:
    svc = SkillService(db)
    try:
        f = await svc.update_file(
            file_id=file_id,
            current_user_id=auth_ctx.user_id,
            content=req.content,
            path=req.path,
            file_name=req.file_name,
        )
    except (NotFoundError, AccessDeniedError, InvalidRequestError) as e:
        return _handle_service_error(e)
    return SkillFileResponse.model_validate(f)


@router.delete("/{skill_id}/files/{file_id}")
async def delete_skill_file(
    skill_id: uuid.UUID = Depends(parse_skill_id),
    file_id: uuid.UUID = Depends(parse_skill_file_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
):
    svc = SkillService(db)
    try:
        await svc.delete_file(file_id, current_user_id=auth_ctx.user_id)
    except (NotFoundError, AccessDeniedError) as e:
        return _handle_service_error(e)
    return {"id": f"sklfile_{file_id}", "type": "skill_file_deleted"}


# ── Skill Versions ───────────────────────────────────────────────────

@router.post("/{skill_id}/versions", status_code=201)
async def create_skill_version(
    req: CreateSkillVersionRequest,
    skill_id: uuid.UUID = Depends(parse_skill_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillVersionResponse:
    svc = SkillVersionService(db)
    version_str = req.version or ""
    if not version_str:
        from app.joysafeter_domain.repositories.skill_version import SkillVersionRepository
        repo = SkillVersionRepository(db)
        highest = await repo.get_highest_version_str(skill_id)
        if highest:
            import semver
            h = semver.Version.parse(highest)
            version_str = str(h.bump_patch())
        else:
            version_str = "0.1.0"
    try:
        sv = await svc.publish_version(
            skill_id=skill_id,
            current_user_id=auth_ctx.user_id,
            version_str=version_str,
            release_notes=req.release_notes or None,
        )
    except (NotFoundError, AccessDeniedError, InvalidRequestError) as e:
        return _handle_service_error(e)
    return SkillVersionResponse.model_validate(sv)


@router.get("/{skill_id}/versions")
async def list_skill_versions(
    skill_id: uuid.UUID = Depends(parse_skill_id),
    limit: int = Query(50, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    svc = SkillVersionService(db)
    try:
        versions = await svc.list_versions(skill_id, current_user_id=auth_ctx.user_id)
    except (NotFoundError, AccessDeniedError) as e:
        return _handle_service_error(e)
    data = [SkillVersionResponse.model_validate(v) for v in versions]
    return {"data": data, "has_more": False}


@router.get("/{skill_id}/versions/{version}")
async def get_skill_version(
    version: str,
    skill_id: uuid.UUID = Depends(parse_skill_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SkillVersionResponse:
    svc = SkillVersionService(db)
    try:
        sv = await svc.get_version(skill_id, version, current_user_id=auth_ctx.user_id)
    except (NotFoundError, AccessDeniedError) as e:
        return _handle_service_error(e)
    return SkillVersionResponse.model_validate(sv)


@router.delete("/{skill_id}/versions/{version}")
async def delete_skill_version(
    version: str,
    skill_id: uuid.UUID = Depends(parse_skill_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
):
    svc = SkillVersionService(db)
    try:
        await svc.delete_version(skill_id, version, current_user_id=auth_ctx.user_id)
    except (NotFoundError, AccessDeniedError) as e:
        return _handle_service_error(e)
    return {"type": "skill_version_deleted"}


@router.get("/{skill_id}/versions/{version}/files")
async def list_skill_version_files(
    version: str,
    skill_id: uuid.UUID = Depends(parse_skill_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    svc = SkillVersionService(db)
    try:
        sv = await svc.get_version(skill_id, version, current_user_id=auth_ctx.user_id)
    except (NotFoundError, AccessDeniedError) as e:
        return _handle_service_error(e)
    files = sv.files or []
    data = [SkillVersionFileResponse.model_validate(f) for f in files]
    return {"data": data}


@router.post("/{skill_id}/versions/restore/{version}")
async def restore_skill_from_version(
    version: str,
    skill_id: uuid.UUID = Depends(parse_skill_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SkillResponse:
    svc = SkillVersionService(db)
    try:
        skill = await svc.restore_draft(skill_id, version, current_user_id=auth_ctx.user_id)
    except (NotFoundError, AccessDeniedError, InvalidRequestError) as e:
        return _handle_service_error(e)
    return SkillResponse.model_validate(skill)
