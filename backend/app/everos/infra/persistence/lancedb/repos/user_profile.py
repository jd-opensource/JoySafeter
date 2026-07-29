"""LanceDB repo singleton for the ``user_profile`` table."""

from __future__ import annotations

from lancedb import AsyncTable

from app.everos.core.persistence.lancedb import LanceRepoBase

from ..lancedb_manager import get_table
from ..tables.user_profile import UserProfile


def _q(value: str) -> str:
    return value.replace("'", "''")


class _UserProfileRepo(LanceRepoBase[UserProfile]):
    schema = UserProfile

    async def _table_lookup(self) -> AsyncTable:
        return await get_table(self.schema.TABLE_NAME, self.schema)

    async def find_by_owner_scope(
        self,
        owner_id: str,
        *,
        app_id: str = "default",
        project_id: str = "default",
    ) -> UserProfile | None:
        return await self.find_one_where(
            f"owner_id = '{_q(owner_id)}' "
            f"AND app_id = '{_q(app_id)}' "
            f"AND project_id = '{_q(project_id)}'"
        )


user_profile_repo = _UserProfileRepo()
