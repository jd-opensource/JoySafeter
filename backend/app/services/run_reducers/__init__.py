"""Run projection reducers."""

from app.services.agent_registry import AgentDefinition, agent_registry

from .chat import apply_chat_event, make_initial_projection as chat_make_initial_projection
from .copilot import apply_copilot_event, make_initial_projection as copilot_make_initial_projection
from .skill_creator import apply_skill_creator_event, make_initial_projection

agent_registry.register(
    AgentDefinition(
        agent_name="skill_creator",
        display_name="Skill Creator",
        run_type="skill_creator",
        reducer=apply_skill_creator_event,
        make_initial_projection=make_initial_projection,
    )
)

agent_registry.register(
    AgentDefinition(
        agent_name="chat",
        display_name="Chat",
        run_type="chat_turn",
        reducer=apply_chat_event,
        make_initial_projection=chat_make_initial_projection,
    )
)

agent_registry.register(
    AgentDefinition(
        agent_name="copilot",
        display_name="Copilot",
        run_type="copilot_turn",
        reducer=apply_copilot_event,
        make_initial_projection=copilot_make_initial_projection,
    )
)

__all__ = [
    "agent_registry",
    "apply_chat_event",
    "apply_copilot_event",
    "apply_skill_creator_event",
    "chat_make_initial_projection",
    "copilot_make_initial_projection",
    "make_initial_projection",
]
