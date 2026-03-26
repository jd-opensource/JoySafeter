from app.services.agent_registry import agent_registry


def test_skill_creator_definition_builds_initial_projection() -> None:
    definition = agent_registry.get("skill_creator")

    projection = definition.make_initial_projection(
        {
            "graph_id": "graph-123",
            "thread_id": "thread-456",
            "edit_skill_id": "skill-789",
        },
        status="queued",
    )

    assert projection["run_type"] == "skill_creator"
    assert projection["status"] == "queued"
    assert projection["graph_id"] == "graph-123"
    assert projection["thread_id"] == "thread-456"
    assert projection["edit_skill_id"] == "skill-789"


def test_skill_creator_definition_reducer_updates_preview_payload() -> None:
    definition = agent_registry.get("skill_creator")
    projection = definition.make_initial_projection({}, status="running")

    next_projection = definition.reducer(
        projection,
        event_type="tool_end",
        payload={
            "message_id": "msg-ai-1",
            "tool_name": "preview_skill",
            "tool_output": {"name": "network-scan"},
        },
        status="running",
    )

    assert next_projection["preview_data"] == {"name": "network-scan"}
