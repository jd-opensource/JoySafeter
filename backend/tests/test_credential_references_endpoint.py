import pytest

from app.joysafeter_infrastructure.credentials.sqlalchemy_repository import (
    SqlAlchemyCredentialRepository,
)


@pytest.mark.asyncio
async def test_names_for_resolves_agent_names(db_session, seeded_agent):
    # seeded_agent fixture: creates an agent id=<agent_id>, name="客服机器人", project="project-a"
    repo = SqlAlchemyCredentialRepository(db_session, material=None)
    names = await repo.names_for("agent", [seeded_agent.id], project_id="project-a")
    assert names == {str(seeded_agent.id): "客服机器人"}


@pytest.mark.asyncio
async def test_names_for_unknown_type_returns_empty(db_session):
    repo = SqlAlchemyCredentialRepository(db_session, material=None)
    assert await repo.names_for("nope", ["x"], project_id="project-a") == {}


@pytest.mark.asyncio
async def test_names_for_empty_ids_returns_empty(db_session):
    repo = SqlAlchemyCredentialRepository(db_session, material=None)
    assert await repo.names_for("agent", [], project_id="project-a") == {}
