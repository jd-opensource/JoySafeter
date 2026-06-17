"""
Skill Service: Permission Check + CRUD
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from loguru import logger

from app.joysafeter_shared.common.app_errors import AccessDeniedError, InvalidRequestError, NotFoundError
from app.joysafeter_shared.common.skill_permissions import check_skill_access
from app.joysafeter_shared.skill.validators import (
    truncate_compatibility,
    truncate_description,
    validate_compatibility,
    validate_skill_description,
    validate_skill_name,
)
from app.joysafeter_shared.skill.yaml_parser import (
    extract_metadata_from_frontmatter,
    is_system_file,
    is_valid_text_content,
    parse_skill_md,
    validate_file_extension,
)
from app.joysafeter_domain.models.skill import Skill, SkillFile
from app.joysafeter_domain.models.skill_collaborator import CollaboratorRole
from app.joysafeter_domain.repositories.skill import SkillFileRepository, SkillRepository
from app.joysafeter_domain.repositories.skill_version import SkillVersionRepository

from .base import BaseService
from .skill_security_service import SkillSecurityService


class SkillService(BaseService[Skill]):
    def __init__(self, db):
        super().__init__(db)
        self.repo = SkillRepository(db)
        self.file_repo = SkillFileRepository(db)
        self.security_service = SkillSecurityService(db)

    def _invalid_import_files_error(self, invalid_files: List[str]) -> InvalidRequestError:
        invalid_list = "\n".join(f"  - {file_name}" for file_name in invalid_files)
        return InvalidRequestError(
            f"The following files cannot be imported (binary files or system files):\n{invalid_list}\n\n"
            f"Skill import only supports text files (.py, .md, .json, .yaml, etc.)",
            code="SKILL_IMPORT_FILES_INVALID",
            data={"files": invalid_files},
        )

    def _is_skill_md_file(self, path: Optional[str], file_name: Optional[str]) -> bool:
        normalized_path = (path or "").replace("\\", "/").strip("/")
        normalized_name = (file_name or "").replace("\\", "/").rsplit("/", 1)[-1]
        return normalized_path.lower() == "skill.md" or normalized_name.lower() == "skill.md"

    def _skill_md_candidate_fields(
        self,
        skill: Skill,
        content: Optional[str],
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "name": skill.name,
            "description": skill.description,
            "content": skill.content,
            "tags": list(skill.tags or []),
            "license": skill.license,
        }
        if not content:
            return fields

        frontmatter, body = parse_skill_md(content)
        metadata = extract_metadata_from_frontmatter(frontmatter)
        if metadata.get("name"):
            fields["name"] = metadata["name"]
        if metadata.get("description"):
            fields["description"] = metadata["description"]
        if metadata.get("tags") and isinstance(metadata["tags"], list):
            fields["tags"] = metadata["tags"]
        if metadata.get("license"):
            fields["license"] = metadata["license"]
        if body:
            fields["content"] = body.strip()
        return fields

    def _apply_skill_md_content(self, skill: Skill, content: Optional[str]) -> None:
        if not content:
            return
        fields = self._skill_md_candidate_fields(skill, content)
        skill.name = fields["name"]
        skill.description = fields["description"]
        skill.content = fields["content"]
        skill.tags = fields["tags"]
        skill.license = fields["license"]

    async def list_skills(
        self,
        current_user_id: Optional[str] = None,
        include_public: bool = True,
        tags: Optional[List[str]] = None,
        project_id: Optional[str] = None,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
    ) -> tuple[List[Skill], bool]:
        """Get Skills list with cursor pagination."""
        return await self.repo.list_by_user(
            user_id=current_user_id,
            include_public=include_public,
            tags=tags,
            project_id=project_id,
            limit=limit,
            after_id=after_id,
        )

    async def get_skill(
        self,
        skill_id: uuid.UUID,
        current_user_id: Optional[str] = None,
    ) -> Skill:
        """Get Skill details"""
        skill = await self.repo.get_with_files(skill_id)
        if not skill or not isinstance(skill, Skill):
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})

        # Permission check: collaborator-aware
        if current_user_id:
            await check_skill_access(
                self.db,
                skill,
                current_user_id,
                CollaboratorRole.viewer,
            )
        elif not skill.is_public:
            raise AccessDeniedError("You don't have permission to access this skill", code="SKILL_ACCESS_DENIED")

        # Type assertion: get_with_files returns Optional[Skill], we've already checked it's not None
        skill = await self._attach_latest_version(skill)
        result = skill
        return result  # type: ignore

    async def get_skill_by_name(
        self,
        skill_name: str,
        current_user_id: Optional[str] = None,
    ) -> Optional[Skill]:
        """Get Skill by name (case-insensitive)

        Args:
            skill_name: Skill name
            current_user_id: Current user ID for permission check

        Returns:
            Skill object, returns None if not found or unauthorized
        """
        # Get all accessible skills
        all_skills = await self.list_skills(
            current_user_id=current_user_id,
            include_public=True,
        )

        # Search by name (case-insensitive)
        for skill in all_skills:
            if skill.name.lower() == skill_name.lower():
                # Get complete information (including files)
                result = await self.repo.get_with_files(skill.id)
                return result if isinstance(result, Skill) else None

        return None

    async def create_skill(
        self,
        created_by_id: str,
        name: str,
        description: str,
        content: str,
        tags: Optional[List[str]] = None,
        source_type: str = "local",
        source_url: Optional[str] = None,
        root_path: Optional[str] = None,
        owner_id: Optional[str] = None,
        is_public: bool = False,
        license: Optional[str] = None,
        files: Optional[List[Dict[str, Any]]] = None,
        project_id: Optional[str] = None,
    ) -> Skill:
        """Create Skill

        If files contain a SKILL.md file with YAML frontmatter, metadata
        (tags, license, compatibility, etc.) will be extracted from it.
        Name and description from frontmatter are only used as fallbacks
        when the caller does not provide them.
        """
        # If owner_id is not specified, use creator ID
        if owner_id is None:
            owner_id = created_by_id

        # Initialize new fields per Agent Skills specification
        compatibility = None
        skill_metadata = {}
        allowed_tools = []

        # Parse SKILL.md frontmatter if present to sync name/description
        if files:
            skill_md_file = next(
                (f for f in files if f.get("path") == "SKILL.md" or f.get("file_name") == "SKILL.md"), None
            )
            if skill_md_file and skill_md_file.get("content"):
                frontmatter, body = parse_skill_md(skill_md_file["content"])
                # Extract all metadata using extract_metadata_from_frontmatter
                metadata = extract_metadata_from_frontmatter(frontmatter)

                # Caller-provided values take priority over frontmatter.
                if not name and metadata.get("name"):
                    name = metadata["name"]
                if not description and metadata.get("description"):
                    description = metadata["description"]

                # Extract additional metadata from frontmatter
                if metadata.get("tags") and isinstance(metadata["tags"], list):
                    tags = metadata["tags"]
                if metadata.get("license"):
                    license = metadata["license"]

                # Extract new fields per Agent Skills specification
                compatibility = metadata.get("compatibility")
                skill_metadata = metadata.get("metadata", {})
                allowed_tools = metadata.get("allowed_tools", [])

                # Store the markdown body as content
                content = body.strip() if body else content

            # Log warnings for uncommon file extensions (but don't reject)
            for file_data in files:
                file_path = file_data.get("path", "")
                if file_path:
                    is_common, warning = validate_file_extension(file_path)
                    if warning:
                        # Just log the warning, don't reject
                        logger.warning(f"Skill file warning: {warning}")

        # Validate skill name per Agent Skills specification
        is_valid, error = validate_skill_name(name)
        if not is_valid:
            logger.warning(f"Invalid skill name rejected: {name!r} — {error}")
            raise InvalidRequestError(
                f"Invalid skill name: {error}",
                code="SKILL_NAME_INVALID",
                data={"validation_error": error, "name": name},
            )

        # Validate and truncate description per Agent Skills specification
        is_valid, error = validate_skill_description(description)
        if not is_valid:
            # Truncate if too long (warn but continue)
            logger.warning(f"Skill description exceeds 1024 characters, truncating: {error}")
            description = truncate_description(description)

        # Validate compatibility if provided
        if compatibility is not None:
            is_valid, error = validate_compatibility(compatibility)
            if not is_valid:
                # Truncate if too long (warn but continue)
                logger.warning(f"Skill compatibility exceeds 500 characters, truncating: {error}")
                compatibility = truncate_compatibility(compatibility)

        # Check if Skill with same name exists (same owner)
        existing = await self.repo.get_by_name_and_owner(name, owner_id)
        if existing:
            raise InvalidRequestError(
                f"Skill name '{name}' already exists for this owner",
                code="SKILL_NAME_ALREADY_EXISTS",
                data={"name": name},
            )

        if files:
            invalid_files = []
            for file_data in files:
                file_path = file_data.get("path", "")
                file_name = file_data.get("file_name", "")
                file_content_raw = file_data.get("content")
                file_content_val: Optional[str] = (
                    file_content_raw
                    if isinstance(file_content_raw, (str, type(None)))
                    else str(file_content_raw)
                    if file_content_raw is not None
                    else None
                )
                if is_system_file(file_path) or is_system_file(file_name):
                    invalid_files.append(f"{file_path} (system file)")
                    continue
                if file_content_val is not None:
                    is_valid, error_msg = is_valid_text_content(file_content_val)
                    if not is_valid:
                        invalid_files.append(f"{file_path} ({error_msg})")
            if invalid_files:
                raise self._invalid_import_files_error(invalid_files)

        security_scan = await self.security_service.scan_for_write(
            trigger="create",
            created_by_id=created_by_id,
            owner_id=owner_id,
            project_id=project_id,
            skill_id=None,
            name=name,
            description=description,
            content=content,
            tags=tags or [],
            license=license,
            files=files,
        )

        skill = Skill(
            name=name,
            description=description,
            content=content,
            tags=tags or [],
            source_type=source_type,
            source_url=source_url,
            root_path=root_path,
            owner_id=owner_id,
            created_by_id=created_by_id,
            is_public=is_public,
            license=license,
            compatibility=compatibility,
            meta_data=skill_metadata,
            allowed_tools=allowed_tools,
            project_id=project_id,
        )
        self.db.add(skill)
        await self.db.flush()
        await self.db.refresh(skill)
        if security_scan is not None:
            security_scan.skill_id = skill.id
            self.security_service.apply_latest_scan(skill, security_scan)

        # Create associated files
        if files:
            invalid_files = []
            for file_data in files:
                file_path = file_data.get("path", "")
                file_name = file_data.get("file_name", "")
                file_content_raw = file_data.get("content")
                file_content_val: Optional[str] = (
                    file_content_raw
                    if isinstance(file_content_raw, (str, type(None)))
                    else str(file_content_raw)
                    if file_content_raw is not None
                    else None
                )

                # Check if it's a system file
                if is_system_file(file_path) or is_system_file(file_name):
                    invalid_files.append(f"{file_path} (system file)")
                    continue

                # Validate content if provided
                if file_content_val is not None:
                    is_valid, error_msg = is_valid_text_content(file_content_val)
                    if not is_valid:
                        invalid_files.append(f"{file_path} ({error_msg})")
                        continue

                # file_content_val can be None, but SkillFile.content might require str
                file_content: str = file_content_val if file_content_val is not None else ""
                file_obj = SkillFile(
                    skill_id=skill.id,
                    path=file_path,
                    file_name=file_name,
                    file_type=file_data.get("file_type", ""),
                    content=file_content,
                    storage_type=file_data.get("storage_type", "database"),
                    storage_key=file_data.get("storage_key"),
                    size=file_data.get("size", 0),
                )
                self.db.add(file_obj)

            # If there are invalid files, raise an error
            if invalid_files:
                raise self._invalid_import_files_error(invalid_files)

        await self.db.commit()
        await self.db.refresh(skill)
        result = skill
        return result  # type: ignore

    async def update_skill(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        content: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source_type: Optional[str] = None,
        source_url: Optional[str] = None,
        root_path: Optional[str] = None,
        owner_id: Optional[str] = None,
        is_public: Optional[bool] = None,
        license: Optional[str] = None,
        compatibility: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        allowed_tools: Optional[List[str]] = None,
        files: Optional[List[Dict[str, Any]]] = None,
    ) -> Skill:
        """Update Skill

        If files are provided, they will replace all existing files for this skill.
        """
        skill = await self.repo.get_with_files(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})

        # Permission check: collaborator-aware (editor role)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            CollaboratorRole.editor,
        )

        # Parse SKILL.md frontmatter if files contain SKILL.md
        if files:
            skill_md_file = next(
                (f for f in files if f.get("path") == "SKILL.md" or f.get("file_name") == "SKILL.md"), None
            )
            if skill_md_file and skill_md_file.get("content"):
                frontmatter, body = parse_skill_md(skill_md_file["content"])
                # Extract all metadata using extract_metadata_from_frontmatter
                metadata_dict = extract_metadata_from_frontmatter(frontmatter)

                # Override fields from frontmatter if not explicitly provided
                if metadata_dict.get("name") and name is None:
                    name = metadata_dict["name"]
                if metadata_dict.get("description") and description is None:
                    description = metadata_dict["description"]
                if metadata_dict.get("tags") and isinstance(metadata_dict["tags"], list) and tags is None:
                    tags = metadata_dict["tags"]
                if metadata_dict.get("license") and license is None:
                    license = metadata_dict["license"]
                if metadata_dict.get("compatibility") is not None and compatibility is None:
                    compatibility = metadata_dict["compatibility"]
                if metadata_dict.get("metadata") and metadata is None:
                    metadata = metadata_dict["metadata"]
                if metadata_dict.get("allowed_tools") and allowed_tools is None:
                    allowed_tools = metadata_dict["allowed_tools"]

                # Store the markdown body as content if not explicitly provided
                if content is None:
                    content = body.strip() if body else None

            # Log warnings for uncommon file extensions (but don't reject)
            for file_data in files:
                file_path = file_data.get("path", "")
                if file_path:
                    is_common, warning = validate_file_extension(file_path)
                    if warning:
                        logger.warning(f"Skill file warning: {warning}")

        proposed_name = skill.name if name is None else name
        proposed_description = skill.description if description is None else description
        proposed_content = skill.content if content is None else content
        proposed_tags = skill.tags if tags is None else tags
        proposed_source_type = skill.source_type if source_type is None else source_type
        proposed_source_url = skill.source_url if source_url is None else source_url
        proposed_root_path = skill.root_path if root_path is None else root_path
        proposed_owner_id = skill.owner_id if owner_id is None else owner_id
        proposed_is_public = skill.is_public if is_public is None else is_public
        proposed_license = skill.license if license is None else license
        proposed_compatibility = skill.compatibility if compatibility is None else compatibility
        proposed_metadata = skill.meta_data
        proposed_allowed_tools = skill.allowed_tools

        # Validate name if provided
        if name and name != skill.name:
            is_valid, error = validate_skill_name(name)
            if not is_valid:
                logger.warning(f"Invalid skill name rejected: {name!r} — {error}")
                raise InvalidRequestError(
                    f"Invalid skill name: {error}",
                    code="SKILL_NAME_INVALID",
                    data={"validation_error": error, "name": name},
                )
            existing = await self.repo.get_by_name_and_owner(name, skill.owner_id)
            if existing:
                raise InvalidRequestError(
                    f"Skill name '{name}' already exists for this owner",
                    code="SKILL_NAME_ALREADY_EXISTS",
                    data={"name": name},
                )

        # Validate description if provided
        if description is not None:
            is_valid, error = validate_skill_description(description)
            if not is_valid:
                # Truncate if too long (warn but continue)
                logger.warning(f"Skill description exceeds 1024 characters, truncating: {error}")
                proposed_description = truncate_description(description)

        # Validate compatibility if provided
        if compatibility is not None:
            is_valid, error = validate_compatibility(compatibility)
            if not is_valid:
                # Truncate if too long (warn but continue)
                logger.warning(f"Skill compatibility exceeds 500 characters, truncating: {error}")
                proposed_compatibility = truncate_compatibility(compatibility)

        # Prepare metadata if provided
        if metadata is not None:
            # Ensure all values are strings (per spec)
            if isinstance(metadata, dict):
                proposed_metadata = {k: str(v) for k, v in metadata.items() if isinstance(k, str)}
            else:
                proposed_metadata = {}

        # Prepare allowed_tools if provided
        if allowed_tools is not None:
            if isinstance(allowed_tools, list):
                proposed_allowed_tools = allowed_tools
            else:
                proposed_allowed_tools = []

        proposed_files = files if files is not None else self.security_service.files_from_skill(skill)
        if files is not None:
            invalid_files = []
            for file_data in files:
                file_path = file_data.get("path", "")
                file_name = file_data.get("file_name", "")
                file_content = file_data.get("content")

                if is_system_file(file_path) or is_system_file(file_name):
                    invalid_files.append(f"{file_path} (system file)")
                    continue

                if file_content is not None:
                    is_valid, error_msg = is_valid_text_content(file_content)
                    if not is_valid:
                        invalid_files.append(f"{file_path} ({error_msg})")
                        continue
            if invalid_files:
                raise self._invalid_import_files_error(invalid_files)

        security_scan = await self.security_service.scan_for_write(
            trigger="update",
            created_by_id=current_user_id,
            owner_id=proposed_owner_id,
            project_id=skill.project_id,
            skill_id=skill.id,
            name=proposed_name,
            description=proposed_description,
            content=proposed_content,
            tags=proposed_tags or [],
            license=proposed_license,
            files=proposed_files,
        )

        skill.name = proposed_name
        skill.description = proposed_description
        skill.content = proposed_content
        skill.tags = proposed_tags or []
        skill.source_type = proposed_source_type
        skill.source_url = proposed_source_url
        skill.root_path = proposed_root_path
        skill.owner_id = proposed_owner_id
        skill.is_public = proposed_is_public
        skill.license = proposed_license
        skill.compatibility = proposed_compatibility
        skill.meta_data = proposed_metadata or {}
        skill.allowed_tools = proposed_allowed_tools or []

        # Handle file updates - replace all files if files are provided
        if files is not None:
            # Delete existing files
            await self.file_repo.delete_by_skill(skill_id)

            # Create new files
            invalid_files = []
            for file_data in files:
                file_path = file_data.get("path", "")
                file_name = file_data.get("file_name", "")
                content = file_data.get("content")

                # Check if it's a system file
                if is_system_file(file_path) or is_system_file(file_name):
                    invalid_files.append(f"{file_path} (system file)")
                    continue

                # Validate content if provided
                if content is not None:
                    is_valid, error_msg = is_valid_text_content(content)
                    if not is_valid:
                        invalid_files.append(f"{file_path} ({error_msg})")
                        continue

                file_obj = SkillFile(
                    skill_id=skill_id,
                    path=file_path,
                    file_name=file_name,
                    file_type=file_data.get("file_type", ""),
                    content=content,
                    storage_type=file_data.get("storage_type", "database"),
                    storage_key=file_data.get("storage_key"),
                    size=file_data.get("size", 0),
                )
                self.db.add(file_obj)

            # If there are invalid files, raise an error
            if invalid_files:
                raise self._invalid_import_files_error(invalid_files)

        if security_scan is not None:
            self.security_service.apply_latest_scan(skill, security_scan)

        await self.db.commit()
        await self.db.refresh(skill)
        result = skill
        return result  # type: ignore

    async def delete_skill(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
    ) -> None:
        """Delete Skill"""
        skill = await self.repo.get_with_files(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})

        # Permission check: Only owner can delete
        if skill.owner_id != current_user_id:
            raise AccessDeniedError("Only the owner can delete a skill", code="SKILL_DELETE_FORBIDDEN")

        # Delete associated files
        await self.file_repo.delete_by_skill(skill_id)

        # Delete Skill
        await self.repo.delete(skill_id)
        await self.db.commit()

    async def add_file(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        path: str,
        file_name: str,
        file_type: str,
        content: Optional[str] = None,
        storage_type: str = "database",
        storage_key: Optional[str] = None,
        size: int = 0,
    ) -> SkillFile:
        """Add file to Skill"""
        skill = await self.repo.get_with_files(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})

        # Permission check: collaborator-aware (editor role)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            CollaboratorRole.editor,
        )

        # Check if it's a system file
        if is_system_file(path) or is_system_file(file_name):
            raise InvalidRequestError(
                f"File '{path}' is a system file and cannot be imported",
                code="SKILL_SYSTEM_FILE_IMPORT_FORBIDDEN",
                data={"path": path},
            )

        # Validate content if provided
        if content is not None:
            is_valid, error_msg = is_valid_text_content(content)
            if not is_valid:
                raise InvalidRequestError(
                    f"File '{path}' {error_msg}. Skill import only supports text files (.py, .md, .json, .yaml, etc.)",
                    code="SKILL_FILE_CONTENT_INVALID",
                    data={"path": path},
                )

        # Log warning for uncommon file extensions (but don't reject)
        if path:
            is_common, warning = validate_file_extension(path)
            if warning:
                logger.warning(f"Skill file warning: {warning}")

        proposed_files = self.security_service.files_from_skill(skill)
        proposed_files.append(
            {
                "path": path,
                "file_name": file_name,
                "file_type": file_type,
                "content": content or "",
                "storage_type": storage_type,
                "storage_key": storage_key,
                "size": size,
            }
        )
        scan_fields = (
            self._skill_md_candidate_fields(skill, content)
            if self._is_skill_md_file(path, file_name)
            else {
                "name": skill.name,
                "description": skill.description,
                "content": skill.content,
                "tags": list(skill.tags or []),
                "license": skill.license,
            }
        )
        security_scan = await self.security_service.scan_for_write(
            trigger="file_add",
            created_by_id=current_user_id,
            owner_id=skill.owner_id,
            project_id=skill.project_id,
            skill_id=skill.id,
            name=scan_fields["name"],
            description=scan_fields["description"],
            content=scan_fields["content"],
            tags=scan_fields["tags"],
            license=scan_fields["license"],
            files=proposed_files,
        )

        file_obj = SkillFile(
            skill_id=skill_id,
            path=path,
            file_name=file_name,
            file_type=file_type,
            content=content,
            storage_type=storage_type,
            storage_key=storage_key,
            size=size,
        )
        self.db.add(file_obj)
        if self._is_skill_md_file(path, file_name):
            self._apply_skill_md_content(skill, content)
        if security_scan is not None:
            self.security_service.apply_latest_scan(skill, security_scan)
        await self.db.commit()
        await self.db.refresh(file_obj)

        return file_obj

    async def delete_file(
        self,
        file_id: uuid.UUID,
        current_user_id: str,
    ) -> None:
        """Delete file"""
        file_obj = await self.file_repo.get(file_id)
        if not file_obj:
            raise NotFoundError("Skill file not found", code="SKILL_FILE_NOT_FOUND", data={"file_id": str(file_id)})

        skill = await self.repo.get_with_files(file_obj.skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(file_obj.skill_id)})

        # Permission check: collaborator-aware (editor role)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            CollaboratorRole.editor,
        )

        proposed_files = [
            {
                "path": existing_file.path,
                "file_name": existing_file.file_name,
                "file_type": existing_file.file_type,
                "content": existing_file.content or "",
                "storage_type": existing_file.storage_type,
                "storage_key": existing_file.storage_key,
                "size": existing_file.size,
            }
            for existing_file in (skill.files or [])
            if existing_file.id != file_obj.id
        ]
        security_scan = await self.security_service.scan_for_write(
            enforce_write_policy=False,
            trigger="file_delete",
            created_by_id=current_user_id,
            owner_id=skill.owner_id,
            project_id=skill.project_id,
            skill_id=skill.id,
            name=skill.name,
            description=skill.description,
            content=skill.content,
            tags=list(skill.tags or []),
            license=skill.license,
            files=proposed_files,
        )

        await self.file_repo.delete(file_id)
        if security_scan is not None:
            self.security_service.apply_latest_scan(skill, security_scan)
        await self.db.commit()

    async def update_file(
        self,
        file_id: uuid.UUID,
        current_user_id: str,
        content: Optional[str] = None,
        path: Optional[str] = None,
        file_name: Optional[str] = None,
    ) -> SkillFile:
        """Update file content"""
        file_obj = await self.file_repo.get(file_id)
        if not file_obj:
            raise NotFoundError("Skill file not found", code="SKILL_FILE_NOT_FOUND", data={"file_id": str(file_id)})

        skill = await self.repo.get_with_files(file_obj.skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(file_obj.skill_id)})

        # Permission check: collaborator-aware (editor role)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            CollaboratorRole.editor,
        )

        # Check if it's a system file (if path is being updated)
        if path is not None:
            if is_system_file(path) or is_system_file(file_obj.file_name):
                raise InvalidRequestError(
                    f"File '{path}' is a system file and cannot be imported",
                    code="SKILL_SYSTEM_FILE_IMPORT_FORBIDDEN",
                    data={"path": path},
                )

            # Log warning for uncommon file extensions (but don't reject)
            is_common, warning = validate_file_extension(path)
            if warning:
                logger.warning(f"Skill file warning: {warning}")

        if content is not None:
            # Validate content
            is_valid, error_msg = is_valid_text_content(content)
            if not is_valid:
                raise InvalidRequestError(
                    f"File '{file_obj.path}' {error_msg}. Skill import only supports text files (.py, .md, .json, .yaml, etc.)",
                    code="SKILL_FILE_CONTENT_INVALID",
                    data={"path": file_obj.path},
                )

        proposed_path = file_obj.path if path is None else path
        proposed_file_name = file_obj.file_name if file_name is None else file_name
        proposed_content = file_obj.content if content is None else content
        proposed_files = []
        for existing_file in skill.files or []:
            if existing_file.id == file_obj.id:
                proposed_files.append(
                    {
                        "path": proposed_path,
                        "file_name": proposed_file_name,
                        "file_type": existing_file.file_type,
                        "content": proposed_content or "",
                        "storage_type": existing_file.storage_type,
                        "storage_key": existing_file.storage_key,
                        "size": len(proposed_content) if proposed_content else 0,
                    }
                )
            else:
                proposed_files.append(
                    {
                        "path": existing_file.path,
                        "file_name": existing_file.file_name,
                        "file_type": existing_file.file_type,
                        "content": existing_file.content or "",
                        "storage_type": existing_file.storage_type,
                        "storage_key": existing_file.storage_key,
                        "size": existing_file.size,
                    }
                )
        scan_fields = (
            self._skill_md_candidate_fields(skill, proposed_content)
            if self._is_skill_md_file(proposed_path, proposed_file_name)
            else {
                "name": skill.name,
                "description": skill.description,
                "content": skill.content,
                "tags": list(skill.tags or []),
                "license": skill.license,
            }
        )
        security_scan = await self.security_service.scan_for_write(
            trigger="file_update",
            created_by_id=current_user_id,
            owner_id=skill.owner_id,
            project_id=skill.project_id,
            skill_id=skill.id,
            name=scan_fields["name"],
            description=scan_fields["description"],
            content=scan_fields["content"],
            tags=scan_fields["tags"],
            license=scan_fields["license"],
            files=proposed_files,
        )

        if content is not None:
            file_obj.content = content
            file_obj.size = len(content) if content else 0
        if path is not None:
            file_obj.path = path
        if file_name is not None:
            file_obj.file_name = file_name

        if self._is_skill_md_file(file_obj.path, file_obj.file_name):
            self._apply_skill_md_content(skill, file_obj.content)
        if security_scan is not None:
            self.security_service.apply_latest_scan(skill, security_scan)
        await self.db.commit()
        await self.db.refresh(file_obj)

        # Type assertion: refresh updates the object in place
        return file_obj  # type: ignore

    async def _sync_skill_from_skill_md(
        self,
        skill: Skill,
        content: Optional[str],
    ) -> None:
        """Sync skill metadata from SKILL.md frontmatter.

        Args:
            skill: The skill to update
            content: The SKILL.md content with YAML frontmatter
        """
        if not content:
            return

        self._apply_skill_md_content(skill, content)
        await self.db.commit()
        await self.db.refresh(skill)

    async def import_skill_from_directory(self, skill_dir: str, owner_id: str, is_public: bool = False) -> Skill:
        """Import Skill from directory

        Args:
            skill_dir: Skill directory path (containing SKILL.md)
            owner_id: Owner ID

        Returns:
            Created or updated Skill object
        """
        from pathlib import Path

        from app.joysafeter_shared.skill.yaml_parser import extract_metadata_from_frontmatter, parse_skill_md

        skill_path = Path(skill_dir)
        if not skill_path.exists():
            raise FileNotFoundError(f"Skill directory not found: {skill_dir}")

        # Find SKILL.md
        skill_md_path = skill_path / "SKILL.md"
        if not skill_md_path.exists():
            # Try lowercase
            skill_md_path = skill_path / "skill.md"

        if not skill_md_path.exists():
            raise FileNotFoundError(f"SKILL.md not found in {skill_dir}")

        # Read SKILL.md
        with open(skill_md_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Parse metadata
        frontmatter, body = parse_skill_md(content)
        metadata = extract_metadata_from_frontmatter(frontmatter)

        name = metadata.get("name", skill_path.name)
        description = metadata.get("description", "")

        # Prepare file list
        files = []

        # Add SKILL.md
        files.append({"path": "SKILL.md", "file_name": "SKILL.md", "content": content, "file_type": "markdown"})

        # Recursively read other files
        for file_path in skill_path.rglob("*"):
            if file_path.is_file() and file_path.name.lower() != "skill.md" and not file_path.name.startswith("."):
                try:
                    rel_path = file_path.relative_to(skill_path)

                    # Simple binary file check (try reading as utf-8)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            file_content = f.read()

                        files.append(
                            {
                                "path": str(rel_path),
                                "file_name": file_path.name,
                                "content": file_content,
                                "file_type": self._detect_file_type(file_path),
                            }
                        )
                    except UnicodeDecodeError:
                        # Skip binary files
                        continue
                except Exception:
                    continue

        # Check if exists
        try:
            existing_skill = await self.get_skill_by_name(name, current_user_id=owner_id)
        except Exception:
            existing_skill = None

        if existing_skill:
            return await self.update_skill(
                skill_id=existing_skill.id,
                current_user_id=owner_id,
                name=name,
                description=description,
                files=files,
                is_public=is_public,
            )
        else:
            return await self.create_skill(
                created_by_id=owner_id,
                name=name,
                description=description,
                content=body,
                files=files,
                owner_id=owner_id,
                is_public=is_public,
            )

    async def list_security_scans(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
    ):
        """List security scan history for a skill."""
        return await self.security_service.list_scans(skill_id, current_user_id, limit=limit, after_id=after_id)

    async def get_latest_security_scan(self, skill_id: uuid.UUID, current_user_id: str):
        """Get latest security scan for a skill."""
        return await self.security_service.get_latest_scan(skill_id, current_user_id)

    async def get_security_scan(self, scan_id: uuid.UUID, current_user_id: str):
        """Get a security scan by id."""
        return await self.security_service.get_scan(scan_id, current_user_id)

    async def rescan_skill(self, skill_id: uuid.UUID, current_user_id: str):
        """Run a manual security rescan for persisted skill content."""
        return await self.security_service.rescan_existing_skill(skill_id, current_user_id)

    def _detect_file_type(self, file_path: Union[str, Path]) -> str:
        """Simple file type detection"""
        if isinstance(file_path, str):
            file_path = Path(file_path)

        suffix = file_path.suffix.lower()
        if suffix == ".py":
            return "python"
        elif suffix == ".md":
            return "markdown"
        elif suffix == ".json":
            return "json"
        elif suffix == ".yaml" or suffix == ".yml":
            return "yaml"
        else:
            return "text"

    async def _attach_latest_version(self, skill):
        """Attach latest_version string to skill for API response."""
        ver_repo = SkillVersionRepository(self.db)
        latest = await ver_repo.get_latest(skill.id)
        skill.latest_version = latest.version if latest else None
        return skill
