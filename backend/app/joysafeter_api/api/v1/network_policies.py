from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, and_, cast, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_sandbox_network_policy import JoySafeterSandboxNetworkPolicy
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_platform_admin,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.ids import SandboxId, SessionId, TaskId

router = APIRouter(tags=["joysafeter-network-policies"])


class NetworkPolicyStatusResponse(BaseModel):
    sandbox_id: SandboxId
    session_id: Optional[SessionId] = None
    task_id: Optional[TaskId] = None
    project_id: Optional[str] = None
    session_title: Optional[str] = None
    agent_name: Optional[str] = None
    sandbox_status: str
    networking_status: str
    networking_policy_hash: Optional[str] = None
    networking_policy_version: int = 0
    networking_last_error: Optional[str] = None
    networking_ready_at: Optional[datetime] = None
    sandbox_updated_at: datetime
    latest_policy_status: Optional[str] = None
    latest_policy_error: Optional[str] = None
    latest_policy_nack_reason: Optional[str] = None
    latest_policy_updated_at: Optional[datetime] = None
    rendered_summary: dict[str, Any] = Field(default_factory=dict)


class NetworkPolicyListResponse(BaseModel):
    data: list[NetworkPolicyStatusResponse]
    total: int
    page: int
    page_size: int


def _row_to_response(row: Any) -> NetworkPolicyStatusResponse:
    return NetworkPolicyStatusResponse(
        sandbox_id=row.sandbox_id,
        session_id=row.session_id,
        task_id=row.task_id,
        project_id=row.project_id,
        session_title=row.session_title,
        agent_name=row.agent_name,
        sandbox_status=row.sandbox_status,
        networking_status=row.networking_status,
        networking_policy_hash=row.networking_policy_hash,
        networking_policy_version=row.networking_policy_version or 0,
        networking_last_error=row.networking_last_error,
        networking_ready_at=row.networking_ready_at,
        sandbox_updated_at=row.sandbox_updated_at,
        latest_policy_status=row.latest_policy_status,
        latest_policy_error=row.latest_policy_error,
        latest_policy_nack_reason=row.latest_policy_nack_reason,
        latest_policy_updated_at=row.latest_policy_updated_at,
        rendered_summary=row.rendered_summary or {},
    )


def _latest_policy_subquery():
    return select(
        JoySafeterSandboxNetworkPolicy.sandbox_id.label("sandbox_id"),
        JoySafeterSandboxNetworkPolicy.task_id.label("task_id"),
        JoySafeterSandboxNetworkPolicy.status.label("latest_policy_status"),
        JoySafeterSandboxNetworkPolicy.last_error.label("latest_policy_error"),
        JoySafeterSandboxNetworkPolicy.last_nack_reason.label("latest_policy_nack_reason"),
        JoySafeterSandboxNetworkPolicy.rendered_summary_json.label("rendered_summary"),
        JoySafeterSandboxNetworkPolicy.updated_at.label("latest_policy_updated_at"),
        func.row_number()
        .over(
            partition_by=JoySafeterSandboxNetworkPolicy.sandbox_id,
            order_by=JoySafeterSandboxNetworkPolicy.policy_version.desc(),
        )
        .label("rn"),
    ).subquery()


def _base_status_query(project_id: Optional[str] = None):
    latest_policy = _latest_policy_subquery()
    columns = [
        JoySafeterSandbox.id.label("sandbox_id"),
        JoySafeterSandbox.chat_session_id.label("session_id"),
        latest_policy.c.task_id,
        JoySafeterSandbox.project_id,
        JoySafeterSession.title.label("session_title"),
        JoySafeterAgent.name.label("agent_name"),
        JoySafeterSandbox.status.label("sandbox_status"),
        JoySafeterSandbox.networking_status,
        JoySafeterSandbox.networking_policy_hash,
        JoySafeterSandbox.networking_policy_version,
        JoySafeterSandbox.networking_last_error,
        JoySafeterSandbox.networking_ready_at,
        JoySafeterSandbox.updated_at.label("sandbox_updated_at"),
        latest_policy.c.latest_policy_status,
        latest_policy.c.latest_policy_error,
        latest_policy.c.latest_policy_nack_reason,
        latest_policy.c.latest_policy_updated_at,
        latest_policy.c.rendered_summary,
    ]
    query = (
        select(*columns)
        .select_from(JoySafeterSandbox)
        .outerjoin(JoySafeterSession, JoySafeterSession.id == JoySafeterSandbox.chat_session_id)
        .outerjoin(JoySafeterAgent, JoySafeterAgent.id == JoySafeterSession.agent_id)
        .outerjoin(latest_policy, and_(latest_policy.c.sandbox_id == JoySafeterSandbox.id, latest_policy.c.rn == 1))
        .where(JoySafeterSandbox.destroyed_at.is_(None))
    )
    if project_id:
        query = query.where(JoySafeterSandbox.project_id == project_id)
    return query


@router.get("/diagnostics")
async def list_network_policy_diagnostics(
    status: Optional[str] = Query(None),
    query: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_platform_admin),
) -> NetworkPolicyListResponse:
    stmt = _base_status_query()
    count_stmt = select(func.count()).select_from(JoySafeterSandbox).where(JoySafeterSandbox.destroyed_at.is_(None))
    if status and status != "all":
        stmt = stmt.where(JoySafeterSandbox.networking_status == status)
        count_stmt = count_stmt.where(JoySafeterSandbox.networking_status == status)
    if query:
        like = f"%{query.strip()}%"
        stmt = stmt.where(
            or_(
                cast(JoySafeterSandbox.id, String).ilike(like),
                cast(JoySafeterSandbox.chat_session_id, String).ilike(like),
                JoySafeterSandbox.networking_last_error.ilike(like),
            )
        )
        count_stmt = count_stmt.where(
            or_(
                cast(JoySafeterSandbox.id, String).ilike(like),
                cast(JoySafeterSandbox.chat_session_id, String).ilike(like),
                JoySafeterSandbox.networking_last_error.ilike(like),
            )
        )
    total = int(await db.scalar(count_stmt) or 0)
    result = await db.execute(
        stmt.order_by(desc(JoySafeterSandbox.updated_at)).offset((page - 1) * page_size).limit(page_size)
    )
    return NetworkPolicyListResponse(
        data=[_row_to_response(row) for row in result.all()],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/sessions/{session_id}")
async def get_session_network_policy_status(
    session_id: SessionId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> Optional[NetworkPolicyStatusResponse]:
    result = await db.execute(
        _base_status_query(project_id=None if auth_ctx.is_super_user else auth_ctx.project_id)
        .where(JoySafeterSandbox.chat_session_id == session_id)
        .order_by(desc(JoySafeterSandbox.updated_at))
        .limit(1)
    )
    row = result.first()
    return _row_to_response(row) if row else None
