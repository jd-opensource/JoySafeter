"""Smoke test: proves the testcontainers harness migrates the schema and yields
a working AsyncSession. This validates conftest end-to-end before behavior tests.
"""

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_harness_migrates_schema(db_session):
    # joysafeter_tasks exists (migrations applied) and starts empty.
    result = await db_session.execute(text("SELECT COUNT(*) FROM joysafeter_tasks"))
    assert result.scalar() == 0
