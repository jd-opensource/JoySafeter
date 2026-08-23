from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_application.agents.command_service import AgentCommandService
from app.joysafeter_application.agents.lifecycle_service import AgentLifecycleService
from app.joysafeter_application.agents.query_service import AgentQueryService
from app.joysafeter_infrastructure.agents import (
    AgentCredentialBindingAdapter,
    AgentRuntimeAdapter,
    AgentTriggerLifecycleAdapter,
    SqlAlchemyAgentRepository,
    SqlAlchemyAgentUnitOfWork,
)


@dataclass(frozen=True, slots=True)
class AgentApplication:
    commands: AgentCommandService
    queries: AgentQueryService
    lifecycle: AgentLifecycleService


def compose_agent_application(db: AsyncSession) -> AgentApplication:
    repository = SqlAlchemyAgentRepository(db)
    uow = SqlAlchemyAgentUnitOfWork(db=db, agents=repository)
    return AgentApplication(
        commands=AgentCommandService(uow, AgentCredentialBindingAdapter(db)),
        queries=AgentQueryService(repository),
        lifecycle=AgentLifecycleService(
            uow,
            AgentRuntimeAdapter(db),
            AgentTriggerLifecycleAdapter(db),
        ),
    )
