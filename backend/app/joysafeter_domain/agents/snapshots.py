from __future__ import annotations

from typing import Any, Optional

from app.joysafeter_domain.agents.assets import split_agent_assets
from app.joysafeter_domain.credentials.references import (
    build_agent_execution_snapshot,
    build_environment_execution_snapshot,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_shared.ids import EnvironmentId


def build_environment_snapshot(environment: Any) -> Optional[dict]:
    return build_environment_execution_snapshot(environment)


def build_agent_snapshot(
    agent: JoySafeterAgent,
    *,
    environment: Any = None,
    environment_id: Optional[EnvironmentId] = None,
    version: Optional[int] = None,
) -> dict:
    skills, agents, commands = split_agent_assets(agent.skills or [])
    return build_agent_execution_snapshot(
        agent,
        environment=environment,
        environment_id=environment_id,
        version=version,
        split_assets=(skills, agents, commands),
    )
