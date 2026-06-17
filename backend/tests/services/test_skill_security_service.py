from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.joysafeter_domain.services.skill_security_service import SkillSecurityService
from app.joysafeter_shared.common.app_errors import InvalidRequestError
from app.joysafeter_shared.config.settings import settings


class _ScannerStub:
    def __init__(self, response=None, exc: Exception | None = None):
        self.response = response
        self.exc = exc
        self.calls: list[tuple[list, bool]] = []

    async def scan(self, files, *, no_llm: bool = True):
        self.calls.append((files, no_llm))
        if self.exc:
            raise self.exc
        return self.response


@pytest.fixture(autouse=True)
def enable_skill_security(monkeypatch):
    monkeypatch.setattr(settings, "skill_security_scan_enabled", True)
    monkeypatch.setattr(settings, "skill_security_fail_closed", True)
    monkeypatch.setattr(settings, "skill_security_no_llm", True)
    monkeypatch.setattr(settings, "skill_security_block_recommendations", ["DO_NOT_INSTALL"])


def _service(scanner: _ScannerStub) -> SkillSecurityService:
    db = SimpleNamespace(
        add=Mock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    svc = SkillSecurityService(db)
    svc.client = scanner
    return svc


@pytest.mark.asyncio
async def test_scan_for_write_rejects_blocked_recommendation():
    scanner = _ScannerStub(
        {
            "scanner_version": "test",
            "report": {
                "risk_assessment": {
                    "score": 95,
                    "severity": "critical",
                    "recommendation": "DO_NOT_INSTALL",
                },
                "issues": [{"severity": "critical"}, {"severity": "high"}],
            },
        }
    )
    svc = _service(scanner)

    with pytest.raises(InvalidRequestError) as exc_info:
        await svc.scan_for_write(
            trigger="create",
            created_by_id="user_1",
            owner_id="user_1",
            project_id="project_1",
            skill_id=None,
            name="unsafe",
            description="unsafe skill",
            content="run untrusted shell",
            tags=["ops"],
            license="MIT",
            files=[],
        )

    assert exc_info.value.code == "SKILL_SECURITY_SCAN_REJECTED"
    assert exc_info.value.data["status"] == "blocked"
    assert exc_info.value.data["critical_count"] == 1
    assert exc_info.value.data["high_count"] == 1


@pytest.mark.asyncio
async def test_scan_for_write_warns_on_scanner_block_recommendation_with_only_low_findings():
    scanner = _ScannerStub(
        {
            "scanner_version": "test",
            "report": {
                "risk_assessment": {
                    "score": 100,
                    "severity": "critical",
                    "recommendation": "DO_NOT_INSTALL",
                },
                "issues": [{"severity": "low", "pattern": "Scope Creep"} for _ in range(31)],
            },
        }
    )
    svc = _service(scanner)

    scan = await svc.scan_for_write(
        trigger="create",
        created_by_id="user_1",
        owner_id="user_1",
        project_id="project_1",
        skill_id=None,
        name="low-only",
        description="low only findings",
        content="body",
        tags=[],
        license=None,
        files=[],
    )

    assert scan.status == "warning"
    assert scan.score == 29
    assert scan.severity == "LOW"
    assert scan.recommendation == "CAUTION"
    assert scan.low_count == 31
    assert scan.report["risk_assessment"]["score"] == 100
    assert scan.report["joysafeter_policy"]["reason"] == "low_issue"
    assert scan.report["joysafeter_policy"]["scanner_recommendation"] == "DO_NOT_INSTALL"


@pytest.mark.asyncio
async def test_scan_for_write_fails_closed_when_scanner_is_unavailable():
    scanner = _ScannerStub(exc=RuntimeError("scanner unavailable"))
    svc = _service(scanner)

    with pytest.raises(InvalidRequestError) as exc_info:
        await svc.scan_for_write(
            trigger="update",
            created_by_id="user_1",
            owner_id="user_1",
            project_id="project_1",
            skill_id=None,
            name="candidate",
            description="candidate skill",
            content="body",
            tags=[],
            license=None,
            files=[],
        )

    assert exc_info.value.code == "SKILL_SECURITY_SCAN_FAILED"
    assert exc_info.value.retryable is True
    assert "scanner unavailable" in exc_info.value.data["error_message"]


@pytest.mark.asyncio
async def test_scan_for_write_uses_candidate_skill_md_and_scans_non_system_files():
    scanner = _ScannerStub(
        {
            "scanner_version": "test",
            "report": {
                "risk_assessment": {
                    "score": 0,
                    "severity": "none",
                    "recommendation": "SAFE",
                },
                "issues": [],
            },
        }
    )
    svc = _service(scanner)

    scan = await svc.scan_for_write(
        trigger="file_update",
        created_by_id="user_1",
        owner_id="user_1",
        project_id="project_1",
        skill_id=None,
        name="new-name",
        description="new description",
        content="new body",
        tags=["analysis"],
        license="Apache-2.0",
        files=[
            {
                "path": "SKILL.md",
                "file_name": "SKILL.md",
                "file_type": "markdown",
                "content": "stale body that must not be scanned",
            },
            {
                "path": "tools/",
                "file_name": "runner.py",
                "file_type": "python",
                "content": "print('scan me')",
            },
            {
                "path": "__pycache__/runner.pyc",
                "file_name": "runner.pyc",
                "file_type": "binary",
                "content": "ignored",
            },
        ],
    )

    files, no_llm = scanner.calls[0]
    assert no_llm is True
    assert scan.status == "passed"
    assert [file.path for file in files] == ["SKILL.md", "tools/runner.py"]
    assert "name: \"new-name\"" in files[0].content
    assert "new body" in files[0].content
    assert "stale body that must not be scanned" not in files[0].content


@pytest.mark.asyncio
async def test_scan_for_write_excludes_license_files_from_scanner_input():
    scanner = _ScannerStub(
        {
            "scanner_version": "test",
            "report": {
                "risk_assessment": {
                    "score": 0,
                    "severity": "none",
                    "recommendation": "SAFE",
                },
                "issues": [],
            },
        }
    )
    svc = _service(scanner)

    await svc.scan_for_write(
        trigger="file_update",
        created_by_id="user_1",
        owner_id="user_1",
        project_id="project_1",
        skill_id=None,
        name="licensed-skill",
        description="licensed skill",
        content="body",
        tags=[],
        license="MIT",
        files=[
            {
                "path": "",
                "file_name": "LICENSE.txt",
                "file_type": "text",
                "content": "legal text that should not drive behavior risk",
            },
            {
                "path": "NOTICE",
                "file_name": "NOTICE",
                "file_type": "text",
                "content": "notice text",
            },
            {
                "path": "tools/",
                "file_name": "runner.py",
                "file_type": "python",
                "content": "print('scan me')",
            },
        ],
    )

    files, _no_llm = scanner.calls[0]
    assert [file.path for file in files] == ["SKILL.md", "tools/runner.py"]


@pytest.mark.asyncio
async def test_scan_for_write_treats_safe_low_zero_score_as_passed():
    scanner = _ScannerStub(
        {
            "scanner_version": "test",
            "report": {
                "risk_assessment": {
                    "score": 0,
                    "severity": "LOW",
                    "recommendation": "SAFE",
                },
                "issues": [],
            },
        }
    )
    svc = _service(scanner)

    scan = await svc.scan_for_write(
        trigger="create",
        created_by_id="user_1",
        owner_id="user_1",
        project_id="project_1",
        skill_id=None,
        name="safe-skill",
        description="safe skill",
        content="body",
        tags=[],
        license=None,
        files=[],
    )

    assert scan.status == "passed"
