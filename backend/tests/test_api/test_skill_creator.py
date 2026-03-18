"""Integration smoke tests for the Skill Creator feature.

After the mode→graph_id unification, skill_creator no longer uses a dedicated
`mode` field. Instead, it routes through `graph_id` like all other modes.
The `edit_skill_id` is now passed via `metadata`.
"""

import json
import tempfile
from pathlib import Path

import pytest

from app.core.tools.buildin.preview_skill import preview_skill_in_sandbox
from app.schemas.chat import ChatRequest


class TestSkillCreatorIntegration:
    """Verify key components of the Skill Creator feature work together."""

    def test_chat_request_with_graph_id(self):
        """Skill creator now uses graph_id for routing, not mode."""
        import uuid

        gid = uuid.uuid4()
        req = ChatRequest(message="Create a network scan skill", graph_id=gid)
        assert req.graph_id == gid

    def test_chat_request_with_edit_skill_id_in_metadata(self):
        """edit_skill_id is now passed via metadata."""
        import uuid

        gid = uuid.uuid4()
        req = ChatRequest(
            message="Update this skill",
            graph_id=gid,
            metadata={"edit_skill_id": "abc-123"},
        )
        assert req.graph_id == gid
        assert req.metadata["edit_skill_id"] == "abc-123"

    def test_preview_skill_end_to_end(self):
        """Simulate: agent creates skill files in sandbox -> preview_skill reads them."""
        with tempfile.TemporaryDirectory() as sandbox_root:
            skill_dir = Path(sandbox_root) / "skills" / "test-scan"
            skill_dir.mkdir(parents=True)

            # Simulate agent writing SKILL.md
            (skill_dir / "SKILL.md").write_text(
                "---\nname: test-scan\ndescription: A network scanning skill\n---\n"
                "# Test Scan Skill\n\nThis skill performs network scanning."
            )

            # Simulate agent writing a script
            scripts_dir = skill_dir / "scripts"
            scripts_dir.mkdir()
            (scripts_dir / "scan.py").write_text("import subprocess\ndef run_scan(target): pass")

            # Call preview_skill (same as agent would)
            result_json = preview_skill_in_sandbox("test-scan", sandbox_root)
            result = json.loads(result_json)

            assert result["skill_name"] == "test-scan"
            assert result["validation"]["valid"] is True
            assert len(result["files"]) == 2

            # Verify files match what would be sent to POST /v1/skills
            paths = {f["path"] for f in result["files"]}
            assert "SKILL.md" in paths
            assert "scripts/scan.py" in paths
