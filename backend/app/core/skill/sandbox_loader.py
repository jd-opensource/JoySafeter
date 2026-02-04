"""Skill loader for sandbox environments.

This module provides functionality to load skill files from the database
into sandbox file systems (e.g., Docker containers) for agent execution.
"""

import uuid
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Optional

from deepagents.backends.protocol import BackendProtocol
from loguru import logger

from app.core.skill.exceptions import (
    SkillFileWriteError,
    SkillNotFoundError,
    SkillPermissionDeniedError,
)
from app.utils.path_utils import sanitize_skill_name

if TYPE_CHECKING:
    from app.models.skill import Skill
    from app.services.skill_service import SkillService


class SkillSandboxLoader:
    """Loads skill files into sandbox file systems.

    This class handles the transfer of skill files from the database
    to sandbox environments, organizing them in a structured way
    for agent access.

    Features:
    - ✅ Loads skills from database with permission checking
    - ✅ Writes skill files to sandbox file system
    - ✅ Organizes files by skill name in configurable base directory
    - ✅ Handles file path conflicts and errors gracefully
    - ✅ Supports both pre-loading and on-demand loading
    - ✅ Supports Docker and Filesystem backend types with configurable paths

    Example:
        ```python
        from app.core.skill.sandbox_loader import SkillSandboxLoader
        from deepagents.backends.filesystem import FilesystemBackend

        backend = FilesystemBackend(root_dir="/workspace")
        loader = SkillSandboxLoader(skill_service, user_id="user123")

        # Pre-load skills
        await loader.load_skills_to_sandbox(
            skill_ids=[uuid1, uuid2],
            backend=backend
        )

        # With custom path
        loader = SkillSandboxLoader(
            skill_service,
            user_id="user123",
            skills_base_dir="/custom/skills/path"
        )
        ```
    """

    # Default base directory (can be overridden via constructor or backend config)
    DEFAULT_SKILLS_BASE_DIR = "/workspace/skills"

    # Paths that should be ignored for filesystem backends to avoid read-only filesystem errors
    FILESYSTEM_FORBIDDEN_PATHS = {"/workspace/skills"}

    def __init__(
        self,
        skill_service: "SkillService",
        user_id: Optional[str] = None,
        skills_base_dir: Optional[str] = None,
    ):
        """Initialize SkillSandboxLoader.

        Args:
            skill_service: SkillService instance for database operations
            user_id: User ID for permission checking (defaults to None)
            skills_base_dir: Base directory for skills (defaults to None, will auto-detect from backend)
        """
        self.skill_service = skill_service
        self.user_id = user_id
        self._skills_base_dir = skills_base_dir

    async def load_skill_to_sandbox(
        self,
        skill_id: uuid.UUID,
        backend: BackendProtocol,
        user_id: Optional[str] = None,
        skills_base_dir: Optional[str] = None,
    ) -> bool:
        """Load a single skill into the sandbox.

        Args:
            skill_id: UUID of the skill to load
            backend: Sandbox backend instance
            user_id: User ID for permission checking (overrides instance user_id)
            skills_base_dir: Base directory for skills (overrides instance setting)

        Returns:
            True if skill was loaded successfully, False otherwise
        """
        effective_user_id = user_id or self.user_id

        try:
            # Load skill from database with permission check
            skill = await self.skill_service.get_skill(
                skill_id=skill_id,
                current_user_id=effective_user_id,
            )

            if not skill:
                raise SkillNotFoundError(f"Skill {skill_id} not found or access denied")

            # Write skill files to sandbox
            return await self._write_skill_files(skill, backend, skills_base_dir=skills_base_dir)

        except SkillNotFoundError as e:
            logger.warning(f"Skill {skill_id} not found or access denied: {e}")
            return False
        except SkillPermissionDeniedError as e:
            logger.warning(f"Permission denied for skill {skill_id}: {e}")
            return False
        except SkillFileWriteError as e:
            logger.error(f"Failed to write skill files for {skill_id}: {e}", exc_info=True)
            return False
        except Exception as e:
            # Unknown exception, log full traceback
            logger.error(f"Unexpected error loading skill {skill_id} to sandbox: {e}", exc_info=True)
            return False

    async def load_skills_to_sandbox(
        self,
        skill_ids: list[uuid.UUID],
        backend: BackendProtocol,
        user_id: Optional[str] = None,
        skills_base_dir: Optional[str] = None,
    ) -> dict[uuid.UUID, bool]:
        """Load multiple skills into the sandbox.

        Args:
            skill_ids: List of skill UUIDs to load
            backend: Sandbox backend instance
            user_id: User ID for permission checking (overrides instance user_id)
            skills_base_dir: Base directory for skills (overrides instance setting)

        Returns:
            Dictionary mapping skill_id to success status (True/False)
        """
        results: dict[uuid.UUID, bool] = {}

        logger.info(f"Loading {len(skill_ids)} skills to sandbox...")

        for skill_id in skill_ids:
            success = await self.load_skill_to_sandbox(
                skill_id=skill_id,
                backend=backend,
                user_id=user_id,
                skills_base_dir=skills_base_dir,
            )
            results[skill_id] = success

        successful = sum(1 for v in results.values() if v)
        logger.info(f"Loaded {successful}/{len(skill_ids)} skills to sandbox. Failed: {len(skill_ids) - successful}")

        return results

    @staticmethod
    def _detect_backend_type(backend: BackendProtocol) -> str:
        """Detect backend type for path configuration.

        Args:
            backend: Backend instance implementing BackendProtocol

        Returns:
            Backend type string: "docker", "filesystem", or "unknown"
        """
        # Check for PydanticSandboxAdapter (Docker backend)
        try:
            from app.core.agent.backends.pydantic_adapter import PydanticSandboxAdapter

            if isinstance(backend, PydanticSandboxAdapter):
                logger.debug(f"[detect_backend_type] Detected Docker backend: {type(backend).__name__}")
                return "docker"
        except ImportError:
            pass

        # Check for FilesystemBackend
        if (
            hasattr(backend, "root_dir")
            or hasattr(backend, "_root_dir")
            or hasattr(backend, "cwd")
            or "Filesystem" in type(backend).__name__
        ):
            logger.debug(
                f"[detect_backend_type] Detected Filesystem backend: {type(backend).__name__}, "
                f"root_dir={getattr(backend, 'root_dir', 'MISSING')}, "
                f"_root_dir={getattr(backend, '_root_dir', 'MISSING')}, "
                f"cwd={getattr(backend, 'cwd', 'MISSING')}"
            )
            return "filesystem"

        # Unknown backend type
        logger.warning(
            f"[detect_backend_type] Unknown backend type: {type(backend).__name__}, has_root_dir={hasattr(backend, 'root_dir')}"
        )
        return "unknown"

    @staticmethod
    def _resolve_override_path(override_dir: Optional[str], backend_type: str) -> Optional[str]:
        """Resolve path from explicit override_dir parameter (Priority 1).

        Args:
            override_dir: Optional override directory (highest priority)
            backend_type: Detected backend type

        Returns:
            Override directory path if valid, None if should be ignored or not provided
        """
        if not override_dir:
            return None

        # Check if override_dir should be ignored for filesystem backends
        if SkillSandboxLoader._should_ignore_override_path(override_dir, backend_type):
            logger.warning(
                f"[resolve_skills_base_dir] IGNORING override_dir {override_dir!r} for filesystem backend "
                f"to avoid read-only filesystem errors - will use default logic instead"
            )
            return None

        logger.debug(f"[resolve_skills_base_dir] Using override_dir: {override_dir!r}")
        return override_dir

    @staticmethod
    def _resolve_instance_path(instance_dir: Optional[str]) -> Optional[str]:
        """Resolve path from instance-level setting (Priority 2).

        Args:
            instance_dir: Optional instance-level directory setting

        Returns:
            Instance directory path if provided, None otherwise
        """
        return instance_dir

    @staticmethod
    def _resolve_backend_path(backend: BackendProtocol) -> Optional[str]:
        """Resolve path from backend's skills_path attribute (Priority 3).

        Args:
            backend: Backend instance implementing BackendProtocol

        Returns:
            Backend's skills_path if available, None otherwise
        """
        if hasattr(backend, "skills_path") and backend.skills_path:
            path = backend.skills_path
            return str(path) if path is not None else None
        return None

    @staticmethod
    def _resolve_node_config_path(backend: BackendProtocol) -> Optional[str]:
        """Resolve path from node config skills_path (Priority 4).

        Args:
            backend: Backend instance implementing BackendProtocol

        Returns:
            Node config skills_path if available, None otherwise
        """
        if not hasattr(backend, "node_config"):
            return None

        node_config = backend.node_config
        if isinstance(node_config, dict):
            config = node_config.get("config", {})
            if isinstance(config, dict) and config.get("skills_path"):
                path = config.get("skills_path")
                return str(path) if path is not None else None
        return None

    @staticmethod
    def _resolve_default_path(backend_type: str, backend_class_name: str) -> str:
        """Resolve default path based on backend type (Priority 5).

        Args:
            backend_type: Detected backend type ("filesystem", "docker", or "unknown")
            backend_class_name: Name of the backend class for logging

        Returns:
            Default skills base directory path
        """
        if backend_type == "filesystem":
            logger.warning(
                f"[resolve_skills_base_dir] FORCE USING RELATIVE PATH 'skills' for filesystem backend "
                f"to avoid read-only filesystem errors. backend_class={backend_class_name}"
            )
            return "skills"
        elif backend_type == "docker":
            # Docker container path
            return SkillSandboxLoader.DEFAULT_SKILLS_BASE_DIR
        else:
            # Unknown backend, use default
            logger.warning(
                f"[resolve_skills_base_dir] UNKNOWN backend type {backend_class_name}, "
                f"detected_type={backend_type}, "
                f"using default skills path: {SkillSandboxLoader.DEFAULT_SKILLS_BASE_DIR}"
            )
            return SkillSandboxLoader.DEFAULT_SKILLS_BASE_DIR

    @staticmethod
    def _should_ignore_override_path(override_dir: str, backend_type: str) -> bool:
        """Check if override_dir should be ignored for filesystem backends.

        This prevents writing to read-only filesystem paths that would cause errors.

        Args:
            override_dir: The override directory path to check
            backend_type: The detected backend type ("filesystem", "docker", or "unknown")

        Returns:
            True if the override_dir should be ignored, False otherwise
        """
        return backend_type == "filesystem" and override_dir in SkillSandboxLoader.FILESYSTEM_FORBIDDEN_PATHS

    @staticmethod
    def resolve_skills_base_dir(
        backend: BackendProtocol,
        override_dir: Optional[str] = None,
        instance_dir: Optional[str] = None,
    ) -> str:
        """Resolve skills base directory with priority order (static method).

        This is a unified method for resolving skills path that can be used
        by both SkillSandboxLoader and SkillsManager.

        Priority (highest to lowest):
        1. Explicit override_dir parameter
        2. Instance-level instance_dir setting (if provided)
        3. Backend's skills_path attribute (if available)
        4. Node config skills_path (if backend has node_config attribute)
        5. Default path based on backend type

        Args:
            backend: Backend instance implementing BackendProtocol
            override_dir: Optional override directory (highest priority)
            instance_dir: Optional instance-level directory setting

        Returns:
            Skills base directory path
        """
        # Detect backend type once at the beginning and cache it
        backend_type = SkillSandboxLoader._detect_backend_type(backend)
        backend_class_name = type(backend).__name__

        # DEBUG: Log all parameters and backend info
        logger.debug(
            f"[resolve_skills_base_dir] override_dir={override_dir!r}, "
            f"instance_dir={instance_dir!r}, "
            f"backend_class={backend_class_name}, "
            f"backend_type={backend_type}"
        )

        # Try each priority level in order, return first non-None result
        path = (
            SkillSandboxLoader._resolve_override_path(override_dir, backend_type)
            or SkillSandboxLoader._resolve_instance_path(instance_dir)
            or SkillSandboxLoader._resolve_backend_path(backend)
            or SkillSandboxLoader._resolve_node_config_path(backend)
            or SkillSandboxLoader._resolve_default_path(backend_type, backend_class_name)
        )

        return path

    def _get_skills_base_dir(self, backend: BackendProtocol, override_dir: Optional[str] = None) -> str:
        """Get skills base directory with priority order.

        This method delegates to the static resolve_skills_base_dir method,
        passing the instance-level skills_base_dir setting.

        Args:
            backend: Backend instance implementing BackendProtocol
            override_dir: Optional override directory (highest priority)

        Returns:
            Skills base directory path
        """
        return self.resolve_skills_base_dir(
            backend=backend,
            override_dir=override_dir,
            instance_dir=self._skills_base_dir,
        )

    async def _write_skill_files(
        self,
        skill: "Skill",
        backend: BackendProtocol,
        skills_base_dir: Optional[str] = None,
    ) -> bool:
        """Write skill files to sandbox file system.

        Files are organized as:
        {skills_base_dir}/{skill_name}/
            ├── SKILL.md
            ├── file1.py
            └── subdir/
                └── file2.py

        Uses BackendProtocol.write() which automatically creates parent directories.

        Args:
            skill: Skill object with files relationship loaded
            backend: Backend instance implementing BackendProtocol
            skills_base_dir: Base directory for skills (optional override)

        Returns:
            True if all files were written successfully, False otherwise
        """
        if not skill.files:
            logger.warning(f"Skill '{skill.name}' has no files to load")
            return True  # Not an error, just no files

        # Get effective skills base directory
        effective_base_dir = self._get_skills_base_dir(backend, override_dir=skills_base_dir)

        # Calculate skill directory using PurePosixPath for POSIX-style paths
        skill_dir_path = PurePosixPath(effective_base_dir) / self._sanitize_skill_name(skill.name)
        skill_dir = str(skill_dir_path)

        # Check if backend supports write_overwrite (for Docker sandbox with potential container reuse)
        # If available, use it to avoid file existence conflicts
        use_overwrite = hasattr(backend, "write_overwrite")
        if use_overwrite:
            logger.debug(f"Backend supports write_overwrite, will use overwrite mode for skill '{skill.name}'")

        # Write each file
        # BackendProtocol.write() automatically creates parent directories
        success_count = 0
        write_errors = []

        for skill_file in skill.files:
            if not skill_file.content:
                logger.debug(f"Skipping file {skill_file.path} (no content)")
                continue

            # Construct full path in sandbox using PurePosixPath
            file_path = str(skill_dir_path / skill_file.path)

            # Write file (use overwrite mode if available to handle existing files)
            try:
                if use_overwrite:
                    write_result = backend.write_overwrite(file_path, skill_file.content)
                else:
                    write_result = backend.write(file_path, skill_file.content)

                if write_result and hasattr(write_result, "error") and write_result.error:
                    error_msg = write_result.error
                    write_errors.append(f"{file_path}: {error_msg}")
                    logger.error(f"Failed to write file {file_path} for skill '{skill.name}': {error_msg}")
                else:
                    success_count += 1
                    logger.debug(f"Wrote file {file_path} for skill '{skill.name}'")
            except Exception as e:
                write_errors.append(f"{file_path}: {str(e)}")
                logger.error(
                    f"Failed to write file {file_path} for skill '{skill.name}': {e}",
                    exc_info=True,
                )

        if success_count == 0:
            error_summary = "; ".join(write_errors[:3])  # Show first 3 errors
            if len(write_errors) > 3:
                error_summary += f" ... and {len(write_errors) - 3} more errors"
            raise SkillFileWriteError(f"No files were written for skill '{skill.name}'. Errors: {error_summary}")

        logger.info(f"Loaded skill '{skill.name}': {success_count}/{len(skill.files)} files written to {skill_dir}")
        return True

    @staticmethod
    def _sanitize_skill_name(name: str) -> str:
        """Sanitize skill name for use in file paths.

        Args:
            name: Original skill name

        Returns:
            Sanitized name safe for file system use
        """
        return sanitize_skill_name(name)

    def get_skill_path_in_sandbox(
        self,
        skill_name: str,
        backend: Optional[BackendProtocol] = None,
        skills_base_dir: Optional[str] = None,
    ) -> str:
        """Get the expected path for a skill in the sandbox.

        Args:
            skill_name: Name of the skill
            backend: Optional backend instance for path detection
            skills_base_dir: Optional base directory override

        Returns:
            Full path where the skill files should be located (POSIX style)
        """
        sanitized_name = self._sanitize_skill_name(skill_name)

        # Get effective base directory
        if backend:
            effective_base_dir = self._get_skills_base_dir(backend, override_dir=skills_base_dir)
        elif skills_base_dir:
            effective_base_dir = skills_base_dir
        elif self._skills_base_dir:
            effective_base_dir = self._skills_base_dir
        else:
            effective_base_dir = self.DEFAULT_SKILLS_BASE_DIR

        skill_path = PurePosixPath(effective_base_dir) / sanitized_name
        return str(skill_path)
