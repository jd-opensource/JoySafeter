from __future__ import annotations

from typing import Any, Optional

from app.joysafeter_domain.agents.assets import split_agent_assets
from app.joysafeter_domain.credentials.references import (
    build_agent_execution_snapshot,
    build_environment_execution_snapshot,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent


def build_environment_snapshot(environment: Any, *, environment_ref: Optional[str]) -> Optional[dict]:
    return build_environment_execution_snapshot(environment, environment_ref=environment_ref)


def build_agent_snapshot(
    agent: JoySafeterAgent,
    *,
    environment: Any = None,
    environment_ref: Optional[str] = None,
    version: Optional[int] = None,
) -> dict:
    skills, agents, commands = split_agent_assets(agent.skills or [])
    return build_agent_execution_snapshot(
        agent,
        environment=environment,
        environment_ref=environment_ref,
        version=version,
        split_assets=(skills, agents, commands),
    )
