"""
JoySafeter sandbox services.

Merged from sandbox_manager.py, joysafeter_sandbox_state_machine.py, and the
sandbox_service.py shim (v1 cleanup consolidation):
  - JoySafeterSandboxStateMachine / InvalidSandboxTransition — status FSM
  - JoySafeterSandboxService — sandbox pool + lifecycle management
  - SandboxService — backwards-compatible alias of JoySafeterSandboxService
"""

from __future__ import annotations

# ruff: noqa: E402 — sections merged verbatim; imports intentionally follow their banners
# ============================================================================
# joysafeter_sandbox_state_machine.py
# ============================================================================
import uuid
from typing import Any, Optional, cast

from sqlalchemy import CursorResult, and_, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
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
    "creating": {"provisioning", "idle", "stopped", "error", "destroyed"},
    "provisioning": {"idle", "stopped", "error", "destroyed"},
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
        sandbox_id: uuid.UUID,
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

    async def claim_pool_for_session(self, sandbox: JoySafeterSandbox, session_id: uuid.UUID) -> JoySafeterSandbox:
        self._validate_transition(sandbox.status, "provisioning")
        sandbox.status = "provisioning"
        sandbox.chat_session_id = session_id
        sandbox.last_used_at = utc_now()
        await self.db.commit()
        await self.db.refresh(sandbox)
        return sandbox

    async def complete_task(self, sandbox_id: uuid.UUID, task_id: uuid.UUID, new_status: str) -> bool:
        self._validate_status(new_status)
        current_status = await self._current_status(sandbox_id)
        if current_status is None:
            return False
        if current_status in ("destroyed", "stopping", "stopped"):
            return False
        self._validate_transition(current_status, new_status)

        values: dict = {
            "status": new_status,
            "last_task_id": task_id,
            "last_used_at": utc_now(),
        }
        # Same idle_since bookkeeping as transition() — keep these in lockstep
        # so any path that lands the sandbox in idle stamps a fresh window.
        if new_status == "idle" and current_status != "idle":
            values["idle_since"] = utc_now()
        elif new_status != "idle" and current_status == "idle":
            values["idle_since"] = None

        result = await self.db.execute(
            sa_update(JoySafeterSandbox)
            .where(
                and_(
                    JoySafeterSandbox.id == sandbox_id,
                    JoySafeterSandbox.status == current_status,
                    JoySafeterSandbox.status.notin_(["destroyed", "stopping", "stopped"]),
                )
            )
            .values(**values)
        )
        await self.db.commit()
        return cast(CursorResult[Any], result).rowcount > 0

    async def _current_status(self, sandbox_id: uuid.UUID) -> Optional[str]:
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

