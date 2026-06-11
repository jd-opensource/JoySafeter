import uuid
from typing import Optional

from sqlalchemy import and_, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.sandbox import JoySafeterSandbox
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

        conditions = [
            JoySafeterSandbox.id == sandbox_id,
            JoySafeterSandbox.status == current_status,
        ]

        result = await self.db.execute(
            sa_update(JoySafeterSandbox).where(and_(*conditions)).values(**values)
        )
        await self.db.commit()
        return result.rowcount > 0

    async def claim_pool_for_session(
        self, sandbox: JoySafeterSandbox, session_id: uuid.UUID
    ) -> JoySafeterSandbox:
        self._validate_transition(sandbox.status, "provisioning")
        sandbox.status = "provisioning"
        sandbox.chat_session_id = session_id
        sandbox.last_used_at = utc_now()
        await self.db.commit()
        await self.db.refresh(sandbox)
        return sandbox

    async def complete_task(
        self, sandbox_id: uuid.UUID, task_id: uuid.UUID, new_status: str
    ) -> bool:
        self._validate_status(new_status)
        current_status = await self._current_status(sandbox_id)
        if current_status is None:
            return False
        if current_status in ("destroyed", "stopping", "stopped"):
            return False
        self._validate_transition(current_status, new_status)

        result = await self.db.execute(
            sa_update(JoySafeterSandbox)
            .where(
                and_(
                    JoySafeterSandbox.id == sandbox_id,
                    JoySafeterSandbox.status == current_status,
                    JoySafeterSandbox.status.notin_(["destroyed", "stopping", "stopped"]),
                )
            )
            .values(
                status=new_status,
                last_task_id=task_id,
                last_used_at=utc_now(),
            )
        )
        await self.db.commit()
        return result.rowcount > 0

    async def _current_status(self, sandbox_id: uuid.UUID) -> Optional[str]:
        result = await self.db.execute(
            select(JoySafeterSandbox.status).where(JoySafeterSandbox.id == sandbox_id)
        )
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
            raise InvalidSandboxTransition(
                f"Cannot transition sandbox from '{from_status}' to '{to_status}'"
            )
