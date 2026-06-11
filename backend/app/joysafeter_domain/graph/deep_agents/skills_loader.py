"""Skills loader — preloads skills into sandbox backends.

Extracted from the original skills_manager.py with cleaner separation:
- resolve_skill_ids: parse and validate skill IDs
- preload_skills: load skills into backend with deduplication
"""

from __future__ import annotations

import uuid
from typing import Any, List, Optional, Set

from loguru import logger

from app.joysafeter_domain.graph.deep_agents import format_node_ctx

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
    *,
    node_label: Optional[str] = None,
    graph_name: Optional[str] = None,
    skill_port: Optional[Any] = None,
) -> List[uuid.UUID]:
    """Resolve raw skill config to validated UUIDs.

    Handles ["*"] (all user skills) and explicit UUID lists.
    """
    if not skill_ids_raw:
        return []

    ctx = format_node_ctx(node_label, graph_name)

    if len(skill_ids_raw) == 1 and skill_ids_raw[0] == "*":
        if skill_port:
            skills_list = await skill_port.list_skills(current_user_id=user_id, include_public=True)
        else:
            from app.joysafeter_shared.database import async_session_factory
            from app.joysafeter_domain.services.skill_service import SkillService

            async with async_session_factory() as db:
                skill_service = SkillService(db)
                skills_list = await skill_service.list_skills(
                    current_user_id=user_id,
                    include_public=True,
                )
        ids = [s.id for s in skills_list]
        logger.info(f"{LOG_PREFIX} Resolved ['*'] → {len(ids)} skills for {ctx}")
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
                logger.warning(f"{LOG_PREFIX} Invalid skill ID type: {type(sid)} for {ctx}")
        except ValueError:
            logger.warning(f"{LOG_PREFIX} Invalid skill UUID: {sid} for {ctx}")

    return valid_ids


async def preload_skills(
    skill_ids: List[uuid.UUID],
    backend: Any,
    user_id: Optional[str] = None,
    skills_path: Optional[str] = None,
    *,
    node_label: Optional[str] = None,
    graph_name: Optional[str] = None,
    skill_port: Optional[Any] = None,
) -> int:
    """Load skills into sandbox backend. Returns count of successfully loaded skills.

    Deduplicates: tracks which skills are already loaded per backend instance.
    """
    if not skill_ids:
        return 0

    ctx = format_node_ctx(node_label, graph_name)

    from deepagents.backends.protocol import BackendProtocol

    if not isinstance(backend, BackendProtocol):
        logger.warning(f"{LOG_PREFIX} Backend does not implement BackendProtocol (requested by {ctx})")
        return 0

    # Deduplication: skip already-loaded skills
    loaded_ids: Set[uuid.UUID] = getattr(backend, "_loaded_skill_ids", set())
    to_load = [sid for sid in skill_ids if sid not in loaded_ids]

    if not to_load:
        logger.debug(f"{LOG_PREFIX} All {len(skill_ids)} skills already loaded")
        return len(skill_ids)

    from app.joysafeter_shared.skill.sandbox_loader import SkillSandboxLoader

    try:
        if skill_port:
            loader = SkillSandboxLoader(
                skill_service=skill_port,
                user_id=user_id,
                skills_base_dir=skills_path,
            )
            results = await loader.load_skills_to_sandbox(
                skill_ids=to_load,
                backend=backend,
                user_id=user_id,
                skills_base_dir=skills_path,
            )
        else:
            from app.joysafeter_shared.database import async_session_factory
            from app.joysafeter_domain.services.skill_service import SkillService

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
            f"{LOG_PREFIX} Loaded {successful}/{len(to_load)} skills for {ctx} ({len(loaded_ids)} previously loaded)"
        )
        return successful

    except Exception as e:
        logger.error(f"{LOG_PREFIX} Skills preload failed for {ctx}: {e}")
        return 0


def get_skills_source_path(backend: Any, skills_path: Optional[str] = None) -> Optional[str]:
    """Get the effective skills source path for a backend."""
    try:
        from app.joysafeter_shared.skill.sandbox_loader import SkillSandboxLoader

        loader = SkillSandboxLoader(skill_service=None, user_id=None)  # type: ignore[arg-type]
        path = loader._get_skills_base_dir(backend, override_dir=skills_path)
        return path.rstrip("/") + "/" if path else None
    except Exception:
        return None
