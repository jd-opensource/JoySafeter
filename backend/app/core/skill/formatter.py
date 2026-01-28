"""Skill content formatter for agent consumption."""

from typing import Dict, List, Optional

from app.models.skill import Skill, SkillFile


class SkillFormatter:
    """Formats skill content for agent consumption."""

    @staticmethod
    def _get_language_hint(file_type: str, file_name: str) -> str:
        """Get language hint for code block based on file type or extension."""
        # Map common file types to language hints
        type_map = {
            "python": "python",
            "javascript": "javascript",
            "typescript": "typescript",
            "markdown": "markdown",
            "json": "json",
            "yaml": "yaml",
            "yml": "yaml",
            "bash": "bash",
            "shell": "bash",
            "sh": "bash",
            "sql": "sql",
            "html": "html",
            "css": "css",
        }

        if file_type and file_type.lower() in type_map:
            return type_map[file_type.lower()]

        # Try to infer from file extension
        if "." in file_name:
            ext = file_name.rsplit(".", 1)[-1].lower()
            ext_map = {
                "py": "python",
                "js": "javascript",
                "ts": "typescript",
                "md": "markdown",
                "json": "json",
                "yaml": "yaml",
                "yml": "yaml",
                "sh": "bash",
                "sql": "sql",
                "html": "html",
                "css": "css",
            }
            return ext_map.get(ext, "")

        return ""

    @staticmethod
    def _get_top_directory(path: str) -> Optional[str]:
        """Get the top-level directory from a file path.

        Returns None for root-level files (no directory).
        """
        if not path or "/" not in path:
            return None
        return path.split("/")[0]

    @staticmethod
    def _group_files_by_directory(files: List[SkillFile]) -> Dict[str, List[SkillFile]]:
        """Group files by their top-level directory.

        Returns dict with:
        - "rootFiles": files at root level (like SKILL.md)
        - Each unique top-level directory as a key
        """
        grouped: Dict[str, List[SkillFile]] = {
            "rootFiles": [],
        }

        for file in files:
            directory = SkillFormatter._get_top_directory(file.path)
            if directory is None:
                # Root-level file (SKILL.md, README.md, etc.)
                grouped["rootFiles"].append(file)
            else:
                if directory not in grouped:
                    grouped[directory] = []
                grouped[directory].append(file)

        return grouped

    @staticmethod
    def _format_file(file: SkillFile, include_content: bool = True) -> str:
        """Format a single file entry."""
        lang_hint = SkillFormatter._get_language_hint(file.file_type, file.file_name)
        parts = [f"### {file.path or file.file_name}"]

        if file.file_type:
            parts.append(f"**Type**: {file.file_type}")

        if include_content and file.content:
            parts.append(f"\n```{lang_hint}\n{file.content}\n```")

        return "\n".join(parts)

    @staticmethod
    def format_skill_content(skill: Skill, include_file_contents: bool = True) -> str:
        """Format skill content as a string for agent context.

        Organizes files hierarchically by their directory structure.

        Args:
            skill: Skill object (should include files relationship)
            include_file_contents: Whether to include full file contents

        Returns:
            Formatted skill content string
        """
        result_parts = [f"Loaded skill: {skill.name}\n"]
        result_parts.append(f"\n# {skill.name}\n")
        result_parts.append(f"**Description**: {skill.description}\n")

        if skill.tags:
            result_parts.append(f"**Tags**: {', '.join(skill.tags)}\n")

        if skill.license:
            result_parts.append(f"**License**: {skill.license}\n")

        # Add main content (from SKILL.md body)
        if skill.content:
            result_parts.append(f"\n## Instructions\n\n{skill.content}\n")

        # Add files organized by directory
        if skill.files and len(skill.files) > 0:
            grouped = SkillFormatter._group_files_by_directory(skill.files)

            # Root level files (excluding SKILL.md as its content is already shown)
            other_root_files = [f for f in grouped["rootFiles"] if f.path != "SKILL.md" and f.file_name != "SKILL.md"]
            if other_root_files:
                result_parts.append("\n## Other Files\n")
                for file in other_root_files:
                    result_parts.append(SkillFormatter._format_file(file, include_file_contents))
                    result_parts.append("")

            # Files in directories (sorted alphabetically)
            directories = sorted([k for k in grouped.keys() if k != "rootFiles"])
            for directory in directories:
                files = grouped[directory]
                if files:
                    result_parts.append(f"\n## {directory}/\n")
                    for file in files:
                        result_parts.append(SkillFormatter._format_file(file, include_file_contents))
                        result_parts.append("")

        return "\n".join(result_parts)

    @staticmethod
    def format_skill_list(skills: List[Skill]) -> str:
        """Format a list of skills as a markdown list.

        Args:
            skills: List of Skill objects

        Returns:
            Formatted markdown string
        """
        if not skills:
            return "No skills available."

        skills_list = []
        for skill in skills:
            tags_str = f" [{', '.join(skill.tags)}]" if skill.tags else ""
            skills_list.append(f"- **{skill.name}**{tags_str}: {skill.description}")

        return "\n".join(skills_list)

    @staticmethod
    def format_skill_structure(skill: Skill) -> str:
        """Format the skill's file structure as a tree view.

        Args:
            skill: Skill object with files

        Returns:
            Tree-like string representation of the skill structure
        """
        if not skill.files:
            return f"📁 {skill.name}/\n└── (empty)"

        grouped = SkillFormatter._group_files_by_directory(skill.files)
        lines = [f"📁 {skill.name}/"]

        # Root-level files (SKILL.md, etc.)
        for file in grouped["rootFiles"]:
            icon = "📄" if file.file_name.endswith(".md") else "📎"
            lines.append(f"├── {icon} {file.file_name}")

        # Directory folders (sorted alphabetically)
        directories = sorted([k for k in grouped.keys() if k != "rootFiles"])
        for directory in directories:
            files = grouped[directory]
            if files:
                lines.append(f"├── 📁 {directory}/")
                for i, file in enumerate(files):
                    prefix = "│   └──" if i == len(files) - 1 else "│   ├──"
                    # Extract filename from path
                    filename = file.path.split("/")[-1] if "/" in file.path else file.file_name
                    # Choose icon based on file extension
                    if filename.endswith(".py"):
                        icon = "🐍"
                    elif filename.endswith(".md"):
                        icon = "📄"
                    else:
                        icon = "📎"
                    lines.append(f"{prefix} {icon} {filename}")

        return "\n".join(lines)
