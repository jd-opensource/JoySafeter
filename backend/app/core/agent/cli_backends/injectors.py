"""
Skill and runtime config injectors for CLI agent containers.
"""

from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from app.utils.path_utils import sanitize_skill_name

from .container_service import CLIContainerService


class CLISkillInjector:
    """Writes skill file trees into the container filesystem.

    Each skill is written as a directory under ``target_dir``:
        /workspace/skills/{skill_name}/
            SKILL.md
            scripts/rotate_pdf.py
            references/tools.md
            ...
    """

    def __init__(self, container_service: CLIContainerService):
        self.container_service = container_service

    async def inject(
        self,
        container_id: str,
        skills: list[dict[str, Any]],
        target_dir: str = "/workspace/skills",
    ) -> None:
        if not skills:
            return
        await self.container_service.exec_in_container(container_id, ["mkdir", "-p", target_dir])

        total_files = 0
        for skill in skills:
            name = sanitize_skill_name(skill.get("name", "unnamed"))
            skill_dir = f"{target_dir}/{name}"
            await self.container_service.exec_in_container(container_id, ["mkdir", "-p", skill_dir])

            files: list[dict[str, str]] = skill.get("files", [])
            if files:
                for f in files:
                    content = f.get("content", "")
                    if not content:
                        continue
                    rel_path = f.get("path", f.get("file_name", "unknown"))
                    full_path = f"{skill_dir}/{rel_path}"
                    parent = "/".join(full_path.rsplit("/", 1)[:-1])
                    if parent:
                        await self.container_service.exec_in_container(container_id, ["mkdir", "-p", parent])
                    escaped = content.replace("\\", "\\\\").replace("'", "'\\''")
                    await self.container_service.exec_in_container(
                        container_id,
                        ["sh", "-c", f"cat > '{full_path}' << 'SKILLEOF'\n{escaped}\nSKILLEOF"],
                    )
                    total_files += 1
            else:
                # Fallback: write SKILL.md from top-level content field
                body = skill.get("content", "")
                if body:
                    desc = skill.get("description", "")
                    skill_md = f"---\nname: {name}\ndescription: {desc}\n---\n\n{body}"
                    await self.container_service.exec_in_container(
                        container_id,
                        ["sh", "-c", f"cat > '{skill_dir}/SKILL.md' << 'SKILLEOF'\n{skill_md}\nSKILLEOF"],
                    )
                    total_files += 1

        logger.info(f"Injected {len(skills)} skills ({total_files} files) into {container_id[:12]}")


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
        sections.append("You are an autonomous coding agent executing a task.")
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
            sections.append(
                "Skills are located in `/workspace/skills/`. Each skill directory contains a SKILL.md and related files."
            )
            sections.append("")
            for name in skill_names:
                safe = sanitize_skill_name(name)
                sections.append(f"- **{name}** → `/workspace/skills/{safe}/SKILL.md`")

        if project_context:
            sections.append("")
            sections.append("## Project Context")
            sections.append("")
            sections.append(project_context)

        return "\n".join(sections)
