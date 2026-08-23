"""
JoySafeter sandbox services.

Contains the sandbox state machine and database lifecycle service:
  - JoySafeterSandboxStateMachine / InvalidSandboxTransition — status FSM
  - SandboxService — sandbox pool + lifecycle management
"""

from __future__ import annotations

# ruff: noqa: E402 — sections merged verbatim; imports intentionally follow their banners
# ============================================================================
# joysafeter_sandbox_state_machine.py
# ============================================================================
from typing import Any, Optional, cast

from sqlalchemy import CursorResult, and_, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.pagination import apply_created_at_desc_cursor
from app.joysafeter_shared.ids import AgentId, SandboxId, SessionId
from app.joysafeter_shared.utils.datetime import utc_now

SANDBOX_STATUSES = frozenset(
    {
        "creating",
        "provisioning",
        "pooled",
        "idle",
        "running",
        "stopping",
        "stopped",
        "error",
        "destroyed",
    }
)

SANDBOX_TERMINAL_STATUSES = frozenset({"destroyed"})

SANDBOX_TRANSITIONS: dict[str, set[str]] = {
    "creating": {"provisioning", "pooled", "idle", "stopped", "error", "destroyed"},
    "provisioning": {"idle", "stopping", "stopped", "error", "destroyed"},
    "pooled": {"provisioning", "stopped", "destroyed"},
    "idle": {"idle", "running", "stopping", "stopped", "error", "destroyed"},
    "running": {"idle", "stopped", "error", "destroyed"},
    "stopping": {"idle", "stopped", "error", "destroyed"},
    "stopped": {"provisioning", "destroyed"},
    "error": {"destroyed"},
    "destroyed": set(),
}


class InvalidSandboxTransition(ValueError):
    pass


class JoySafeterSandboxStateMachine:
    """Centralized DB state transitions for joysafeter sandboxes."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def transition(
        self,
        sandbox_id: SandboxId,
        new_status: str,
        expected_status: Optional[str] = None,
        config: Optional[dict] = None,
        mark_destroyed: bool = False,
        touch: bool = False,
    ) -> bool:
        self._validate_status(new_status)
        current_status = await self._current_status(sandbox_id)
        if current_status is None:
            return False
        if expected_status is not None and current_status != expected_status:
            return False
        self._validate_transition(current_status, new_status)

        values: dict = {"status": new_status}
        if config is not None:
            values["config"] = config
        if mark_destroyed:
            values["destroyed_at"] = utc_now()
        if touch:
            values["last_used_at"] = utc_now()
        # idle_since is the idle-sweep's authoritative timestamp. Stamp it
        # whenever we *enter* idle (from any non-idle status) and clear it
        # whenever we leave idle, so the sweeper sees a fresh window every
        # time the sandbox really becomes idle, and never sees a stale
        # window for a sandbox that's busy. This decouples the sweeper from
        # last_used_at (which used to be touched on every heartbeat and
        # caused row bloat on long-running sandboxes).
        if new_status == "idle" and current_status != "idle":
            values["idle_since"] = utc_now()
        elif new_status != "idle" and current_status == "idle":
            values["idle_since"] = None

        conditions = [
            JoySafeterSandbox.id == sandbox_id,
            JoySafeterSandbox.status == current_status,
        ]

        result = await self.db.execute(sa_update(JoySafeterSandbox).where(and_(*conditions)).values(**values))
        await self.db.commit()
        return cast(CursorResult[Any], result).rowcount > 0

    async def _current_status(self, sandbox_id: SandboxId) -> Optional[str]:
        result = await self.db.execute(select(JoySafeterSandbox.status).where(JoySafeterSandbox.id == sandbox_id))
        return result.scalar_one_or_none()

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in SANDBOX_STATUSES:
            raise InvalidSandboxTransition(f"Unknown sandbox status: {status}")

    @staticmethod
    def _validate_transition(from_status: str, to_status: str) -> None:
        JoySafeterSandboxStateMachine._validate_status(from_status)
        JoySafeterSandboxStateMachine._validate_status(to_status)
        if from_status == to_status:
            return
        if to_status not in SANDBOX_TRANSITIONS[from_status]:
            raise InvalidSandboxTransition(f"Cannot transition sandbox from '{from_status}' to '{to_status}'")


# ============================================================================
# sandbox_manager.py
# ============================================================================

"""JoySafeter sandbox lifecycle service.

The active sandbox dispatch path is:
    orchestrator gRPC ↔ sandbox-runner (Rust)
This service only owns the JoySafeterSandbox database record — state
machine transitions, bridge connect/disconnect markers, pool claims, and
list queries used by the reaper sweepers in orchestrator-rs.

