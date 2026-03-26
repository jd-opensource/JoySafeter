"""Tests for preview_skill_in_sandbox builtin tool."""

import json
from pathlib import Path

import pytest

from app.core.tools.buildin.preview_skill import preview_skill_in_sandbox


@pytest.fixture
def sandbox_root(tmp_path: Path) -> str:
    """Create a temporary sandbox root directory."""
    return str(tmp_path)


def _make_skill(sandbox_root: str, skill_name: str, files: dict[str, str], skills_subdir: str = "skills") -> Path:
    """Helper to create a skill directory with given files.

    Args:
        sandbox_root: Root of the sandbox.
        skill_name: Name of the skill directory.
        files: Mapping of relative file path -> content.
        skills_subdir: Subdirectory under sandbox_root for skills.

    Returns:
        Path to the created skill directory.
    """
    skill_dir = Path(sandbox_root) / skills_subdir / skill_name
    for rel_path, content in files.items():
        file_path = skill_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    return skill_dir


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_skill_returns_correct_structure(sandbox_root: str):
    """A well-formed skill with SKILL.md should pass validation."""
    skill_md = (
        "---\nname: hello-world\ndescription: A simple greeting skill\n---\n\n# Hello World\nThis skill says hello.\n"
    )
    _make_skill(
        sandbox_root,
        "hello-world",
        {
            "SKILL.md": skill_md,
            "main.py": "print('hello')\n",
        },
    )

    result_str = preview_skill_in_sandbox("hello-world", sandbox_root)
    result = json.loads(result_str)

    assert result["skill_name"] == "hello-world"
    assert result["validation"]["valid"] is True
    assert result["validation"]["errors"] == []

    # Check files are included
    file_paths = [f["path"] for f in result["files"]]
    assert "SKILL.md" in file_paths
    assert "main.py" in file_paths

    # Check file metadata
    skill_md_file = next(f for f in result["files"] if f["path"] == "SKILL.md")
    assert skill_md_file["file_type"] == "markdown"
    assert skill_md_file["size"] > 0
    assert "Hello World" in skill_md_file["content"]

    main_py_file = next(f for f in result["files"] if f["path"] == "main.py")
    assert main_py_file["file_type"] == "python"


def test_valid_skill_with_nested_files(sandbox_root: str):
    """Nested subdirectory files should be included with relative paths."""
    skill_md = "---\nname: nested-skill\ndescription: Skill with nested files\n---\n\nBody text.\n"
    _make_skill(
        sandbox_root,
        "nested-skill",
        {
            "SKILL.md": skill_md,
            "src/utils.py": "def helper(): pass\n",
            "src/data/config.json": '{"key": "value"}\n',
        },
    )

    result = json.loads(preview_skill_in_sandbox("nested-skill", sandbox_root))

    assert result["validation"]["valid"] is True
    paths = sorted(f["path"] for f in result["files"])
    assert "SKILL.md" in paths
    assert "src/utils.py" in paths
    assert "src/data/config.json" in paths

    json_file = next(f for f in result["files"] if f["path"] == "src/data/config.json")
    assert json_file["file_type"] == "json"


def test_custom_skills_subdir(sandbox_root: str):
    """Should respect a custom skills_subdir parameter."""
    skill_md = "---\nname: custom-dir\ndescription: test\n---\nBody.\n"
    _make_skill(sandbox_root, "custom-dir", {"SKILL.md": skill_md}, skills_subdir="my_skills")

    result = json.loads(preview_skill_in_sandbox("custom-dir", sandbox_root, skills_subdir="my_skills"))
    assert result["validation"]["valid"] is True
    assert result["skill_name"] == "custom-dir"


def test_default_lookup_finds_thread_scoped_skill_dir(sandbox_root: str):
    """Default lookup should find a skill under <thread_id>/skills when unambiguous."""
    skill_md = "---\nname: thread-dir\ndescription: test\n---\nBody.\n"
    _make_skill(sandbox_root, "thread-dir", {"SKILL.md": skill_md}, skills_subdir="thread-123/skills")

    result = json.loads(preview_skill_in_sandbox("thread-dir", sandbox_root))

    assert result["validation"]["valid"] is True
    assert result["skill_name"] == "thread-dir"


# ---------------------------------------------------------------------------
# File type detection
# ---------------------------------------------------------------------------


def test_file_type_detection(sandbox_root: str):
    """Various file extensions should map to correct file_type values."""
    skill_md = "---\nname: types-test\ndescription: test types\n---\nBody.\n"
    _make_skill(
        sandbox_root,
        "types-test",
        {
            "SKILL.md": skill_md,
            "script.py": "pass",
            "config.yaml": "key: val",
            "config.yml": "key: val",
            "data.json": "{}",
            "readme.txt": "hello",
            "run.sh": "#!/bin/bash",
            "style.css": "body {}",
            "page.html": "<html></html>",
            "app.js": "console.log(1)",
            "app.ts": "const x = 1",
            "unknown.xyz": "stuff",
        },
    )

    result = json.loads(preview_skill_in_sandbox("types-test", sandbox_root))
    type_map = {f["path"]: f["file_type"] for f in result["files"]}

    assert type_map["script.py"] == "python"
    assert type_map["config.yaml"] == "yaml"
    assert type_map["config.yml"] == "yaml"
    assert type_map["data.json"] == "json"
    assert type_map["readme.txt"] == "text"
    assert type_map["run.sh"] == "shell"
    assert type_map["style.css"] == "css"
    assert type_map["page.html"] == "html"
    assert type_map["app.js"] == "javascript"
    assert type_map["app.ts"] == "typescript"
    assert type_map["unknown.xyz"] == "other"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_skill_directory_not_found(sandbox_root: str):
    """Missing skill directory should produce valid=False with error."""
    result = json.loads(preview_skill_in_sandbox("nonexistent", sandbox_root))

    assert result["skill_name"] == "nonexistent"
    assert result["validation"]["valid"] is False
    assert any("not found" in e.lower() for e in result["validation"]["errors"])
    assert result["files"] == []


