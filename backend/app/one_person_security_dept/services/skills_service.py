"""Filesystem skill discovery and validation for Security Dept."""

from __future__ import annotations

import re
from pathlib import Path

from app.common.exceptions import BadRequestException, NotFoundException
from app.core.skill.yaml_parser import extract_metadata_from_frontmatter, parse_skill_md

_SKILL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


class SecurityDeptSkillsService:
    """Resolves skills under project-level skills directory."""

    @staticmethod
    def get_skills_root() -> Path:
        candidates = [
            Path("/app/skills"),
            Path(__file__).resolve().parents[4] / "skills",
            Path.cwd() / "skills",
            Path.cwd().parent / "skills",
        ]

        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return candidate.resolve()

        raise NotFoundException("Skills root directory not found")

    @staticmethod
    def _validate_skill_name(skill_name: str) -> None:
        if not _SKILL_NAME_PATTERN.match(skill_name):
            raise BadRequestException(f"Invalid skill name: {skill_name}")

    @classmethod
    def list_fs_skills(cls) -> tuple[Path, list[dict[str, str | bool]]]:
        root = cls.get_skills_root()
        items: list[dict[str, str | bool]] = []

        for directory in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not directory.is_dir() or directory.name.startswith("."):
                continue

            skill_md = directory / "SKILL.md"
            if not skill_md.exists():
                skill_md = directory / "skill.md"

            has_skill_md = skill_md.exists()
            display_name = directory.name
            description = ""

            if has_skill_md:
                try:
                    content = skill_md.read_text(encoding="utf-8")
                    frontmatter, _ = parse_skill_md(content)
                    meta = extract_metadata_from_frontmatter(frontmatter)
                    display_name = str(meta.get("name") or directory.name)
                    description = str(meta.get("description") or "")
                except Exception:
                    description = ""

            items.append(
                {
                    "skill_name": directory.name,
                    "display_name": display_name,
                    "description": description,
                    "has_skill_md": has_skill_md,
                    "abs_path": str(directory.resolve()),
                }
            )

        return root, items

    @classmethod
    def resolve_skill_paths(cls, skill_names: list[str]) -> list[str]:
        if not skill_names:
            return []

        root = cls.get_skills_root()
        resolved_paths: list[str] = []
        seen: set[str] = set()

        for raw_name in skill_names:
            skill_name = raw_name.strip()
            cls._validate_skill_name(skill_name)
            if skill_name in seen:
                continue

            candidate_dir = (root / skill_name).resolve()

            # Ensure resolved path stays inside the skills root.
            try:
                candidate_dir.relative_to(root)
            except ValueError as exc:
                raise BadRequestException(f"Skill path escapes root: {skill_name}") from exc

            if not candidate_dir.exists() or not candidate_dir.is_dir():
                raise NotFoundException(f"Skill not found: {skill_name}")

            skill_md = candidate_dir / "SKILL.md"
            if not skill_md.exists() and not (candidate_dir / "skill.md").exists():
                raise BadRequestException(f"Skill missing SKILL.md: {skill_name}")

            resolved_paths.append(str(candidate_dir))
            seen.add(skill_name)

        return resolved_paths
