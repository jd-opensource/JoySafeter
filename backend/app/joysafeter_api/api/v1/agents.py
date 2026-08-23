from typing import Any, Optional, cast

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.model_connection_summary import (
    load_model_connection_summaries,
    maybe_credential_id,
    normalize_agent_model,
)
from app.joysafeter_application.agents import compose_agent_application
from app.joysafeter_domain.agents import split_agent_assets
from app.joysafeter_domain.credentials.references import snapshot_model_credential_id
from app.joysafeter_domain.schemas.base import CursorPaginatedResponse as PaginatedResponse
from app.joysafeter_domain.schemas.joysafeter_agent import (
    AgentVersionResponse,
)
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterAgentResponse as AgentResponse,
)
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterCreateAgentRequest as CreateAgentRequest,
)
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterUpdateAgentRequest as UpdateAgentRequest,
)
from app.joysafeter_domain.schemas.joysafeter_credential import ModelCredentialSummary
from app.joysafeter_domain.schemas.joysafeter_session import SessionResponse
from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterTaskResponse as TaskResponse
from app.joysafeter_domain.services.joysafeter_session_service import SessionService
from app.joysafeter_shared.common.app_errors import (
    AppError,
    NotFoundError,
    ResourceConflictError,
)
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.ids import AgentId, SessionId

router = APIRouter(tags=["joysafeter-agents"])


def _agent_not_found_error(agent_id: AgentId) -> AppError:
    return NotFoundError(
        code="AGENT_NOT_FOUND",
        message="Agent not found",
        data={"agent_id": str(agent_id)},
        user_action="refresh",
    )


def _agent_to_response(agent, *, model_connection: ModelCredentialSummary | None = None) -> AgentResponse:
    skills, agents, commands = split_agent_assets(agent.skills or [])
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        engine_kind=agent.engine_kind,
        model=cast(Any, normalize_agent_model(agent.model)),
        system=agent.system_prompt,
        description=agent.description,
        metadata=agent.metadata_,
        env=agent.env,
        mcp_servers=agent.mcp_servers,
        skills=cast(Any, skills),
        agents=cast(Any, agents),
        commands=cast(Any, commands),
        tools=agent.tools,
        multiagent=agent.multiagent,
        version=agent.version,
        environment_ref=agent.environment_ref,
        model_credential_id=agent.model_credential_id,
        model_connection=model_connection,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        archived_at=agent.archived_at,
    )


async def _agent_model_connection(
    db: AsyncSession,
    agent,
    *,
    project_id: str | None,
) -> ModelCredentialSummary | None:
    if not agent.model_credential_id:
        return None
    summaries = await load_model_connection_summaries(
        db,
        [agent.model_credential_id],
        project_id=project_id,
    )
    return summaries.get(agent.model_credential_id)


