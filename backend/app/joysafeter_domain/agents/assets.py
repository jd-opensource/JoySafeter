from __future__ import annotations


def merge_agent_assets(skills: list, agents: list, commands: list) -> list[dict]:
    merged = []
    for item in skills:
        data = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        data["target"] = "skills"
        merged.append(data)
    for item in agents:
        data = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        data["target"] = "agents"
        merged.append(data)
    for item in commands:
        data = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        data["target"] = "commands"
        merged.append(data)
    return merged


def split_agent_assets(merged: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    skills, agents, commands = [], [], []
    for item in merged:
        item_copy = {key: value for key, value in item.items() if key != "target"}
        target = item.get("target")
        if target == "agents":
            agents.append(item_copy)
        elif target == "commands":
            commands.append(item_copy)
        elif target == "skills":
            skills.append(item_copy)
        else:
            raise ValueError("Agent asset target must be skills, agents, or commands")
    return skills, agents, commands
