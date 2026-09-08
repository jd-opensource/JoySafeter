"""Handler test for the additive ``POST /quickstart/recommendations`` route.

Calls the route function directly against conftest's real ``db_session`` (mirrors
``test_quickstart_error_contract.py``; the full app is un-loadable mid-cutover)."""

import uuid

import pytest_asyncio

from app.joysafeter_api.api.v1.quickstart import (
    QuickstartRecommendRequest,
    quickstart_recommendations,
)
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import OrganizationId, ProjectId, UserId

TEST_USER_ID = UserId.new()
TEST_ORGANIZATION_ID = OrganizationId.new()


async def _make_project(db_session) -> ProjectId:
    org = Organization(id=TEST_ORGANIZATION_ID, name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(id=ProjectId.new(), org_id=org.id, name=f"proj-{uuid.uuid4()}", slug=f"proj-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest_asyncio.fixture
async def project_id(db_session) -> ProjectId:
    return await _make_project(db_session)


def _auth_ctx(project_id: ProjectId) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=TEST_USER_ID,
        org_id=TEST_ORGANIZATION_ID,
        project_id=project_id,
        role=JoySafeterRole.MEMBER,
    )


async def test_secure_phase_returns_rule_recommendation(db_session, project_id):
    rec = await quickstart_recommendations(
        QuickstartRecommendRequest(phase="secure", intent="summarize my github pull requests"),
        db_session,
        _auth_ctx(project_id),
    )
    assert rec.phase == "secure"
    assert "github.com" in rec.environment.allowed_hosts


async def test_understand_phase_ranks_engines_with_no_connections(db_session, project_id):
    rec = await quickstart_recommendations(
        QuickstartRecommendRequest(phase="understand", intent="build a research agent"),
        db_session,
        _auth_ctx(project_id),
    )
    assert rec.phase == "understand"
    assert len(rec.engine.options) >= 1
    # A fresh project has no model connections, so nothing can be "ready".
    assert all(o.readiness in ("setup_required", "unavailable") for o in rec.engine.options)