def test_missing_skill_md(sandbox_root: str):
    """A skill directory without SKILL.md should produce valid=False."""
    _make_skill(
        sandbox_root,
        "no-readme",
        {
            "main.py": "print('hi')\n",
        },
    )

    result = json.loads(preview_skill_in_sandbox("no-readme", sandbox_root))

    assert result["validation"]["valid"] is False
    assert any("SKILL.md" in e for e in result["validation"]["errors"])
    # Other files should still be listed
    assert len(result["files"]) == 1


def test_bad_yaml_frontmatter(sandbox_root: str):
    """Invalid YAML frontmatter should produce valid=False."""
    bad_skill_md = "---\nname: [invalid yaml\n---\nBody.\n"
    _make_skill(sandbox_root, "bad-yaml", {"SKILL.md": bad_skill_md})

    result = json.loads(preview_skill_in_sandbox("bad-yaml", sandbox_root))

    assert result["validation"]["valid"] is False
    assert any("frontmatter" in e.lower() or "name" in e.lower() for e in result["validation"]["errors"])


def test_missing_name_in_frontmatter(sandbox_root: str):
    """Frontmatter without 'name' should produce a validation error."""
    skill_md = "---\ndescription: no name here\n---\nBody.\n"
    _make_skill(sandbox_root, "no-name", {"SKILL.md": skill_md})

    result = json.loads(preview_skill_in_sandbox("no-name", sandbox_root))

    assert result["validation"]["valid"] is False
    assert any("name" in e.lower() for e in result["validation"]["errors"])


def test_missing_description_in_frontmatter(sandbox_root: str):
    """Frontmatter without 'description' should produce a validation error."""
    skill_md = "---\nname: no-desc\n---\nBody.\n"
    _make_skill(sandbox_root, "no-desc", {"SKILL.md": skill_md})

    result = json.loads(preview_skill_in_sandbox("no-desc", sandbox_root))

    assert result["validation"]["valid"] is False
    assert any("description" in e.lower() for e in result["validation"]["errors"])


def test_invalid_skill_name_format(sandbox_root: str):
    """Skill name that violates naming rules should produce validation error."""
    skill_md = "---\nname: Invalid_Name!\ndescription: bad name\n---\nBody.\n"
    _make_skill(sandbox_root, "bad-name", {"SKILL.md": skill_md})

    result = json.loads(preview_skill_in_sandbox("bad-name", sandbox_root))

    assert result["validation"]["valid"] is False
    assert any("name" in e.lower() for e in result["validation"]["errors"])


def test_description_too_long(sandbox_root: str):
    """Description exceeding max length should produce validation error."""
    long_desc = "x" * 1025
    skill_md = f"---\nname: long-desc\ndescription: {long_desc}\n---\nBody.\n"
    _make_skill(sandbox_root, "long-desc", {"SKILL.md": skill_md})

    result = json.loads(preview_skill_in_sandbox("long-desc", sandbox_root))

    assert result["validation"]["valid"] is False
    assert any("description" in e.lower() for e in result["validation"]["errors"])


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------


def test_empty_body_produces_warning(sandbox_root: str):
    """SKILL.md with empty body (no content after frontmatter) should warn."""
    skill_md = "---\nname: empty-body\ndescription: has no body\n---\n"
    _make_skill(sandbox_root, "empty-body", {"SKILL.md": skill_md})

    result = json.loads(preview_skill_in_sandbox("empty-body", sandbox_root))

    # Still valid, but warning present
    assert result["validation"]["valid"] is True
    assert any("body" in w.lower() or "empty" in w.lower() for w in result["validation"]["warnings"])


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_system_files_are_excluded(sandbox_root: str):
    """System files like .DS_Store should be excluded from file list."""
    skill_md = "---\nname: sys-files\ndescription: test system files\n---\nBody.\n"
    _make_skill(
        sandbox_root,
        "sys-files",
        {
            "SKILL.md": skill_md,
            ".DS_Store": "binary garbage",
            "__pycache__/module.pyc": "bytecode",
        },
    )

    result = json.loads(preview_skill_in_sandbox("sys-files", sandbox_root))
    file_paths = [f["path"] for f in result["files"]]

    assert ".DS_Store" not in file_paths
    # __pycache__ files should also be filtered
    assert not any("__pycache__" in p for p in file_paths)


def test_returns_valid_json_string(sandbox_root: str):
    """The function should always return a valid JSON string."""
    # Even for missing skill
    result_str = preview_skill_in_sandbox("missing", sandbox_root)
    assert isinstance(result_str, str)
    json.loads(result_str)  # Should not raise
