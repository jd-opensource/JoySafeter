from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_infrastructure.agents.sqlalchemy_repository import (
    SqlAlchemyAgentRepository,
    translate_agent_integrity_error,
)


@dataclass(slots=True)
class SqlAlchemyAgentUnitOfWork:
    db: AsyncSession
    agents: SqlAlchemyAgentRepository

    async def commit(self) -> None:
        try:
            await self.db.commit()
        except IntegrityError as exc:
            translate_agent_integrity_error(exc)
            raise

    async def rollback(self) -> None:
        await self.db.rollback()


__all__ = ["SqlAlchemyAgentUnitOfWork"]
