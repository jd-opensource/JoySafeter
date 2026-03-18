"""Preview skill files from a sandbox directory (read-only).

This builtin tool is called by the Agent inside the Skill Creator graph
to output the generated skill files for frontend preview. It reads from
the Docker sandbox's host-side volume mount and does NOT write to DB.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from app.core.skill.validators import validate_skill_description, validate_skill_name
from app.core.skill.yaml_parser import is_system_file, parse_skill_md

# Extension -> human-readable file type mapping
_EXTENSION_TYPE_MAP: Dict[str, str] = {
    ".py": "python",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".txt": "text",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".xml": "xml",
    ".svg": "svg",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "config",
    ".conf": "config",
    ".env": "env",
    ".sql": "sql",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".r": "r",
    ".R": "r",
    ".dockerfile": "dockerfile",
}

# Directories that should be excluded from file listing
_EXCLUDED_DIRS = {"__pycache__", ".git", "node_modules", ".mypy_cache", ".pytest_cache"}


def _detect_file_type(file_path: str) -> str:
    """Detect file type from extension.

    Args:
        file_path: Relative or absolute file path.

    Returns:
        Human-readable file type string.
    """
    basename = os.path.basename(file_path)

    # Special filenames
    if basename.lower() == "dockerfile":
        return "dockerfile"
    if basename.lower() == "makefile":
        return "makefile"

    ext = os.path.splitext(file_path)[1].lower()
    return _EXTENSION_TYPE_MAP.get(ext, "other")


def _should_exclude(rel_path: str) -> bool:
    """Check whether a file should be excluded from listing.

    Filters system files (e.g. .DS_Store) and common generated directories.

    Args:
        rel_path: Relative path of the file within the skill directory.

    Returns:
        True if the file should be excluded.
    """
    # Use existing is_system_file helper
    if is_system_file(rel_path):
        return True

    # Exclude files inside known generated/cache directories
    parts = Path(rel_path).parts
    for part in parts:
        if part in _EXCLUDED_DIRS:
            return True

    return False


def _collect_files(skill_dir: Path) -> List[Dict[str, Any]]:
    """Recursively collect all non-excluded files from *skill_dir*.

    Args:
        skill_dir: Absolute path to the skill directory.

    Returns:
        List of file info dicts with keys: path, content, file_type, size.
    """
    files: List[Dict[str, Any]] = []

    for root, _dirs, filenames in os.walk(skill_dir):
        for filename in sorted(filenames):
            abs_path = Path(root) / filename
            rel_path = str(abs_path.relative_to(skill_dir))

            if _should_exclude(rel_path):
                continue

            try:
                content = abs_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                # Skip binary / unreadable files silently
                continue

            files.append(
                {
                    "path": rel_path,
                    "content": content,
                    "file_type": _detect_file_type(rel_path),
                    "size": abs_path.stat().st_size,
                }
            )

    return files


def preview_skill_in_sandbox(
    skill_name: str,
    sandbox_root: str,
    skills_subdir: str = "skills",
) -> str:
    """Preview a skill's files and validate its metadata.

    Reads all files from ``{sandbox_root}/{skills_subdir}/{skill_name}/``
    recursively, validates the SKILL.md frontmatter, and returns a JSON
    string suitable for the frontend preview panel.

    Args:
        skill_name: Directory name of the skill (e.g. ``"hello-world"``).
        sandbox_root: Host path to the sandbox root
            (e.g. ``"/tmp/sandboxes/{user_id}"``).
        skills_subdir: Subdirectory under *sandbox_root* that contains
            skill directories.  Defaults to ``"skills"``.

    Returns:
        JSON string with structure::

            {
              "skill_name": "...",
              "files": [{
                "path": "SKILL.md",
                "content": "...",
                "file_type": "markdown",
                "size": 1234
              }],
              "validation": {
                "valid": true,
                "errors": [],
                "warnings": []
              }
            }
    """
    errors: List[str] = []
    warnings: List[str] = []

    skill_dir = Path(sandbox_root) / skills_subdir / skill_name

    # --- 1. Check skill directory exists ---
    if not skill_dir.is_dir():
        return json.dumps(
            {
                "skill_name": skill_name,
                "files": [],
                "validation": {
                    "valid": False,
                    "errors": [f"Skill directory not found: {skills_subdir}/{skill_name}"],
                    "warnings": [],
                },
            }
        )

    # --- 2. Collect files ---
    files = _collect_files(skill_dir)

    # --- 3. Locate and validate SKILL.md ---
    skill_md_entry = next((f for f in files if f["path"] == "SKILL.md"), None)

    if skill_md_entry is None:
        errors.append("SKILL.md not found in skill directory")
    else:
        frontmatter, body = parse_skill_md(skill_md_entry["content"])

        # Validate name
        fm_name = frontmatter.get("name", "")
        if not fm_name:
            errors.append("Missing required field 'name' in SKILL.md frontmatter")
        else:
            name_valid, name_err = validate_skill_name(fm_name)
            if not name_valid:
                errors.append(f"Invalid skill name: {name_err}")

        # Validate description
        fm_desc = frontmatter.get("description", "")
        if not fm_desc:
            errors.append("Missing required field 'description' in SKILL.md frontmatter")
        else:
            desc_valid, desc_err = validate_skill_description(str(fm_desc))
            if not desc_valid:
                errors.append(f"Invalid skill description: {desc_err}")

        # Warn on empty body
        if not body or not body.strip():
            warnings.append("SKILL.md body is empty; consider adding usage documentation")

    valid = len(errors) == 0

    return json.dumps(
        {
            "skill_name": skill_name,
            "files": files,
            "validation": {
                "valid": valid,
                "errors": errors,
                "warnings": warnings,
            },
        }
    )
