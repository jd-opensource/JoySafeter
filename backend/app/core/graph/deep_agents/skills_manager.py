"""Skills manager for DeepAgents graph builder.

Manages skills preloading and path configuration.
"""

import uuid
from typing import Any, Optional

from loguru import logger

from app.core.skill.sandbox_loader import SkillSandboxLoader
from app.models.graph import GraphNode

LOG_PREFIX = "[SkillsManager]"


class DeepAgentsSkillsManager:
    """Manages skills for DeepAgents graph."""

    def __init__(self, user_id: Optional[str] = None):
        """Initialize skills manager.

        Args:
            user_id: User ID for permission checking
        """
        self.user_id = user_id

    @staticmethod
    def _is_use_all_skills(skill_ids_raw: Any) -> bool:
        """Check if config means 'use all skills available to the current user'."""
        if not skill_ids_raw or not isinstance(skill_ids_raw, list):
            return False
        return len(skill_ids_raw) == 1 and skill_ids_raw[0] == "*"

    @staticmethod
    def has_valid_skills_config(skill_ids_raw: Any) -> bool:
        """Check if skills configuration is valid and non-empty.

        Accepts either a list of skill UUIDs or the sentinel ["*"] for
        'use all skills available to the current user'.

        Args:
            skill_ids_raw: Raw skills configuration from node config

        Returns:
            True if skills are configured and valid
        """
        if not skill_ids_raw or not isinstance(skill_ids_raw, list):
            return False
        if DeepAgentsSkillsManager._is_use_all_skills(skill_ids_raw):
            return True
        return len(skill_ids_raw) > 0

    async def preload_skills_to_backend(
        self,
        node: GraphNode,
        backend: Any,
    ) -> None:
        """Pre-load skills into sandbox backend.

        Args:
            node: GraphNode containing skill configuration
            backend: Backend instance implementing BackendProtocol

        Raises:
            TypeError: If backend does not implement BackendProtocol
            ValueError: If skill configuration is invalid
            RuntimeError: If skill loading fails critically
        """
        from deepagents.backends.protocol import BackendProtocol

        if not isinstance(backend, BackendProtocol):
            raise TypeError(f"{LOG_PREFIX} Backend must implement BackendProtocol, got {type(backend).__name__}")

        data = node.data or {}
        config = data.get("config", {})
        node_label = data.get("label", "unknown")
        skill_ids_raw = config.get("skills")

        if not self.has_valid_skills_config(skill_ids_raw):
            if skill_ids_raw is not None and not isinstance(skill_ids_raw, list):
                raise ValueError(
                    f"{LOG_PREFIX} Invalid skills configuration for node '{node_label}': "
                    f"expected list, got {type(skill_ids_raw).__name__}"
                )
            return

        from app.core.database import async_session_factory
        from app.core.skill.sandbox_loader import SkillSandboxLoader
        from app.services.skill_service import SkillService

        try:
            async with async_session_factory() as db:
                skill_service = SkillService(db)

                # Resolve skill_ids: ["*"] -> all skills available to current user
                if self._is_use_all_skills(skill_ids_raw):
                    skills_list = await skill_service.list_skills(
                        current_user_id=self.user_id,
                        include_public=True,
                    )
                    skill_ids = [s.id for s in skills_list]
                    if not skill_ids:
                        logger.debug(
                            f"{LOG_PREFIX} No skills available for user (node '{node_label}'), skipping preload"
                        )
                        return
                    logger.info(
                        f"{LOG_PREFIX} Resolved skills: ['*'] -> {len(skill_ids)} skill(s) for node '{node_label}'"
                    )
                else:
                    skill_ids = []
                    invalid_ids = []
                    for sid in skill_ids_raw:
                        try:
                            if isinstance(sid, str):
                                skill_ids.append(uuid.UUID(sid))
                            elif isinstance(sid, uuid.UUID):
                                skill_ids.append(sid)
                            else:
                                invalid_ids.append(str(sid))
                        except ValueError as e:
                            invalid_ids.append(str(sid))
                            logger.warning(f"{LOG_PREFIX} Invalid skill UUID '{sid}': {e}")
                    if invalid_ids:
                        logger.warning(
                            f"{LOG_PREFIX} Skipping {len(invalid_ids)} invalid skill ID(s) for node "
                            f"'{node_label}': {', '.join(invalid_ids[:5])}"
                        )
                    if not skill_ids:
                        logger.warning(f"{LOG_PREFIX} No valid skill IDs found for node '{node_label}'")
                        return

                # Try to get skills_path from node config
                skills_path = config.get("skills_path")

                loader = SkillSandboxLoader(
                    skill_service=skill_service,
                    user_id=self.user_id,
                    skills_base_dir=skills_path,  # Pass path from config if available
                )

                results = await loader.load_skills_to_sandbox(
                    skill_ids=skill_ids,
                    backend=backend,
                    user_id=self.user_id,
                    skills_base_dir=skills_path,  # Also pass to method for override
                )

                successful = sum(1 for v in results.values() if v)
                failed = len(skill_ids) - successful

                try:
                    from app.core.skill.sandbox_loader import SkillSandboxLoader

                    # Get effective skills path from loader
                    effective_skills_path = loader._get_skills_base_dir(backend, override_dir=skills_path)
                    # Ensure path ends with / for diagnosis
                    source_path = effective_skills_path.rstrip("/") + "/"

                    # Check if diagnose_skills_in_backend method exists
                    if hasattr(SkillSandboxLoader, "diagnose_skills_in_backend"):
                        diagnosis = await SkillSandboxLoader.diagnose_skills_in_backend(
                            backend=backend,
                            source_path=source_path,
                        )
                    else:
                        # Skip diagnosis if method doesn't exist
                        diagnosis = {}

                    if diagnosis.get("errors"):
                        logger.warning(f"{LOG_PREFIX} Skills diagnosis found errors: {diagnosis['errors']}")

                    directories = diagnosis.get("directories", [])
                    skills_with_md = sum(1 for d in directories if d.get("has_skill_md", False))

                    if skills_with_md > 0:
                        logger.info(
                            f"{LOG_PREFIX} Skills diagnosis for node '{node_label}': "
                            f"{len(directories)} directories, "
                            f"{skills_with_md} with SKILL.md"
                        )
                except Exception as e:
                    logger.debug(f"{LOG_PREFIX} Failed to diagnose skills in backend: {e}", exc_info=True)

                if successful > 0:
                    logger.info(
                        f"{LOG_PREFIX} Pre-loaded {successful}/{len(skill_ids)} skills "
                        f"to backend for node '{node_label}'"
                    )

                if failed > 0:
                    logger.warning(
                        f"{LOG_PREFIX} Failed to pre-load {failed}/{len(skill_ids)} skills "
                        f"for node '{node_label}' "
                        f"(likely due to permission issues or missing skills)"
                    )

        except Exception as e:
            raise RuntimeError(
                f"{LOG_PREFIX} Failed to pre-load skills to sandbox for node '{node_label}': {e}",
            ) from e

    @staticmethod
    def get_skills_paths(
        has_skills: bool, backend: Optional[Any], skills_path: Optional[str] = None
    ) -> Optional[list[str]]:
        """Get skills paths if skills are configured and backend is available.

        This method uses SkillSandboxLoader.resolve_skills_base_dir() to resolve
        the skills path, ensuring consistency across the codebase.

        Args:
            has_skills: Whether skills are configured
            backend: Backend instance or None
            skills_path: Optional custom skills path from config (highest priority)

        Returns:
            Skills paths list or None
        """
        if not (has_skills and backend):
            return None

        # Use unified path resolution from SkillSandboxLoader
        effective_path = SkillSandboxLoader.resolve_skills_base_dir(
            backend=backend,
            override_dir=skills_path,
            instance_dir=None,  # SkillsManager doesn't have instance-level setting
        )

        # Ensure path ends with /
        if not effective_path.endswith("/"):
            effective_path = effective_path + "/"

        return [effective_path]