@router.post("", status_code=201)
async def create_agent(
    req: CreateAgentRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> AgentResponse:
    agent = await compose_agent_application(db).commands.create_agent(req, project_id=auth_ctx.project_id)
    return _agent_to_response(
        agent,
        model_connection=await _agent_model_connection(db, agent, project_id=auth_ctx.project_id),
    )


@router.get("")
async def list_agents(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[AgentId] = Query(None),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[AgentResponse]:
    agents, has_more = await compose_agent_application(db).queries.list_agents(
        limit, after_id, include_archived=include_archived, project_id=auth_ctx.project_id
    )

    model_connections = await load_model_connection_summaries(
        db,
        (agent.model_credential_id for agent in agents),
        project_id=auth_ctx.project_id,
    )
    data = [
        _agent_to_response(agent, model_connection=model_connections.get(agent.model_credential_id)) for agent in agents
    ]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{agent_id}")
async def get_agent(
    agent_id: AgentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> AgentResponse:
    agent = await compose_agent_application(db).queries.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise _agent_not_found_error(agent_id)
    return _agent_to_response(
        agent,
        model_connection=await _agent_model_connection(db, agent, project_id=auth_ctx.project_id),
    )


@router.post("/{agent_id}")
async def update_agent(
    req: UpdateAgentRequest,
    agent_id: AgentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> AgentResponse:
    agent = await compose_agent_application(db).commands.update_agent(
        agent_id,
        req,
        project_id=auth_ctx.project_id,
    )
    if not agent:
        raise _agent_not_found_error(agent_id)

    return _agent_to_response(
        agent,
        model_connection=await _agent_model_connection(db, agent, project_id=auth_ctx.project_id),
    )


@router.get("/{agent_id}/delete_preview")
async def delete_agent_preview(
    agent_id: AgentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> dict[str, int]:
    """Counts of data that will be removed when the agent is deleted.

    Powers the frontend delete-confirmation dialog. Returns exact counts of
    sessions, active tasks, and versions tied to the agent.
    """
    counts = await compose_agent_application(db).queries.count_delete_preview(
        agent_id,
        project_id=auth_ctx.project_id,
    )
    if counts is None:
        raise _agent_not_found_error(agent_id)
    sessions, tasks, versions, triggers = counts
    return {"sessions": sessions, "tasks": tasks, "versions": versions, "triggers": triggers}


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: AgentId,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> None:
    ok = await compose_agent_application(db).lifecycle.delete_with_cleanup(
        agent_id,
        force=force,
        project_id=auth_ctx.project_id,
    )
    if not ok:
        raise _agent_not_found_error(agent_id)


@router.post("/{agent_id}/archive", status_code=200)
async def archive_agent(
    agent_id: AgentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    application = compose_agent_application(db)
    agent = await application.queries.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise _agent_not_found_error(agent_id)
    try:
        archived, archived_session_ids = await application.lifecycle.archive_agent_with_sessions(
            agent_id,
            project_id=auth_ctx.project_id,
        )
    except ValueError as e:
        raise ResourceConflictError(
            code="AGENT_ACTIVE_TASKS",
            message=str(e),
            data={"agent_id": str(agent_id)},
            retryable=True,
            user_action="retry",
        ) from e
    if not archived:
        raise _agent_not_found_error(agent_id)
    return {
        "status": "archived",
        "archived_sessions": len(archived_session_ids),
    }


@router.post("/{agent_id}/unarchive", status_code=200)
async def unarchive_agent(
    agent_id: AgentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    restored = await compose_agent_application(db).lifecycle.restore_agent(
        agent_id,
        project_id=auth_ctx.project_id,
    )
    if not restored:
        raise _agent_not_found_error(agent_id)
    return {"status": "active"}


@router.get("/{agent_id}/tasks")
async def list_agent_tasks(
    agent_id: AgentId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> list[TaskResponse]:
    queries = compose_agent_application(db).queries
    agent = await queries.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise _agent_not_found_error(agent_id)
    tasks = await queries.list_active_tasks_for_agent(agent_id, project_id=auth_ctx.project_id)
    return [TaskResponse.model_validate(t) for t in tasks]


@router.get("/{agent_id}/sessions")
async def list_agent_sessions(
    agent_id: AgentId,
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[SessionId] = Query(None),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[SessionResponse]:
    agent = await compose_agent_application(db).queries.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise _agent_not_found_error(agent_id)
    session_svc = SessionService(db)
    sessions, has_more = await session_svc.list_sessions_by_agent(
        agent_id,
        limit,
        after_id,
        project_id=auth_ctx.project_id,
        include_archived=include_archived,
    )

    model_connections = await load_model_connection_summaries(
        db,
        [agent.model_credential_id],
        project_id=auth_ctx.project_id,
    )
    model_connection = model_connections.get(agent.model_credential_id)

    def _session_to_response(session) -> SessionResponse:
        from app.joysafeter_api.api.v1.sessions import _session_to_response as _s2r

        return _s2r(session, agent, model_connection=model_connection)

    data = [_session_to_response(s) for s in sessions]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{agent_id}/versions")
async def list_agent_versions(
    agent_id: AgentId,
    limit: int = Query(20, ge=1, le=100),
    before_version: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[AgentVersionResponse]:
    queries = compose_agent_application(db).queries
    agent = await queries.get_agent(agent_id, project_id=auth_ctx.project_id)
    if not agent:
        raise _agent_not_found_error(agent_id)
    versions, has_more = await queries.list_versions(
        agent_id,
        limit,
        before_version,
        project_id=auth_ctx.project_id,
    )
    model_connections = await load_model_connection_summaries(
        db,
        (
            maybe_credential_id(snapshot_model_credential_id(v.snapshot))
            for v in versions
            if isinstance(v.snapshot, dict)
        ),
        project_id=auth_ctx.project_id,
    )
    data = []
    for version in versions:
        item = AgentVersionResponse.model_validate(version)
        snapshot = dict(item.snapshot)
        credential_id = maybe_credential_id(snapshot_model_credential_id(snapshot))
        snapshot["model"] = normalize_agent_model(snapshot.get("model"))
        model_connection = model_connections.get(credential_id)
        if model_connection is not None:
            snapshot["model_connection"] = model_connection.model_dump(mode="json")
        item.snapshot = snapshot
        data.append(item)
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )
