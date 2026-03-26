from app.services.agent_registry import agent_registry


def test_agent_registry_exposes_skill_creator_definition() -> None:
    definition = agent_registry.get("skill_creator")

    assert definition.agent_name == "skill_creator"
    assert definition.display_name == "Skill Creator"
    assert definition.run_type == "skill_creator"
    assert callable(definition.reducer)
    assert callable(definition.make_initial_projection)


def test_agent_registry_lists_registered_agents() -> None:
    definitions = agent_registry.list_definitions()

    assert [definition.agent_name for definition in definitions] == ["skill_creator"]
