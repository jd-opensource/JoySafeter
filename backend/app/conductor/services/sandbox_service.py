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
        external_id: Optional[str] = None,
        sandbox_id: Optional[uuid.UUID] = None,
        status: str = "creating",
    ) -> ConductorSandbox:
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
        sandbox = ConductorSandbox(**kwargs)
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
    ) -> bool:
        result = await self.db.execute(
            update(ConductorSandbox)
            .where(
                and_(
                    ConductorSandbox.id == sandbox_id,
                    ConductorSandbox.status == expected_status,
                )
            )
            .values(status=new_status)
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
                        ["idle", "running", "creating", "provisioning", "stopped", "stopping", "error"]
                    ),
                )
            )
            .order_by(ConductorSandbox.last_used_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def claim_from_pool(
        self, image: str, session_id: uuid.UUID
    ) -> Optional[ConductorSandbox]:
        result = await self.db.execute(
            select(ConductorSandbox)
            .where(
                and_(
                    ConductorSandbox.status == "pooled",
                    ConductorSandbox.image == image,
                )
            )
            .order_by(ConductorSandbox.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        sandbox = result.scalar_one_or_none()
        if not sandbox:
            return None
        sandbox.status = "provisioning"
        sandbox.chat_session_id = session_id
        sandbox.last_used_at = utc_now()
        await self.db.commit()
        await self.db.refresh(sandbox)
        return sandbox

    async def stop_sandbox(self, sandbox_id: uuid.UUID) -> bool:
        return await self.update_status_cas(sandbox_id, "idle", "stopping")

    async def update_status(self, sandbox_id: uuid.UUID, status: str) -> None:
        await self.db.execute(
            update(ConductorSandbox)
            .where(ConductorSandbox.id == sandbox_id)
            .values(status=status)
        )
        await self.db.commit()

    async def mark_destroyed(self, sandbox_id: uuid.UUID) -> None:
        await self.db.execute(
            update(ConductorSandbox)
            .where(ConductorSandbox.id == sandbox_id)
            .values(status="destroyed", destroyed_at=utc_now())
        )
        await self.db.commit()

    async def update_status_and_config(
        self, sandbox_id: uuid.UUID, status: str, config: dict
    ) -> None:
        await self.db.execute(
            update(ConductorSandbox)
            .where(ConductorSandbox.id == sandbox_id)
            .values(status=status, config=config, last_used_at=utc_now())
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
            )
        )
        await self.db.commit()

    async def list_stopping(self, timeout_seconds: int) -> list:
        cutoff = utc_now() - timedelta(seconds=timeout_seconds)
        result = await self.db.execute(
            select(ConductorSandbox).where(
                and_(
                    ConductorSandbox.status == "stopping",
                    ConductorSandbox.last_used_at < cutoff,
                )
            )
        )
        return list(result.scalars().all())

    async def list_stopped_expired(self, max_age_seconds: int) -> list:
        cutoff = utc_now() - timedelta(seconds=max_age_seconds)
        result = await self.db.execute(
            select(ConductorSandbox).where(
                and_(
                    ConductorSandbox.status.in_(["stopped", "error"]),
                    ConductorSandbox.last_used_at < cutoff,
                )
            )
        )
        return list(result.scalars().all())
