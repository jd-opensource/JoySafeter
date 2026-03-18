"""Integration smoke tests for the Skill Creator feature."""
import json
import tempfile
from pathlib import Path

import pytest

from app.schemas.chat import ChatRequest
from app.core.tools.buildin.preview_skill import preview_skill_in_sandbox


class TestSkillCreatorIntegration:
    """Verify key components of the Skill Creator feature work together."""

    def test_chat_request_accepts_skill_creator_mode(self):
        req = ChatRequest(message="Create a network scan skill", mode="skill_creator")
        assert req.mode == "skill_creator"
        assert req.edit_skill_id is None

    def test_chat_request_skill_creator_with_edit(self):
        req = ChatRequest(
            message="Update this skill",
            mode="skill_creator",
            edit_skill_id="abc-123",
        )
        assert req.mode == "skill_creator"
        assert req.edit_skill_id == "abc-123"

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
            (scripts_dir / "scan.py").write_text(
                "import subprocess\ndef run_scan(target): pass"
            )

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

    def test_graph_service_has_skill_creator_method(self):
        """Verify GraphService has the create_skill_creator_graph method."""
        try:
            from app.services.graph_service import GraphService
        except ImportError as exc:
            pytest.skip(f"GraphService import requires optional deps: {exc}")

        assert hasattr(GraphService, "create_skill_creator_graph")
        assert callable(getattr(GraphService, "create_skill_creator_graph"))
