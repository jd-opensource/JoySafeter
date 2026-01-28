"""
CTF Knowledge Parser

Pure parsing/normalization helpers for the CTF knowledge YAML formats.
This module is intentionally side-effect free (no caches / singletons).
"""

from typing import Any

from .models import Trick


def convert_attack_steps_to_tricks(attack_steps: list[dict[str, Any]]) -> list[Trick]:
    """
    Convert legacy attack_steps format to simplified tricks format.

    Legacy format:
        attack_steps:
          - step: 1
            action: "Check homepage HTML source code"
            method: GET
            endpoint: /
            expected_output: "Look for comments"
            notes: "Check source code comments first"

    New format:
        tricks:
          - name: "Check HTML source code comments"
            when: "First visit to target"
            how: "View page source and search for <!-- comments"
            payload: ""
    """
    tricks: list[Trick] = []

    for step in attack_steps:
        action = step.get("action", "")
        notes = step.get("notes", "")
        method = step.get("method", "")
        endpoint = step.get("endpoint", "")
        payload_hint = step.get("payload_hint", step.get("payload", ""))
        expected = step.get("expected_output", "")

        # Build trick from attack step
        name = action[:50] if action else f"Step {step.get('step', '?')}"
        when = notes if notes else f"Execute {method} {endpoint}" if method else "Execute in order"
        how = action
        if expected:
            how += f" (expected: {expected[:50]})"
        payload = payload_hint if payload_hint else ""

        tricks.append(Trick(name=name, when=when, how=how, payload=payload))

    return tricks


def normalize_knowledge(yaml_data: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize knowledge YAML to simplified format.

    Supports both new (tricks) and legacy (attack_steps) formats.
    Returns a consistent structure for the Agent.
    """
    # If already in new format, return as-is
    if "tricks" in yaml_data and yaml_data["tricks"]:
        return yaml_data

    # Convert legacy format
    normalized: dict[str, Any] = {
        "name": yaml_data.get("name", "unknown"),
        "category": yaml_data.get("category", "misc"),
        "tags": yaml_data.get("tags", []),
        "indicators": yaml_data.get("indicators", []),
        "tricks": [],
        "difficulty": yaml_data.get("severity", "medium"),
        "references": [ref.get("url", "") for ref in yaml_data.get("references", []) if isinstance(ref, dict)],
    }

    # Convert attack_steps to tricks
    attack_steps = yaml_data.get("attack_steps", [])
    if attack_steps:
        normalized["tricks"] = convert_attack_steps_to_tricks(attack_steps)

    # Also extract discovery_hints as additional tricks
    discovery_hints = yaml_data.get("discovery_hints", [])
    for dh in discovery_hints:
        dh_type = dh.get("type", "discovery")
        dh_desc = dh.get("description", "")
        strategies = dh.get("strategies", [])

        for strategy in strategies[:3]:  # Limit to top 3 strategies
            normalized["tricks"].append(
                Trick(
                    name=f"{dh_type}: {dh_desc[:30]}",
                    when=dh_type,
                    how=strategy if isinstance(strategy, str) else str(strategy),
                    payload="",
                )
            )

    return normalized
