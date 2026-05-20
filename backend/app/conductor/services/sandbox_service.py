import uuid
from typing import Optional

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.conductor.models.sandbox import ConductorSandbox
from app.utils.datetime import utc_now


class SandboxService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_sandbox(
        self,
        image: str,
        provider: str = "docker",
        config: Optional[dict] = None,
        chat_session_id: Optional[uuid.UUID] = None,
        workspace_path: Optional[str] = None,
    ) -> ConductorSandbox:
        sandbox = ConductorSandbox(
            provider=provider,
            status="creating",
            image=image,
            config=config or {},
            chat_session_id=chat_session_id,
            workspace_path=workspace_path,
        )
        self.db.add(sandbox)
        await self.db.commit()
        await self.db.refresh(sandbox)
        return sandbox

    async def get_sandbox(self, sandbox_id: uuid.UUID) -> Optional[ConductorSandbox]:
        result = await self.db.execute(
            select(ConductorSandbox).where(ConductorSandbox.id == sandbox_id)
        )
        return result.scalar_one_or_none()

    async def list_sandboxes(
        self, limit: int = 20, after_id: Optional[uuid.UUID] = None
    ) -> tuple[list[ConductorSandbox], bool]:
        q = select(ConductorSandbox).where(
            ConductorSandbox.destroyed_at.is_(None)
        )
        if after_id:
            q = q.where(ConductorSandbox.id < after_id)
        q = q.order_by(ConductorSandbox.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        sandboxes = list(result.scalars().all())
        has_more = len(sandboxes) > limit
        return sandboxes[:limit], has_more

    async def update_status_cas(
        self,
        sandbox_id: uuid.UUID,
        expected_status: str,
        new_status: str,
        external_id: Optional[str] = None,
    ) -> bool:
        values: dict = {"status": new_status, "updated_at": utc_now()}
        if external_id is not None:
            values["external_id"] = external_id
        if new_status == "destroyed":
            values["destroyed_at"] = utc_now()
        result = await self.db.execute(
            update(ConductorSandbox)
            .where(
                and_(
                    ConductorSandbox.id == sandbox_id,
                    ConductorSandbox.status == expected_status,
                )
            )
            .values(**values)
        )
        await self.db.commit()
        return result.rowcount > 0

    async def touch(self, sandbox_id: uuid.UUID, task_id: Optional[uuid.UUID] = None) -> None:
        values: dict = {"last_used_at": utc_now()}
        if task_id:
            values["last_task_id"] = task_id
        await self.db.execute(
            update(ConductorSandbox)
            .where(ConductorSandbox.id == sandbox_id)
            .values(**values)
        )
        await self.db.commit()

    async def find_by_session(self, session_id: uuid.UUID) -> Optional[ConductorSandbox]:
        result = await self.db.execute(
            select(ConductorSandbox).where(
                and_(
                    ConductorSandbox.chat_session_id == session_id,
                    ConductorSandbox.status.in_(["running", "idle"]),
                )
            )
        )
        return result.scalar_one_or_none()

    async def claim_from_pool(self, session_id: uuid.UUID) -> Optional[ConductorSandbox]:
        result = await self.db.execute(
            select(ConductorSandbox)
            .where(ConductorSandbox.status == "pooled")
            .order_by(ConductorSandbox.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        sandbox = result.scalar_one_or_none()
        if not sandbox:
            return None
        sandbox.status = "running"
        sandbox.chat_session_id = session_id
        sandbox.last_used_at = utc_now()
        await self.db.commit()
        await self.db.refresh(sandbox)
        return sandbox

    async def stop_sandbox(self, sandbox_id: uuid.UUID) -> bool:
        sandbox = await self.get_sandbox(sandbox_id)
        if not sandbox or sandbox.destroyed_at:
            return False
        sandbox.status = "stopping"
        sandbox.updated_at = utc_now()
        await self.db.commit()
        return True