Runtime dispatch stays in the Rust orchestrator; this service only manages
database state and lifecycle queries.
"""


from datetime import timedelta


class SandboxService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.state_machine = JoySafeterSandboxStateMachine(db)

    async def create_sandbox(
        self,
        image: str,
        provider: str = "docker",
        config: Optional[dict] = None,
        chat_session_id: Optional[SessionId] = None,
        workspace_path: Optional[str] = None,
        external_id: Optional[str] = None,
        sandbox_id: Optional[SandboxId] = None,
        status: str = "creating",
        project_id: Optional[str] = None,
    ) -> JoySafeterSandbox:
        if chat_session_id is not None:
            raise ValueError(
                "Session-bound sandbox creation is owned by the Rust orchestrator "
                "(create_session_bound_sandbox_guarded); the Python domain service "
                "only creates unbound/pooled sandboxes"
            )
        kwargs: dict = dict(
            provider=provider,
            status=status,
            image=image,
            config=config or {},
            workspace_path=workspace_path,
        )
        if sandbox_id is not None:
            kwargs["id"] = sandbox_id
        if external_id is not None:
            kwargs["external_id"] = external_id
        if project_id is not None:
            kwargs["project_id"] = project_id
        sandbox = JoySafeterSandbox(**kwargs)
        self.db.add(sandbox)
        await self.db.commit()
        await self.db.refresh(sandbox)
        return sandbox

    async def get_sandbox(
        self,
        sandbox_id: SandboxId,
        project_id: Optional[str] = None,
    ) -> Optional[JoySafeterSandbox]:
        conditions = [JoySafeterSandbox.id == sandbox_id]
        if project_id is not None:
            conditions.append(JoySafeterSandbox.project_id == project_id)
        result = await self.db.execute(select(JoySafeterSandbox).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def list_sandboxes(
        self, limit: int = 20, after_id: Optional[SandboxId] = None, project_id: Optional[str] = None
    ) -> tuple[list[JoySafeterSandbox], bool]:
        q = select(JoySafeterSandbox).where(JoySafeterSandbox.destroyed_at.is_(None))
        if project_id is not None:
            q = q.where(JoySafeterSandbox.project_id == project_id)
        q = apply_created_at_desc_cursor(q, JoySafeterSandbox, after_id).limit(limit + 1)
        result = await self.db.execute(q)
        sandboxes = list(result.scalars().all())
        has_more = len(sandboxes) > limit
        return sandboxes[:limit], has_more

    async def update_status_cas(
        self,
        sandbox_id: SandboxId,
        expected_status: str,
        new_status: str,
    ) -> bool:
        return await self.state_machine.transition(
            sandbox_id,
            new_status,
            expected_status=expected_status,
        )

    async def find_by_session(
        self, session_id: SessionId, project_id: Optional[str] = None
    ) -> Optional[JoySafeterSandbox]:
        conditions = [
            JoySafeterSandbox.chat_session_id == session_id,
            JoySafeterSandbox.destroyed_at.is_(None),
            JoySafeterSandbox.status.in_(
                ["idle", "running", "creating", "provisioning", "stopped", "stopping", "error"]
            ),
        ]
        if project_id is not None:
            from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession

            conditions.append(
                select(JoySafeterSession.id)
                .where(
                    JoySafeterSession.id == session_id,
                    JoySafeterSession.project_id == project_id,
                )
                .exists()
            )
        result = await self.db.execute(
            select(JoySafeterSandbox).where(and_(*conditions)).order_by(JoySafeterSandbox.last_used_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def list_active_for_agent(
        self, agent_id: AgentId, project_id: Optional[str] = None
    ) -> list[JoySafeterSandbox]:
        from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession

        conditions = [
            JoySafeterSession.agent_id == agent_id,
            JoySafeterSandbox.destroyed_at.is_(None),
            JoySafeterSandbox.status != "destroyed",
        ]
        if project_id is not None:
            conditions.append(JoySafeterSession.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterSandbox)
            .join(JoySafeterSession, JoySafeterSandbox.chat_session_id == JoySafeterSession.id)
            .where(and_(*conditions))
        )
        return list(result.scalars().all())

    async def stop_sandbox(self, sandbox_id: SandboxId, project_id: Optional[str] = None) -> bool:
        if project_id is not None and await self.get_sandbox(sandbox_id, project_id=project_id) is None:
            return False
        return await self.update_status_cas(sandbox_id, "idle", "stopping")

    async def update_status(self, sandbox_id: SandboxId, status: str) -> None:
        await self.state_machine.transition(sandbox_id, status)

    async def mark_destroyed_after_runtime_ack(
        self,
        sandbox_id: SandboxId,
        expected_status: str,
        expected_external_id: Optional[str],
    ) -> bool:
        self.state_machine._validate_status(expected_status)
        if expected_status != "destroyed":
            self.state_machine._validate_transition(expected_status, "destroyed")

        external_id_conditions = [JoySafeterSandbox.external_id == expected_external_id]
        if not expected_external_id:
            external_id_conditions = [or_(JoySafeterSandbox.external_id.is_(None), JoySafeterSandbox.external_id == "")]

        result = await self.db.execute(
            sa_update(JoySafeterSandbox)
            .where(
                and_(
                    JoySafeterSandbox.id == sandbox_id,
                    JoySafeterSandbox.status == expected_status,
                    JoySafeterSandbox.destroyed_at.is_(None),
                    *external_id_conditions,
                )
            )
            .values(
                status="destroyed",
                destroyed_at=utc_now(),
                updated_at=utc_now(),
                idle_since=None,
            )
        )
        await self.db.commit()
        if cast(CursorResult[Any], result).rowcount > 0:
            return True

        current = await self.db.execute(
            select(
                JoySafeterSandbox.status,
                JoySafeterSandbox.external_id,
                JoySafeterSandbox.destroyed_at,
            ).where(JoySafeterSandbox.id == sandbox_id)
        )
        row = current.one_or_none()
        if row is None:
            return False
        status, external_id, destroyed_at = row
        expected = expected_external_id or ""
        return status == "destroyed" and (external_id or "") == expected and destroyed_at is not None

    async def list_idle_expired(self, timeout_seconds: int) -> list:
        cutoff = utc_now() - timedelta(seconds=timeout_seconds)
        result = await self.db.execute(
            select(JoySafeterSandbox).where(
                and_(
                    JoySafeterSandbox.status == "idle",
                    JoySafeterSandbox.destroyed_at.is_(None),
                    JoySafeterSandbox.idle_since.isnot(None),
                    JoySafeterSandbox.idle_since < cutoff,
                )
            )
        )
        return list(result.scalars().all())
