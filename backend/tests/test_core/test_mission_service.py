from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from app.models.mission import Mission, MissionPriority, MissionStatus
from app.services.execution_lifecycle_service import build_execution_prompt


def _make_mission(**overrides) -> Mission:
    """Create a Mission-like object for testing prompt building."""
    defaults = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "creator_id": "user-1",
        "title": "Fix login bug",
        "description": None,
        "objective": None,
        "status": MissionStatus.TODO,
        "priority": MissionPriority.MEDIUM,
        "assignee_type": "agent",
        "assignee_id": uuid.uuid4(),
        "parent_task_id": None,
        "current_execution_id": None,
        "due_date": None,
        "position": 0.0,
        "tags": None,
    }
    defaults.update(overrides)
    mission = MagicMock(spec=Mission)
    for k, v in defaults.items():
        setattr(mission, k, v)
    return mission


def test_build_prompt_title_only():
    mission = _make_mission(title="Fix login bug")
    prompt = build_execution_prompt(mission)
    assert "# Mission: Fix login bug" in prompt
    assert "## Description" not in prompt
    assert "## Objective" not in prompt


def test_build_prompt_with_description():
    mission = _make_mission(
        title="Add caching",
        description="Implement Redis caching for the API layer.",
    )
    prompt = build_execution_prompt(mission)
    assert "# Mission: Add caching" in prompt
    assert "## Description" in prompt
    assert "Implement Redis caching" in prompt


def test_build_prompt_with_objective():
    mission = _make_mission(
        title="Refactor auth",
        objective="Reduce auth latency by 50%.",
    )
    prompt = build_execution_prompt(mission)
    assert "## Objective" in prompt
    assert "Reduce auth latency" in prompt


def test_build_prompt_with_tags():
    mission = _make_mission(
        title="Deploy v2",
        tags=["backend", "infra", "urgent"],
    )
    prompt = build_execution_prompt(mission)
    assert "## Tags" in prompt
    assert "backend" in prompt
    assert "infra" in prompt
    assert "urgent" in prompt


def test_build_prompt_full():
    mission = _make_mission(
        title="Full mission",
        description="Do everything.",
        objective="Ship it.",
        tags=["release"],
    )
    prompt = build_execution_prompt(mission)
    assert "# Mission: Full mission" in prompt
    assert "## Description" in prompt
    assert "Do everything." in prompt
    assert "## Objective" in prompt
    assert "Ship it." in prompt
    assert "## Tags" in prompt
    assert "release" in prompt


def test_build_prompt_empty_tags_not_shown():
    mission = _make_mission(title="No tags", tags=None)
    prompt = build_execution_prompt(mission)
    assert "## Tags" not in prompt


def test_build_prompt_empty_tags_list_not_shown():
    mission = _make_mission(title="Empty tags", tags=[])
    prompt = build_execution_prompt(mission)
    assert "## Tags" not in prompt