The legacy ``SandboxManagerService`` / ``get_sandbox_handle`` / in-process
``SandboxPool`` / ``PydanticSandboxAdapter`` cluster was removed along with
the old DispatchService / ExecutionOrchestrator chain.
"""


from datetime import timedelta

from sqlalchemy import func, update


class JoySafeterSandboxService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.state_machine = JoySafeterSandboxStateMachine(db)

    async def create_sandbox(
        self,
        image: str,
        provider: str = "docker",
        config: Optional[dict] = None,
        chat_session_id: Optional[uuid.UUID] = None,
        workspace_path: Optional[str] = None,
        external_id: Optional[str] = None,
        sandbox_id: Optional[uuid.UUID] = None,
        status: str = "creating",
        project_id: Optional[str] = None,
    ) -> JoySafeterSandbox:
        kwargs: dict = dict(
            provider=provider,
            status=status,
            image=image,
            config=config or {},
            chat_session_id=chat_session_id,
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

    async def get_sandbox(self, sandbox_id: uuid.UUID) -> Optional[JoySafeterSandbox]:
        result = await self.db.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id))
        return result.scalar_one_or_none()

    async def get_sandbox_by_external_id(self, external_id: str) -> Optional[JoySafeterSandbox]:
        result = await self.db.execute(
            select(JoySafeterSandbox).where(
                and_(
                    JoySafeterSandbox.external_id == external_id,
                    JoySafeterSandbox.destroyed_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_sandboxes(
        self, limit: int = 20, after_id: Optional[uuid.UUID] = None, project_id: Optional[str] = None
    ) -> tuple[list[JoySafeterSandbox], bool]:
        q = select(JoySafeterSandbox).where(JoySafeterSandbox.destroyed_at.is_(None))
        if project_id is not None:
            q = q.where(JoySafeterSandbox.project_id == project_id)
        if after_id:
            q = q.where(JoySafeterSandbox.id < after_id)
        q = q.order_by(JoySafeterSandbox.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        sandboxes = list(result.scalars().all())
        has_more = len(sandboxes) > limit
        return sandboxes[:limit], has_more

    async def update_status_cas(
        self,
        sandbox_id: uuid.UUID,
        expected_status: str,
        new_status: str,
    ) -> bool:
        return await self.state_machine.transition(
            sandbox_id,
            new_status,
            expected_status=expected_status,
        )

    async def touch(self, sandbox_id: uuid.UUID, task_id: Optional[uuid.UUID] = None) -> None:
        values: dict = {"last_used_at": utc_now()}
        if task_id:
            values["last_task_id"] = task_id
        await self.db.execute(update(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id).values(**values))
        await self.db.commit()

    async def mark_bridge_disconnected(self, sandbox_id: uuid.UUID) -> None:
        """Record that the runner→orchestrator gRPC bridge has dropped.

        The fallback sweeper uses ``disconnected_at`` (plus a grace window)
        to reap sandboxes whose runner crashed before it could send a clean
        RunnerIdle. We only stamp once: a follow-up disconnect that arrives
        while disconnected_at is still set is a no-op.
        """
        await self.db.execute(
            update(JoySafeterSandbox)
            .where(
                and_(
                    JoySafeterSandbox.id == sandbox_id,
                    JoySafeterSandbox.disconnected_at.is_(None),
                )
            )
            .values(disconnected_at=utc_now())
        )
        await self.db.commit()

    async def mark_bridge_connected(self, sandbox_id: uuid.UUID) -> None:
        """Clear the disconnect marker on a successful runner reconnect."""
        await self.db.execute(
            update(JoySafeterSandbox).where(JoySafeterSandbox.id == sandbox_id).values(disconnected_at=None)
        )
        await self.db.commit()

    async def find_by_session(self, session_id: uuid.UUID) -> Optional[JoySafeterSandbox]:
        result = await self.db.execute(
            select(JoySafeterSandbox)
            .where(
                and_(
                    JoySafeterSandbox.chat_session_id == session_id,
                    JoySafeterSandbox.destroyed_at.is_(None),
                    JoySafeterSandbox.status.in_(
                        ["idle", "running", "creating", "provisioning", "stopped", "stopping", "error"]
                    ),
                )
            )
            .order_by(JoySafeterSandbox.last_used_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def claim_from_pool(self, image: str, session_id: uuid.UUID) -> Optional[JoySafeterSandbox]:
        result = await self.db.execute(
            select(JoySafeterSandbox)
            .where(
                and_(
                    JoySafeterSandbox.status == "pooled",
                    JoySafeterSandbox.image == image,
                )
            )
            .order_by(JoySafeterSandbox.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        sandbox = result.scalar_one_or_none()
        if not sandbox:
            return None
        return await self.state_machine.claim_pool_for_session(sandbox, session_id)

    async def stop_sandbox(self, sandbox_id: uuid.UUID) -> bool:
        return await self.update_status_cas(sandbox_id, "idle", "stopping")

    async def update_status(self, sandbox_id: uuid.UUID, status: str) -> None:
        await self.state_machine.transition(sandbox_id, status)

    async def mark_destroyed(self, sandbox_id: uuid.UUID) -> None:
        await self.state_machine.transition(sandbox_id, "destroyed", mark_destroyed=True)

    async def mark_destroyed_cas(self, sandbox_id: uuid.UUID, expected_status: str) -> bool:
        return await self.state_machine.transition(
            sandbox_id,
            "destroyed",
            expected_status=expected_status,
            mark_destroyed=True,
        )

    async def update_status_and_config(self, sandbox_id: uuid.UUID, status: str, config: dict) -> None:
        await self.state_machine.transition(sandbox_id, status, config=config, touch=True)

    async def list_idle_expired(self, timeout_seconds: int) -> list:
        cutoff = utc_now() - timedelta(seconds=timeout_seconds)
        result = await self.db.execute(
            select(JoySafeterSandbox).where(
                and_(
                    JoySafeterSandbox.status == "idle",
                    JoySafeterSandbox.last_used_at < cutoff,
                )
            )
        )
        return list(result.scalars().all())

    async def list_pool_stale(self, max_age_seconds: int) -> list:
        cutoff = utc_now() - timedelta(seconds=max_age_seconds)
        result = await self.db.execute(
            select(JoySafeterSandbox).where(
                and_(
                    JoySafeterSandbox.status == "pooled",
                    JoySafeterSandbox.created_at < cutoff,
                )
            )
        )
        return list(result.scalars().all())

    async def count_pool_by_provider_image(self, provider: str, image: str) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(JoySafeterSandbox)
            .where(
                and_(
                    JoySafeterSandbox.status == "pooled",
                    JoySafeterSandbox.provider == provider,
                    JoySafeterSandbox.image == image,
                )
            )
        )
        return result.scalar_one()

    async def list_all_pooled(self) -> list:
        result = await self.db.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.status == "pooled"))
        return list(result.scalars().all())

    async def list_provisioning(self) -> list:
        result = await self.db.execute(select(JoySafeterSandbox).where(JoySafeterSandbox.status == "provisioning"))
        return list(result.scalars().all())

    async def complete_task(self, sandbox_id: uuid.UUID, task_id: uuid.UUID, status: str) -> bool:
        return await self.state_machine.complete_task(sandbox_id, task_id, status)

    async def list_stopping(self, timeout_seconds: int) -> list:
        cutoff = utc_now() - timedelta(seconds=timeout_seconds)
        result = await self.db.execute(
            select(JoySafeterSandbox).where(
                and_(
                    JoySafeterSandbox.status == "stopping",
                    JoySafeterSandbox.last_used_at < cutoff,
                )
            )
        )
        return list(result.scalars().all())

    async def list_stopped_expired(self, max_age_seconds: int) -> list:
        cutoff = utc_now() - timedelta(seconds=max_age_seconds)
        result = await self.db.execute(
            select(JoySafeterSandbox).where(
                and_(
                    JoySafeterSandbox.status.in_(["stopped", "error"]),
                    JoySafeterSandbox.last_used_at < cutoff,
                )
            )
        )
        return list(result.scalars().all())


# Backwards-compatible alias (was sandbox_service.py)
SandboxService = JoySafeterSandboxService
