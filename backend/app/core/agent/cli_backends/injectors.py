"""
Credential, skill, and runtime config injectors for CLI agent containers.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from loguru import logger

from .container_service import CLIContainerService


class CredentialInjector:
    """Builds the env dict for CLI agent containers.

    Credentials are passed to ``create_container()`` which sets them via
    Docker's ``-e`` / ``--env-file`` flags.  This class only resolves and
    returns the dict — it never writes to the container filesystem.
    """

    def build_env(self, credentials: dict[str, str]) -> dict[str, str]:
        """Return a sanitised copy of *credentials* suitable for Docker env."""
        return dict(credentials) if credentials else {}


class CLISkillInjector:
    """Writes skill definitions into the container filesystem."""

    def __init__(self, container_service: CLIContainerService):
        self.container_service = container_service

    async def inject(
        self,
        container_id: str,
        skills: list[dict[str, Any]],
        target_dir: str = "/workspace/.skills",
    ) -> None:
        if not skills:
            return
        await self.container_service.exec_in_container(container_id, ["mkdir", "-p", target_dir])
        for skill in skills:
            name = skill.get("name", "unnamed")
            filename = f"{target_dir}/{name}.json"
            content = json.dumps(skill, indent=2)
            await self.container_service.exec_in_container(
                container_id,
                ["sh", "-c", f"cat > {filename} << 'SKILLEOF'\n{content}\nSKILLEOF"],
            )
        logger.debug(f"Injected {len(skills)} skills into {container_id[:12]}")


class RuntimeConfigInjector:
    """Generates and writes CLAUDE.md configuration into the container."""

    def __init__(self, container_service: CLIContainerService):
        self.container_service = container_service

    async def inject(
        self,
        container_id: str,
        *,
        instructions: Optional[str] = None,
        skill_names: Optional[list[str]] = None,
        project_context: Optional[str] = None,
        working_dir: str = "/workspace",
    ) -> None:
        claude_md = self._build_claude_md(
            instructions=instructions,
            skill_names=skill_names,
            project_context=project_context,
        )
        target = f"{working_dir}/CLAUDE.md"
        await self.container_service.exec_in_container(
            container_id,
            ["sh", "-c", f"cat > {target} << 'CLAUDEEOF'\n{claude_md}\nCLAUDEEOF"],
        )
        logger.debug(f"Injected CLAUDE.md into {container_id[:12]}")

    def _build_claude_md(
        self,
        *,
        instructions: Optional[str] = None,
        skill_names: Optional[list[str]] = None,
        project_context: Optional[str] = None,
    ) -> str:
        sections: list[str] = []
        sections.append("# Agent Configuration")
        sections.append("")
        sections.append("You are an autonomous coding agent executing a mission.")
        sections.append("Complete the task thoroughly and commit your work when done.")

        if instructions:
            sections.append("")
            sections.append("## Instructions")
            sections.append("")
            sections.append(instructions)

        if skill_names:
            sections.append("")
            sections.append("## Available Skills")
            sections.append("")
            for name in skill_names:
                sections.append(f"- {name}")

        if project_context:
            sections.append("")
            sections.append("## Project Context")
            sections.append("")
            sections.append(project_context)

        return "\n".join(sections)
