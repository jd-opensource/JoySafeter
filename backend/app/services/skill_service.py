"""
Skill Service: Permission Check + CRUD
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from loguru import logger

from app.common.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.common.skill_permissions import check_skill_access
from app.core.skill.validators import (
    truncate_compatibility,
    truncate_description,
    validate_compatibility,
    validate_skill_description,
    validate_skill_name,
)
from app.core.skill.yaml_parser import (
    extract_metadata_from_frontmatter,
    is_system_file,
    is_valid_text_content,
    parse_skill_md,
    validate_file_extension,
)
from app.models.skill import Skill, SkillFile
from app.models.skill_collaborator import CollaboratorRole
from app.repositories.skill import SkillFileRepository, SkillRepository
from app.repositories.skill_version import SkillVersionRepository

from .base import BaseService


class SkillService(BaseService[Skill]):
    def __init__(self, db):
        super().__init__(db)
        self.repo = SkillRepository(db)
        self.file_repo = SkillFileRepository(db)

    async def list_skills(
        self,
        current_user_id: Optional[str] = None,
        include_public: bool = True,
        tags: Optional[List[str]] = None,
    ) -> List[Skill]:
        """Get Skills list"""
        result = await self.repo.list_by_user(
            user_id=current_user_id,
            include_public=include_public,
            tags=tags,
        )
        return list(result) if result is not None else []

    async def get_skill(
        self,
        skill_id: uuid.UUID,
        current_user_id: Optional[str] = None,
    ) -> Skill:
        """Get Skill details"""
        skill = await self.repo.get_with_files(skill_id)
        if not skill or not isinstance(skill, Skill):
            raise NotFoundException("Skill not found")

        # Permission check: collaborator-aware
        if current_user_id:
            await check_skill_access(
                self.db,
                skill,
                current_user_id,
                CollaboratorRole.viewer,
            )
        elif not skill.is_public:
            raise ForbiddenException("You don't have permission to access this skill")

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
            raise BadRequestException(f"Invalid skill name: {error}")

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
            raise BadRequestException(f"Skill name '{name}' already exists for this owner")

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
        )
        self.db.add(skill)
        await self.db.flush()
        await self.db.refresh(skill)

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
                invalid_list = "\n".join(f"  - {f}" for f in invalid_files)
                raise BadRequestException(
                    f"The following files cannot be imported (binary files or system files):\n{invalid_list}\n\n"
                    f"Skill import only supports text files (.py, .md, .json, .yaml, etc.)"
                )

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
        skill = await self.repo.get(skill_id)
        if not skill:
            raise NotFoundException("Skill not found")

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

        # Validate and update name if provided
        if name and name != skill.name:
            is_valid, error = validate_skill_name(name)
            if not is_valid:
                logger.warning(f"Invalid skill name rejected: {name!r} — {error}")
                raise BadRequestException(f"Invalid skill name: {error}")
            existing = await self.repo.get_by_name_and_owner(name, skill.owner_id)
            if existing:
                raise BadRequestException(f"Skill name '{name}' already exists for this owner")
            skill.name = name

        # Validate and update description if provided
        if description is not None:
            is_valid, error = validate_skill_description(description)
            if not is_valid:
                # Truncate if too long (warn but continue)
                logger.warning(f"Skill description exceeds 1024 characters, truncating: {error}")
                description = truncate_description(description)
            skill.description = description
        if content is not None:
            skill.content = content
        if tags is not None:
            skill.tags = tags
        if source_type is not None:
            skill.source_type = source_type
        if source_url is not None:
            skill.source_url = source_url
        if root_path is not None:
            skill.root_path = root_path
        if owner_id is not None:
            skill.owner_id = owner_id
        if is_public is not None:
            skill.is_public = is_public
        if license is not None:
            skill.license = license

        # Validate and update compatibility if provided
        if compatibility is not None:
            is_valid, error = validate_compatibility(compatibility)
            if not is_valid:
                # Truncate if too long (warn but continue)
                logger.warning(f"Skill compatibility exceeds 500 characters, truncating: {error}")
                compatibility = truncate_compatibility(compatibility)
            skill.compatibility = compatibility

        # Update metadata if provided
        if metadata is not None:
            # Ensure all values are strings (per spec)
            if isinstance(metadata, dict):
                skill.meta_data = {k: str(v) for k, v in metadata.items() if isinstance(k, str)}
            else:
                skill.meta_data = {}

        # Update allowed_tools if provided
        if allowed_tools is not None:
            if isinstance(allowed_tools, list):
                skill.allowed_tools = allowed_tools
            else:
                skill.allowed_tools = []

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
                invalid_list = "\n".join(f"  - {f}" for f in invalid_files)
                raise BadRequestException(
                    f"The following files cannot be imported (binary files or system files):\n{invalid_list}\n\n"
                    f"Skill import only supports text files (.py, .md, .json, .yaml, etc.)"
                )

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
        skill = await self.repo.get(skill_id)
        if not skill:
            raise NotFoundException("Skill not found")

        # Permission check: Only owner can delete
        if skill.owner_id != current_user_id:
            raise ForbiddenException("Only the owner can delete a skill")

        # Delete associated files
        await self.file_repo.delete_by_skill(skill_id)

        # Revoke all tokens bound to this skill
        from app.services.platform_token_service import PlatformTokenService

        token_service = PlatformTokenService(self.db)
        await token_service.revoke_by_resource("skill", str(skill_id))

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
        skill = await self.repo.get(skill_id)
        if not skill:
            raise NotFoundException("Skill not found")

        # Permission check: collaborator-aware (editor role)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            CollaboratorRole.editor,
        )

        # Check if it's a system file
        if is_system_file(path) or is_system_file(file_name):
            raise BadRequestException(f"File '{path}' is a system file and cannot be imported")

        # Validate content if provided
        if content is not None:
            is_valid, error_msg = is_valid_text_content(content)
            if not is_valid:
                raise BadRequestException(
                    f"File '{path}' {error_msg}. Skill import only supports text files (.py, .md, .json, .yaml, etc.)"
                )

        # Log warning for uncommon file extensions (but don't reject)
        if path:
            is_common, warning = validate_file_extension(path)
            if warning:
                logger.warning(f"Skill file warning: {warning}")

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
        await self.db.commit()
        await self.db.refresh(file_obj)

        # If adding/updating SKILL.md, sync metadata to skill
        if path == "SKILL.md" or file_name == "SKILL.md":
            await self._sync_skill_from_skill_md(skill, content)

        return file_obj

    async def delete_file(
        self,
        file_id: uuid.UUID,
        current_user_id: str,
    ) -> None:
        """Delete file"""
        file_obj = await self.file_repo.get(file_id)
        if not file_obj:
            raise NotFoundException("Skill file not found")

        skill = await self.repo.get(file_obj.skill_id)
        if not skill:
            raise NotFoundException("Skill not found")

        # Permission check: collaborator-aware (editor role)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            CollaboratorRole.editor,
        )

        await self.file_repo.delete(file_id)
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
            raise NotFoundException("Skill file not found")

        skill = await self.repo.get(file_obj.skill_id)
        if not skill:
            raise NotFoundException("Skill not found")

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
                raise BadRequestException(f"File '{path}' is a system file and cannot be imported")

            # Log warning for uncommon file extensions (but don't reject)
            is_common, warning = validate_file_extension(path)
            if warning:
                logger.warning(f"Skill file warning: {warning}")

        if content is not None:
            # Validate content
            is_valid, error_msg = is_valid_text_content(content)
            if not is_valid:
                raise BadRequestException(
                    f"File '{file_obj.path}' {error_msg}. Skill import only supports text files (.py, .md, .json, .yaml, etc.)"
                )

            file_obj.content = content
            file_obj.size = len(content) if content else 0
        if path is not None:
            file_obj.path = path
        if file_name is not None:
            file_obj.file_name = file_name

        await self.db.commit()
        await self.db.refresh(file_obj)

        # If updating SKILL.md, sync metadata to skill
        if file_obj.path == "SKILL.md" or file_obj.file_name == "SKILL.md":
            await self._sync_skill_from_skill_md(skill, file_obj.content)

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

        frontmatter, body = parse_skill_md(content)

        # Update skill fields from frontmatter
        if frontmatter.get("name"):
            skill.name = frontmatter["name"]
        if frontmatter.get("description"):
            skill.description = frontmatter["description"]
        if frontmatter.get("tags") and isinstance(frontmatter["tags"], list):
            skill.tags = frontmatter["tags"]
        if frontmatter.get("license"):
            skill.license = frontmatter["license"]

        # Update content with markdown body
        if body:
            skill.content = body.strip()

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

        from app.core.skill.yaml_parser import extract_metadata_from_frontmatter, parse_skill_md

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
