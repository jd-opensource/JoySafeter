"""Adapter middleware: Convert database skills to deepagents SkillsMiddleware compatible format.

This adapter allows using deepagents SkillsMiddleware even when skills are stored in database
by loading them into a temporary StateBackend.
"""

from typing import TYPE_CHECKING, Any, List, Optional

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from loguru import logger

if TYPE_CHECKING:
    from deepagents.backends.protocol import BackendProtocol
    from deepagents.middleware.skills import SkillsMiddleware

from app.core.database import async_session_factory
from app.core.skill.sandbox_loader import SkillSandboxLoader
from app.services.skill_service import SkillService


class DatabaseSkillAdapter(AgentMiddleware):
    """Adapter: Load skills from database and convert to deepagents SkillsMiddleware format.

    This adapter creates a temporary StateBackend, loads skills from database into it,
    and then uses deepagents SkillsMiddleware to provide skill descriptions.

    Use this when you need skill descriptions injected but don't have a persistent backend.
    For better performance, use deepagents SkillsMiddleware directly with a persistent backend.
    """

    priority = 50  # Same priority as SkillsMiddleware

    def __init__(
        self,
        user_id: Optional[str] = None,
        skill_ids: Optional[List[Any]] = None,
        db_session_factory: Optional[Any] = None,
        backend_factory: Optional[Any] = None,
    ):
        """Initialize DatabaseSkillAdapter.

        Args:
            user_id: User ID to filter skills (defaults to None, loads all public skills)
            skill_ids: Optional list of specific skill UUIDs to load
            db_session_factory: Async database session factory (defaults to async_session_factory)
            backend_factory: Factory function to create backend (defaults to StateBackend)
        """
        self.user_id = user_id
        self.skill_ids = skill_ids
        self.db_session_factory = db_session_factory or async_session_factory
        self.backend_factory = backend_factory
        self._skills_middleware: Optional["SkillsMiddleware"] = None
        self._backend: Optional["BackendProtocol"] = None

    async def _ensure_skills_loaded(self, runtime):
        """Ensure skills are loaded into StateBackend and SkillsMiddleware is created."""
        if self._skills_middleware is not None:
            return

        try:
            from deepagents.backends.state import StateBackend
            from deepagents.middleware.skills import SkillsMiddleware
        except ImportError:
            logger.error(
                "deepagents.middleware.skills or deepagents.backends.state not available. "
                "DatabaseSkillAdapter requires deepagents to be installed."
            )
            return

        # Create temporary StateBackend if factory not provided
        if self.backend_factory is None:
            self.backend_factory = lambda rt: StateBackend(rt)

        # Create backend
        self._backend = self.backend_factory(runtime)

        # Load skills from database and write to backend
        try:
            async with self.db_session_factory() as db:
                skill_service = SkillService(db)
                loader = SkillSandboxLoader(
                    skill_service,
                    user_id=self.user_id,
                    # Use default path for StateBackend
                )

                # Get effective skills path from loader
                effective_skills_path = loader._get_skills_base_dir(self._backend)
                # Ensure path ends with / for SkillsMiddleware
                skills_source_path = effective_skills_path.rstrip("/") + "/"

                if self.skill_ids:
                    await loader.load_skills_to_sandbox(
                        self.skill_ids,
                        self._backend,
                        skills_base_dir=effective_skills_path,
                    )
                else:
                    skills = await skill_service.list_skills(
                        current_user_id=self.user_id,
                        include_public=True,
                    )
                    skill_ids = [s.id for s in skills]
                    if skill_ids:
                        await loader.load_skills_to_sandbox(
                            skill_ids,
                            self._backend,
                            skills_base_dir=effective_skills_path,
                        )

            # Create deepagents SkillsMiddleware with dynamic path
            self._skills_middleware = SkillsMiddleware(
                backend=self._backend,
                sources=[skills_source_path],
            )
            logger.debug("DatabaseSkillAdapter: Loaded skills into StateBackend and created SkillsMiddleware")
        except Exception as e:
            logger.error(
                f"DatabaseSkillAdapter: Failed to load skills: {e}",
                exc_info=True,
            )

    async def abefore_agent(self, state: AgentState, runtime, config) -> Optional[AgentState]:  # type: ignore[override]
        """Load skills and delegate to SkillsMiddleware."""
        await self._ensure_skills_loaded(runtime)
        if self._skills_middleware is None:
            return None
        result = await self._skills_middleware.abefore_agent(state, runtime, config)
        return result  # type: ignore[no-any-return]

    def before_agent(self, state: AgentState, runtime, config) -> Optional[AgentState]:  # type: ignore[override]
        """Sync version - delegates to async."""
        import asyncio

        try:
            asyncio.get_running_loop()
            # If loop is running, we can't use run_until_complete
            logger.warning("Event loop is running, skipping skill loading in before_agent")
            return None
        except RuntimeError:
            # No running loop, safe to use asyncio.run()
            return asyncio.run(self.abefore_agent(state, runtime, config))

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse:
        """Delegate to SkillsMiddleware if available."""
        if self._skills_middleware is None:
            result = handler(request)
            return result  # type: ignore[no-any-return]
        result = self._skills_middleware.wrap_model_call(request, handler)
        return result  # type: ignore[no-any-return]

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler,
    ) -> ModelResponse:
        """Async version - delegate to SkillsMiddleware if available."""
        if self._skills_middleware is None:
            result = await handler(request)
            return result  # type: ignore[no-any-return]
        result = await self._skills_middleware.awrap_model_call(request, handler)
        return result  # type: ignore[no-any-return]
