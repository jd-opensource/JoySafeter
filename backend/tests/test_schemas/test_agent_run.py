"""AgentRun schema tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.schemas.agent_run import AgentRunResponse


def test_agent_run_response_allows_draft_version_without_release() -> None:
    version_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    response = AgentRunResponse.model_validate(
        {
            "id": uuid.uuid4(),
            "release_id": None,
            "agent_version_id": version_id,
            "workspace_id": uuid.uuid4(),
            "thread_id": None,
            "task_id": None,
            "trigger_source": "draft_test",
            "goal": "hello draft",
            "input_payload": None,
            "status": "running",
            "current_execution_id": uuid.uuid4(),
            "result_summary": None,
            "started_at": now,
            "ended_at": None,
            "created_by": "user-123",
            "created_at": now,
        }
    )

    assert response.release_id is None
    assert response.agent_version_id == version_id
