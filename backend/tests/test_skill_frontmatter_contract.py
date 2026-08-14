import pytest

from app.joysafeter_shared.skill.yaml_parser import extract_metadata_from_frontmatter

pytestmark = pytest.mark.no_db


def test_skill_frontmatter_uses_canonical_allowed_tools_key() -> None:
    metadata = extract_metadata_from_frontmatter({"allowed-tools": "Read Write"})
    assert metadata["allowed_tools"] == ["Read", "Write"]


def test_skill_frontmatter_does_not_emit_removed_fields() -> None:
    metadata = extract_metadata_from_frontmatter(
        {
            "allowed_tools": "Read",
            "version": "1.0.0",
            "author": "Legacy",
        }
    )

    assert metadata["allowed_tools"] == []
    assert "version" not in metadata
    assert "author" not in metadata
