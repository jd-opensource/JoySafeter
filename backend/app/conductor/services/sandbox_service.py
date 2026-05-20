import uuid
from datetime import timedelta
from typing import Optional

from sqlalchemy import and_, func, select, update
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
            select(ConductorSandbox)
            .where(
                and_(
                    ConductorSandbox.chat_session_id == session_id,
                    ConductorSandbox.status.in_(
                        ["idle", "provisioning", "stopped", "stopping", "error"]
                    ),
                )
            )
            .order_by(ConductorSandbox.last_used_at.desc())
            .limit(1)
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

    async def update_status(self, sandbox_id: uuid.UUID, status: str) -> None:
        await self.db.execute(
            update(ConductorSandbox)
            .where(ConductorSandbox.id == sandbox_id)
            .values(status=status, updated_at=utc_now())
        )
        await self.db.commit()

    async def update_status_and_config(
        self, sandbox_id: uuid.UUID, status: str, config: dict
    ) -> None:
        await self.db.execute(
            update(ConductorSandbox)
            .where(ConductorSandbox.id == sandbox_id)
            .values(status=status, config=config, last_used_at=utc_now(), updated_at=utc_now())
        )
        await self.db.commit()

    async def list_idle_expired(self, timeout_seconds: int) -> list:
        cutoff = utc_now() - timedelta(seconds=timeout_seconds)
        result = await self.db.execute(
            select(ConductorSandbox).where(
                and_(
                    ConductorSandbox.status == "idle",
                    ConductorSandbox.last_used_at < cutoff,
                )
            )
        )
        return list(result.scalars().all())

    async def list_pool_stale(self, max_age_seconds: int) -> list:
        cutoff = utc_now() - timedelta(seconds=max_age_seconds)
        result = await self.db.execute(
            select(ConductorSandbox).where(
                and_(
                    ConductorSandbox.status == "pooled",
                    ConductorSandbox.created_at < cutoff,
                )
            )
        )
        return list(result.scalars().all())

    async def count_pool_by_provider_image(self, provider: str, image: str) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(ConductorSandbox)
            .where(
                and_(
                    ConductorSandbox.status == "pooled",
                    ConductorSandbox.provider == provider,
                    ConductorSandbox.image == image,
                )
            )
        )
        return result.scalar_one()

    async def list_all_pooled(self) -> list:
        result = await self.db.execute(
            select(ConductorSandbox)
            .where(ConductorSandbox.status == "pooled")
            .order_by(ConductorSandbox.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_provisioning(self) -> list:
        result = await self.db.execute(
            select(ConductorSandbox).where(ConductorSandbox.status == "provisioning")
        )
        return list(result.scalars().all())

    async def complete_task(
        self, sandbox_id: uuid.UUID, task_id: uuid.UUID, status: str
    ) -> None:
        await self.db.execute(
            update(ConductorSandbox)
            .where(ConductorSandbox.id == sandbox_id)
            .values(
                status=status,
                last_task_id=task_id,
                last_used_at=utc_now(),
                updated_at=utc_now(),
            )
        )
        await self.db.commit()

    async def list_stopping(self, timeout_seconds: int) -> list:
        cutoff = utc_now() - timedelta(seconds=timeout_seconds)
        result = await self.db.execute(
            select(ConductorSandbox).where(
                and_(
                    ConductorSandbox.status == "stopping",
                    ConductorSandbox.updated_at < cutoff,
                )
            )
        )
        return list(result.scalars().all())

    async def list_stopped_expired(self, max_age_seconds: int) -> list:
        cutoff = utc_now() - timedelta(seconds=max_age_seconds)
        result = await self.db.execute(
            select(ConductorSandbox).where(
                and_(
                    ConductorSandbox.status == "stopped",
                    ConductorSandbox.updated_at < cutoff,
                    ConductorSandbox.destroyed_at.is_(None),
                )
            )
        )
        return list(result.scalars().all())
