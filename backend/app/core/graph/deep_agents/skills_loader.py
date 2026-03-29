"""Skills loader — preloads skills into sandbox backends.

Extracted from the original skills_manager.py with cleaner separation:
- resolve_skill_ids: parse and validate skill IDs
- preload_skills: load skills into backend with deduplication
"""

from __future__ import annotations

import uuid
from typing import Any, List, Optional, Set

from loguru import logger

LOG_PREFIX = "[SkillsLoader]"


def has_valid_skills(skill_ids_raw: Any) -> bool:
    """Check if skills configuration is valid and non-empty."""
    if not skill_ids_raw or not isinstance(skill_ids_raw, list):
        return False
    if len(skill_ids_raw) == 1 and skill_ids_raw[0] == "*":
        return True
    return len(skill_ids_raw) > 0


async def resolve_skill_ids(
    skill_ids_raw: List[Any],
    user_id: Optional[str] = None,
) -> List[uuid.UUID]:
    """Resolve raw skill config to validated UUIDs.

    Handles ["*"] (all user skills) and explicit UUID lists.
    """
    if not skill_ids_raw:
        return []

    # ["*"] means all skills for this user
    if len(skill_ids_raw) == 1 and skill_ids_raw[0] == "*":
        from app.core.database import async_session_factory
        from app.services.skill_service import SkillService

        async with async_session_factory() as db:
            skill_service = SkillService(db)
            skills_list = await skill_service.list_skills(
                current_user_id=user_id,
                include_public=True,
            )
            ids = [s.id for s in skills_list]
            logger.info(f"{LOG_PREFIX} Resolved ['*'] → {len(ids)} skills")
            return ids

    # Explicit UUIDs
    valid_ids: List[uuid.UUID] = []
    for sid in skill_ids_raw:
        try:
            if isinstance(sid, uuid.UUID):
                valid_ids.append(sid)
            elif isinstance(sid, str):
                valid_ids.append(uuid.UUID(sid))
            else:
                logger.warning(f"{LOG_PREFIX} Invalid skill ID type: {type(sid)}")
        except ValueError:
            logger.warning(f"{LOG_PREFIX} Invalid skill UUID: {sid}")

    return valid_ids


async def preload_skills(
    skill_ids: List[uuid.UUID],
    backend: Any,
    user_id: Optional[str] = None,
    skills_path: Optional[str] = None,
) -> int:
    """Load skills into sandbox backend. Returns count of successfully loaded skills.

    Deduplicates: tracks which skills are already loaded per backend instance.
    """
    if not skill_ids:
        return 0

    from deepagents.backends.protocol import BackendProtocol

    if not isinstance(backend, BackendProtocol):
        logger.warning(f"{LOG_PREFIX} Backend does not implement BackendProtocol")
        return 0

    # Deduplication: skip already-loaded skills
    loaded_ids: Set[uuid.UUID] = getattr(backend, "_loaded_skill_ids", set())
    to_load = [sid for sid in skill_ids if sid not in loaded_ids]

    if not to_load:
        logger.debug(f"{LOG_PREFIX} All {len(skill_ids)} skills already loaded")
        return len(skill_ids)

    from app.core.database import async_session_factory
    from app.core.skill.sandbox_loader import SkillSandboxLoader
    from app.services.skill_service import SkillService

    try:
        async with async_session_factory() as db:
            skill_service = SkillService(db)
            loader = SkillSandboxLoader(
                skill_service=skill_service,
                user_id=user_id,
                skills_base_dir=skills_path,
            )

            results = await loader.load_skills_to_sandbox(
                skill_ids=to_load,
                backend=backend,
                user_id=user_id,
                skills_base_dir=skills_path,
            )

            successful = sum(1 for v in results.values() if v)
            newly_loaded = {sid for sid, ok in results.items() if ok}

            if newly_loaded:
                setattr(backend, "_loaded_skill_ids", loaded_ids | newly_loaded)

            logger.info(
                f"{LOG_PREFIX} Loaded {successful}/{len(to_load)} skills "
                f"({len(loaded_ids)} previously loaded)"
            )
            return successful

    except Exception as e:
        logger.error(f"{LOG_PREFIX} Skills preload failed: {e}")
        return 0


def get_skills_source_path(backend: Any, skills_path: Optional[str] = None) -> Optional[str]:
    """Get the effective skills source path for a backend."""
    try:
        from app.core.skill.sandbox_loader import SkillSandboxLoader

        loader = SkillSandboxLoader(skill_service=None, user_id=None)
        path = loader._get_skills_base_dir(backend, override_dir=skills_path)
        return path.rstrip("/") + "/" if path else None
    except Exception:
        return None
