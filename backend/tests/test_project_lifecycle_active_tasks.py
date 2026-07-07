import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import select

from app.joysafeter_api.api.v1.auth import archive_project
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole


def _admin_ctx(project_id: str, org_id: str) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="admin-user",
        org_id=org_id,
        project_id=project_id,
        role=JoySafeterRole.ADMIN,
    )


@pytest.mark.asyncio
async def test_archive_project_rejects_active_tasks(db_session):
    org_id = f"org-{uuid.uuid4()}"
    org = Organization(id=org_id, name="Launch Org", slug=f"launch-org-{uuid.uuid4()}")
    project = Project(id=f"proj-{uuid.uuid4()}", org_id=org_id, name="Launch", slug=f"launch-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.commit()

    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    agent = JoySafeterAgent(name=f"project-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    project_id = project.id

    task = JoySafeterTask(
        agent_id=agent.id,
        project_id=project_id,
        prompt="scan target",
        status=JoySafeterTaskStatus.PENDING.value,
    )
    db_session.add(task)
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await archive_project(project_id, db_session, _admin_ctx(project_id, org_id))

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "PROJECT_ACTIVE_TASKS",
        "message": "Project has active tasks. Stop or wait for them before archiving.",
        "data": {"project_id": project_id, "active": 1},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    project_row = (await db_session.execute(select(Project).where(Project.id == project_id))).scalar_one()
    assert project_row.archived_at is None
