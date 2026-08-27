"""Skill scanning, publish enforcement, and async dispatch."""

from __future__ import annotations

# ruff: noqa: E402 — sections merged verbatim; imports intentionally follow their banners

# ============================================================================
# skill_security_service.py
# ============================================================================

"""Skill security scanning service."""


import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_skill import (
    JoySafeterSkill,
    JoySafeterSkillLifecycleStatus,
    JoySafeterSkillSecurityScan,
    JoySafeterSkillSecurityStatus,
)
from app.joysafeter_domain.repositories.joysafeter_skill import SkillRepository, SkillSecurityScanRepository
from app.joysafeter_shared.common.app_errors import (
    AccessDeniedError,
    NotFoundError,
    ResourceConflictError,
)
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure_loguru
from app.joysafeter_shared.common.joysafeter_auth.context import (
    JoySafeterRole,
    ProjectCapability,
)
from app.joysafeter_shared.common.skill_permissions import check_skill_access, resolve_skill_org_id
from app.joysafeter_shared.config.settings import settings
from app.joysafeter_shared.ids import OrganizationId, ProjectId, SkillId, SkillSecurityScanId, UserId
from app.joysafeter_shared.security.ssrf_guard import validate_url
from app.joysafeter_shared.skill.yaml_parser import is_system_file
from app.joysafeter_shared.utils.datetime import utc_now


@dataclass(frozen=True)
class SkillScanFile:
    path: str
    file_name: str
    file_type: str
    content: str


@dataclass(frozen=True)
class SkillSecurityPolicyDecision:
    status: str
    score: int
    severity: str
    recommendation: str
    reason: str

    # ── Module-level pure helpers ────────────────────────────────────────────
    # The hash + scan-files projection used to be private methods on
    # ``SkillSecurityService``. They are pure (no DB, no settings), and
    # publish-time enforcement needs the same canonical projection and hash.


def _ensure_scan_target_mutable(skill: JoySafeterSkill) -> None:
    if getattr(skill, "lifecycle_status", None) == JoySafeterSkillLifecycleStatus.ARCHIVED.value:
        raise ResourceConflictError(
            "Skill is archived and read-only. Unarchive before rescanning.",
            code="SKILL_ARCHIVED",
            data={"skill_id": str(skill.id)},
            retryable=False,
            user_action="refresh",
        )


def _coerce_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _scan_path(file_data: dict[str, Any]) -> str:
    raw_path = str(file_data.get("path") or "").replace("\\", "/").strip()
    file_name = str(file_data.get("file_name") or "").replace("\\", "/").strip()
    if not raw_path:
        return file_name
    if raw_path.endswith("/") and file_name:
        return f"{raw_path}{file_name}"
    if file_name and raw_path.rsplit("/", 1)[-1] != file_name:
        return f"{raw_path.rstrip('/')}/{file_name}"
    return raw_path


def _is_skill_md(path: str, file_name: str) -> bool:
    return path.strip("/").lower() == "skill.md" or file_name.lower() == "skill.md"


def _is_generated_file(path: str, file_name: str) -> bool:
    normalized_path = path.replace("\\", "/").lower()
    normalized_name = file_name.lower()
    parts = [part for part in normalized_path.split("/") if part]
    return (
        "__pycache__" in parts
        or normalized_name.endswith((".pyc", ".pyo"))
        or normalized_name in {".coverage", "coverage.xml"}
    )


def _is_non_security_context_file(path: str, file_name: str) -> bool:
    normalized_path = path.replace("\\", "/").strip("/").lower()
    normalized_name = file_name.lower()
    legal_doc_names = {
        "license",
        "licence",
        "license.txt",
        "licence.txt",
        "license.md",
        "licence.md",
        "copying",
        "copying.txt",
        "notice",
        "notice.txt",
        "notice.md",
    }
    if normalized_name in legal_doc_names:
        return True
    return normalized_path in legal_doc_names


def _generated_skill_md(
    name: str,
    description: str,
    content: str,
    tags: list[str],
    license: Optional[str],
) -> str:
    frontmatter: dict[str, Any] = {
        "name": name,
        "description": description,
    }
    if tags:
        frontmatter["tags"] = tags
    if license:
        frontmatter["license"] = license
    yaml_lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, list):
            yaml_lines.append(f"{key}:")
            yaml_lines.extend(f"  - {item}" for item in value)
        else:
            escaped = str(value).replace('"', '\\"')
            yaml_lines.append(f'{key}: "{escaped}"')
    yaml_lines.extend(["---", "", content or ""])
    return "\n".join(yaml_lines)


def build_scan_files(
    *,
    name: str,
    description: str,
    content: str,
    tags: list[str],
    license: Optional[str],
    files: Optional[list[dict[str, Any]]],
) -> list[SkillScanFile]:
    """Project skill content into the list ``SkillSpector`` consumes.

    Pure function shared by informational scans and enforced publication so
    every scan uses the same canonical file projection.
    """
    scan_files: list[SkillScanFile] = []
    for file_data in files or []:
        path = _scan_path(file_data)
        file_name = str(file_data.get("file_name") or path.rsplit("/", 1)[-1] or "").strip()
        if (
            not path
            or _is_skill_md(path, file_name)
            or is_system_file(path)
            or is_system_file(file_name)
            or _is_generated_file(path, file_name)
            or _is_non_security_context_file(path, file_name)
        ):
            continue
        scan_files.append(
            SkillScanFile(
                path=path,
                file_name=file_name,
                file_type=str(file_data.get("file_type") or "text"),
                content=_coerce_content(file_data.get("content")),
            )
        )

    scan_files.insert(
        0,
        SkillScanFile(
            path="SKILL.md",
            file_name="SKILL.md",
            file_type="markdown",
            content=_generated_skill_md(name, description, content, tags, license),
        ),
    )
    return sorted(scan_files, key=lambda item: item.path)


def target_hash(
    *,
    name: str,
    description: str,
    content: str,
    tags: list[str],
    license: Optional[str],
    files: Iterable[SkillScanFile],
) -> str:
    """Canonical sha256 over scan input. The drift gate compares the
    skill's stored hash against a fresh recompute through this exact
    function — anything subtle (key order, separators, ensure_ascii) has
    to live here, not in the caller."""
    payload = {
        "name": name,
        "description": description,
        "content": content,
        "tags": tags,
        "license": license,
        "files": [
            {
                "path": file.path,
                "file_name": file.file_name,
                "file_type": file.file_type,
                "content": file.content,
            }
            for file in files
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SkillSecurityScannerClient:
    """HTTP client for the internal SkillSpector scanner service."""

    def __init__(self, base_url: str, timeout_seconds: float):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def scan(self, files: list[SkillScanFile], *, no_llm: bool = True) -> dict[str, Any]:
        payload = {
            "no_llm": no_llm,
            "files": [
                {
                    "path": file.path,
                    "file_name": file.file_name,
                    "file_type": file.file_type,
                    "content": file.content,
                }
                for file in files
            ],
        }
        validate_url(self.base_url, context="Skill security scanner URL")
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False) as client:
            response = await client.post(f"{self.base_url}/scan", json=payload)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and isinstance(data.get("report"), dict):
            return data
        if isinstance(data, dict):
            return {"report": data}
        raise ValueError("Skill security scanner returned an invalid response")


class SkillSecurityService:
    """Coordinates informational SkillSpector scans and persistence."""

    _caller_org_role: JoySafeterRole = JoySafeterRole.MEMBER

    def __init__(
        self,
        db: AsyncSession,
        *,
        active_org_id: OrganizationId | None = None,
        caller_org_role: JoySafeterRole = JoySafeterRole.MEMBER,
    ):
        self.db = db
        self.repo = SkillSecurityScanRepository(db)
        self.skill_repo = SkillRepository(db)
        self.client = SkillSecurityScannerClient(
            settings.skill_security_scanner_url,
            settings.skill_security_timeout_seconds,
        )
        # See ``SkillService`` for the same field. Used to
        # pass ``active_org_id`` through to ``check_skill_access`` so
        # scan-history reads / rescan triggers also respect the strict
        # cross-org isolation rule.
        self._active_org_id = active_org_id
        # Caller's org role, threaded into
        # ``check_skill_access`` so org super-users resolve to ADMIN.
        self._caller_org_role = caller_org_role

    async def scan_for_write(
        self,
        *,
        trigger: str,
        created_by_id: UserId,
        owner_id: UserId | None,
        project_id: ProjectId | None,
        skill_id: Optional[SkillId],
        name: str,
        description: str,
        content: str,
        tags: Optional[list[str]],
        license: Optional[str],
        files: Optional[list[dict[str, Any]]],
    ) -> Optional[JoySafeterSkillSecurityScan]:
        """Scan and record a candidate Skill snapshot without enforcing policy.

        This service is deliberately informational. The publish service is the
        only place allowed to turn a scan result into a blocking decision.
        """
        if not settings.skill_security_scan_enabled:
            return None

        scan_files = self._build_scan_files(
            name=name,
            description=description,
            content=content,
            tags=tags or [],
            license=license,
            files=files,
        )
        target_hash = self._target_hash(
            name=name,
            description=description,
            content=content,
            tags=tags or [],
            license=license,
            files=scan_files,
        )

        try:
            response = await self.client.scan(scan_files, no_llm=settings.skill_security_no_llm)
            report = response["report"]
            scan = self._scan_from_report(
                report=report,
                scanner_version=response.get("scanner_version") or self._extract_scanner_version(report),
                ruleset_version=response.get("ruleset_version") or self._extract_ruleset_version(report),
                trigger=trigger,
                created_by_id=created_by_id,
                owner_id=owner_id,
                project_id=project_id,
                skill_id=skill_id,
                target_name=name,
                target_hash=target_hash,
            )
        except Exception as exc:
            log_boundary_failure_loguru(
                logger,
                boundary="skill_security",
                code="SKILL_SECURITY_SCAN_FAILED",
                message="Skill security scan failed",
                operation="scan_skill",
                error=exc,
                data={
                    "skill_id": str(skill_id) if skill_id else "",
                    "project_id": str(project_id) if project_id else "",
                    "trigger": trigger,
                    "target_hash": target_hash,
                },
            )
            scan = JoySafeterSkillSecurityScan(
                id=SkillSecurityScanId.new(),
                skill_id=skill_id,
                project_id=project_id,
                owner_id=owner_id,
                created_by_id=created_by_id,
                trigger=trigger,
                target_name=name,
                target_hash=target_hash,
                scanner="skillspector",
                scanner_version=None,
                status=JoySafeterSkillSecurityStatus.FAILED.value,
                score=None,
                severity=None,
                recommendation=None,
                issues_count=0,
                critical_count=0,
                high_count=0,
                medium_count=0,
                low_count=0,
                report=None,
                error_message=str(exc),
            )
            self.db.add(scan)
            await self.db.flush()
            return scan

        self.db.add(scan)
        await self.db.flush()
        return scan

    async def rescan_existing_skill(self, skill_id: SkillId, current_user_id: UserId) -> JoySafeterSkillSecurityScan:
        """Rescan persisted skill content and update the skill's current security state."""
        skill = await self.skill_repo.get_with_files(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            ProjectCapability.WRITE,
            caller_org_role=self._caller_org_role,
            active_org_id=self._active_org_id,
        )
        _ensure_scan_target_mutable(skill)

        scan = await self.scan_for_write(
            trigger="manual",
            created_by_id=current_user_id,
            owner_id=skill.owner_id,
            project_id=skill.project_id,
            skill_id=skill.id,
            name=skill.name,
            description=skill.description,
            content=skill.content,
            tags=list(skill.tags or []),
            license=skill.license,
            files=self.files_from_skill(skill),
        )
        if scan is None:
            scan = JoySafeterSkillSecurityScan(
                id=SkillSecurityScanId.new(),
                skill_id=skill.id,
                project_id=skill.project_id,
                owner_id=skill.owner_id,
                created_by_id=current_user_id,
                trigger="manual",
                target_name=skill.name,
                target_hash=self._target_hash(
                    name=skill.name,
                    description=skill.description,
                    content=skill.content,
                    tags=list(skill.tags or []),
                    license=skill.license,
                    files=self._build_scan_files(
                        name=skill.name,
                        description=skill.description,
                        content=skill.content,
                        tags=list(skill.tags or []),
                        license=skill.license,
                        files=self.files_from_skill(skill),
                    ),
                ),
                scanner="skillspector",
                status=JoySafeterSkillSecurityStatus.NOT_SCANNED.value,
                score=None,
                severity=None,
                recommendation=None,
                report=None,
            )
            self.db.add(scan)
            await self.db.flush()
        self.apply_latest_scan(skill, scan)
        await self.db.commit()
        await self.db.refresh(scan)
        return scan

    async def list_scans(
        self,
        skill_id: SkillId,
        current_user_id: UserId,
        project_id: ProjectId | None = None,
        limit: int = 20,
        after_id: Optional[SkillSecurityScanId] = None,
    ) -> tuple[list[JoySafeterSkillSecurityScan], bool]:
        skill = await self.skill_repo.get(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            ProjectCapability.READ,
            caller_org_role=self._caller_org_role,
            active_org_id=self._active_org_id,
        )
        await self._ensure_scan_read_scope(skill, project_id)
        return await self.repo.list_by_skill(skill_id, limit=limit, after_id=after_id)

    async def get_latest_scan(
        self,
        skill_id: SkillId,
        current_user_id: UserId,
        project_id: ProjectId | None = None,
    ) -> JoySafeterSkillSecurityScan:
        skill = await self.skill_repo.get(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            ProjectCapability.READ,
            caller_org_role=self._caller_org_role,
            active_org_id=self._active_org_id,
        )
        await self._ensure_scan_read_scope(skill, project_id)
        scan = await self.repo.get_latest_by_skill(skill_id)
        if not scan:
            raise NotFoundError(
                "Skill security scan not found",
                code="SKILL_SECURITY_SCAN_NOT_FOUND",
                data={"skill_id": str(skill_id)},
            )
        return scan

    async def get_scan(
        self,
        scan_id: SkillSecurityScanId,
        current_user_id: UserId,
        project_id: ProjectId | None = None,
    ) -> JoySafeterSkillSecurityScan:
        scan = await self.repo.get(scan_id)
        if not scan:
            raise NotFoundError(
                "Skill security scan not found",
                code="SKILL_SECURITY_SCAN_NOT_FOUND",
                data={"scan_id": str(scan_id)},
            )
        if scan.skill_id:
            skill = await self.skill_repo.get(scan.skill_id)
            if not skill:
                raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(scan.skill_id)})
            await check_skill_access(
                self.db,
                skill,
                current_user_id,
                ProjectCapability.READ,
                caller_org_role=self._caller_org_role,
                active_org_id=self._active_org_id,
            )
            await self._ensure_scan_read_scope(skill, project_id)
        elif scan.created_by_id != current_user_id and scan.owner_id != current_user_id:
            raise AccessDeniedError(
                "You don't have permission to access this scan",
                code="SKILL_SECURITY_SCAN_ACCESS_DENIED",
            )
        return scan

    async def _ensure_scan_read_scope(self, skill: JoySafeterSkill, project_id: ProjectId | None) -> None:
        if project_id is not None and project_id == skill.project_id:
            return
        skill_org_id = await resolve_skill_org_id(self.db, skill)
        if skill_org_id == self._active_org_id and self._caller_org_role.is_org_superuser():
            return
        raise AccessDeniedError(
            "Security scan reports are only available inside the owning project",
            code="SKILL_SECURITY_SCAN_ACCESS_DENIED",
            data={"skill_id": str(skill.id)},
        )

    def apply_latest_scan(self, skill: JoySafeterSkill, scan: JoySafeterSkillSecurityScan) -> None:
        """Copy the latest scan summary onto the skill row for list/detail APIs."""
        if (
            skill.security_scanned_at is not None
            and isinstance(scan.created_at, datetime)
            and scan.created_at < skill.security_scanned_at
        ):
            return
        skill.security_status = scan.status
        skill.security_score = scan.score
        skill.security_severity = scan.severity
        skill.security_recommendation = scan.recommendation
        skill.security_scanned_at = scan.created_at if isinstance(scan.created_at, datetime) else utc_now()
        skill.security_scan_id = scan.id
        skill.security_scan_hash = scan.target_hash
        skill.security_issues_count = scan.issues_count
        skill.security_critical_count = scan.critical_count
        skill.security_high_count = scan.high_count
        skill.security_medium_count = scan.medium_count
        skill.security_low_count = scan.low_count

    def files_from_skill(self, skill: JoySafeterSkill) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for file_obj in skill.files or []:
            result.append(
                {
                    "path": file_obj.path,
                    "file_name": file_obj.file_name,
                    "file_type": file_obj.file_type,
                    "content": file_obj.content or "",
                    "storage_type": file_obj.storage_type,
                    "storage_key": file_obj.storage_key,
                    "size": file_obj.size,
                }
            )
        return result

    def _build_scan_files(
        self,
        *,
        name: str,
        description: str,
        content: str,
        tags: list[str],
        license: Optional[str],
        files: Optional[list[dict[str, Any]]],
    ) -> list[SkillScanFile]:
        return build_scan_files(
            name=name,
            description=description,
            content=content,
            tags=tags,
            license=license,
            files=files,
        )

    def _generated_skill_md(
        self,
        name: str,
        description: str,
        content: str,
        tags: list[str],
        license: Optional[str],
    ) -> str:
        return _generated_skill_md(name, description, content, tags, license)

    def _scan_path(self, file_data: dict[str, Any]) -> str:
        return _scan_path(file_data)

    def _is_skill_md(self, path: str, file_name: str) -> bool:
        return _is_skill_md(path, file_name)

    def _is_generated_file(self, path: str, file_name: str) -> bool:
        return _is_generated_file(path, file_name)

    def _is_non_security_context_file(self, path: str, file_name: str) -> bool:
        return _is_non_security_context_file(path, file_name)

    def _target_hash(
        self,
        *,
        name: str,
        description: str,
        content: str,
        tags: list[str],
        license: Optional[str],
        files: Iterable[SkillScanFile],
    ) -> str:
        return target_hash(
            name=name,
            description=description,
            content=content,
            tags=tags,
            license=license,
            files=files,
        )

    def _scan_from_report(
        self,
        *,
        report: dict[str, Any],
        scanner_version: Optional[str],
        ruleset_version: Optional[str],
        trigger: str,
        created_by_id: UserId,
        owner_id: UserId | None,
        project_id: ProjectId | None,
        skill_id: Optional[SkillId],
        target_name: str,
        target_hash: str,
    ) -> JoySafeterSkillSecurityScan:
        raw_risk = report.get("risk_assessment")
        risk: dict[str, Any] = raw_risk if isinstance(raw_risk, dict) else {}
        scanner_score = self._coerce_int(risk.get("score"))
        scanner_severity = self._coerce_upper(risk.get("severity"))
        scanner_recommendation = self._coerce_upper(risk.get("recommendation"))
        counts = self._issue_counts(report.get("issues"))
        decision = self._policy_decision(
            counts=counts,
            scanner_recommendation=scanner_recommendation,
            scanner_severity=scanner_severity,
            scanner_score=scanner_score,
        )
        report = self._report_with_policy(
            report=report,
            decision=decision,
            scanner_recommendation=scanner_recommendation,
            scanner_severity=scanner_severity,
            scanner_score=scanner_score,
        )
        return JoySafeterSkillSecurityScan(
            id=SkillSecurityScanId.new(),
            skill_id=skill_id,
            project_id=project_id,
            owner_id=owner_id,
            created_by_id=created_by_id,
            trigger=trigger,
            target_name=target_name,
            target_hash=target_hash,
            scanner="skillspector",
            scanner_version=scanner_version,
            ruleset_version=ruleset_version,
            status=decision.status,
            score=decision.score,
            severity=decision.severity,
            recommendation=decision.recommendation,
            issues_count=counts["issues"],
            critical_count=counts["critical"],
            high_count=counts["high"],
            medium_count=counts["medium"],
            low_count=counts["low"],
            report=report,
            error_message=None,
        )

    def _policy_decision(
        self,
        *,
        counts: dict[str, int],
        scanner_recommendation: Optional[str],
        scanner_severity: Optional[str],
        scanner_score: Optional[int],
    ) -> SkillSecurityPolicyDecision:
        """Normalize scanner output into JoySafeter's risk verdict.

        SkillSpector's aggregate score intentionally accumulates many LOW findings. For product
        risk reporting, a large number of LOW findings should surface as reviewable risk, not as an
        automatic publication block. Blocking is reserved for concrete HIGH/CRITICAL findings or
        for aggregate-only scanner results where no finding details are available.
        """
        if counts["critical"] > 0:
            score = min(100, 90 + (counts["critical"] - 1) * 5 + counts["high"] * 3 + counts["medium"])
            return SkillSecurityPolicyDecision(
                JoySafeterSkillSecurityStatus.BLOCKED.value, score, "CRITICAL", "DO_NOT_INSTALL", "critical_issue"
            )

        if counts["high"] > 0:
            score = min(89, 70 + (counts["high"] - 1) * 5 + counts["medium"] * 2 + min(counts["low"], 10))
            return SkillSecurityPolicyDecision(
                JoySafeterSkillSecurityStatus.BLOCKED.value, score, "HIGH", "DO_NOT_INSTALL", "high_issue"
            )

        if counts["medium"] > 0:
            score = min(69, 30 + (counts["medium"] - 1) * 5 + min(counts["low"], 10))
            return SkillSecurityPolicyDecision(
                JoySafeterSkillSecurityStatus.WARNING.value, score, "MEDIUM", "CAUTION", "medium_issue"
            )

        if counts["low"] > 0:
            score = min(29, 5 + min(counts["low"] * 2, 24))
            return SkillSecurityPolicyDecision(
                JoySafeterSkillSecurityStatus.WARNING.value, score, "LOW", "CAUTION", "low_issue"
            )

        if counts["issues"] > 0:
            score = min(49, max(1, scanner_score or counts["issues"]))
            return SkillSecurityPolicyDecision(
                JoySafeterSkillSecurityStatus.WARNING.value, score, "LOW", "CAUTION", "unknown_issue_severity"
            )

        if self._scanner_aggregate_blocks(scanner_recommendation, scanner_severity, scanner_score):
            score = min(100, max(70, scanner_score or 70))
            severity = scanner_severity if scanner_severity in {"HIGH", "CRITICAL"} else "HIGH"
            return SkillSecurityPolicyDecision(
                JoySafeterSkillSecurityStatus.BLOCKED.value,
                score,
                severity,
                "DO_NOT_INSTALL",
                "scanner_aggregate_without_issue_details",
            )

        if scanner_recommendation == "CAUTION" or (scanner_score is not None and scanner_score > 0):
            score = min(49, max(1, scanner_score or 1))
            severity = scanner_severity if scanner_severity in {"MEDIUM", "LOW"} else "LOW"
            return SkillSecurityPolicyDecision(
                JoySafeterSkillSecurityStatus.WARNING.value,
                score,
                severity,
                "CAUTION",
                "scanner_caution_without_issues",
            )

        return SkillSecurityPolicyDecision(JoySafeterSkillSecurityStatus.PASSED.value, 0, "LOW", "SAFE", "no_issues")

    def _scanner_aggregate_blocks(
        self,
        recommendation: Optional[str],
        severity: Optional[str],
        score: Optional[int],
    ) -> bool:
        block_recommendations = {item.upper() for item in settings.skill_security_block_recommendations}
        return (
            bool(recommendation and recommendation in block_recommendations)
            or severity in {"HIGH", "CRITICAL"}
            or (score is not None and score >= 70)
        )

    def _report_with_policy(
        self,
        *,
        report: dict[str, Any],
        decision: SkillSecurityPolicyDecision,
        scanner_recommendation: Optional[str],
        scanner_severity: Optional[str],
        scanner_score: Optional[int],
    ) -> dict[str, Any]:
        enriched = dict(report)
        enriched["joysafeter_policy"] = {
            "status": decision.status,
            "score": decision.score,
            "severity": decision.severity,
            "recommendation": decision.recommendation,
            "reason": decision.reason,
            "scanner_score": scanner_score,
            "scanner_severity": scanner_severity,
            "scanner_recommendation": scanner_recommendation,
        }
        return enriched

    def error_data(self, scan: JoySafeterSkillSecurityScan) -> dict[str, Any]:
        report = scan.report if isinstance(scan.report, dict) else {}
        return {
            "scan_id": str(scan.id),
            "status": scan.status,
            "score": scan.score,
            "severity": scan.severity,
            "recommendation": scan.recommendation,
            "issues_count": scan.issues_count,
            "critical_count": scan.critical_count,
            "high_count": scan.high_count,
            "medium_count": scan.medium_count,
            "low_count": scan.low_count,
            "issues": report.get("issues") if isinstance(report.get("issues"), list) else [],
        }

    def _issue_counts(self, issues: Any) -> dict[str, int]:
        counts = {"issues": 0, "critical": 0, "high": 0, "medium": 0, "low": 0}
        if not isinstance(issues, list):
            return counts
        counts["issues"] = len(issues)
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            severity = self._coerce_upper(
                issue.get("severity") or issue.get("level") or issue.get("risk") or issue.get("priority")
            )
            if severity == "CRITICAL":
                counts["critical"] += 1
            elif severity == "HIGH":
                counts["high"] += 1
            elif severity == "MEDIUM":
                counts["medium"] += 1
            elif severity == "LOW":
                counts["low"] += 1
        return counts

    def _extract_scanner_version(self, report: dict[str, Any]) -> Optional[str]:
        metadata = report.get("metadata")
        if isinstance(metadata, dict):
            version = metadata.get("scanner_version") or metadata.get("version")
            return str(version) if version is not None else None
        return None

    def _extract_ruleset_version(self, report: dict[str, Any]) -> Optional[str]:
        """Pull the ruleset version from the report payload.

        SkillSpector can surface this at the top level (``response.ruleset_version``)
        or nested under ``report.metadata`` (``ruleset_version`` / ``rules_version`` /
        ``ruleset``). The top-level reading happens in the caller; this helper
        covers the metadata fallback so a scanner build that only writes the field
        into the report body still flows through.
        """
        metadata = report.get("metadata")
        if isinstance(metadata, dict):
            version = metadata.get("ruleset_version") or metadata.get("rules_version") or metadata.get("ruleset")
            return str(version) if version is not None else None
        return None

    def _coerce_upper(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None

    def _coerce_int(self, value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

            # ── Async dispatch decision ────────────────────────────────

    @staticmethod
    def should_scan_async(
        *,
        name: str,
        description: str,
        content: str,
        files: Optional[list[dict[str, Any]]],
    ) -> bool:
        """Return ``True`` when the caller should defer to a
        FastAPI BackgroundTask instead of running the scan inline.

        The threshold lives in ``settings.skill_security_async_threshold_bytes``
        so deployments can tune it without code changes. A non-positive
        threshold forces every scan async; a very large threshold keeps
        the original sync-only behavior.
        """

        threshold = settings.skill_security_async_threshold_bytes
        if threshold <= 0:
            return True
        size = scan_input_bytes(
            name=name,
            description=description,
            content=content,
            files=files,
        )
        return size >= threshold

    async def mark_scanning(self, skill_id: SkillId) -> None:
        """Flip the skill row to ``security_status='scanning'`` so API clients
        can display that a background scan is in flight.

        Used by the API layer in the async-dispatch path:

            1. ``SkillSecurityService.should_scan_async(...)`` → True
            2. ``svc.mark_scanning(skill_id)`` + commit
            3. ``background_tasks.add_task(run_scan_in_background, ...)``

        Idempotent: calling on a row that's already ``scanning`` is a
        no-op; calling on a row in any other state writes ``scanning``.
        """
        from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill

        skill = await self.db.get(JoySafeterSkill, skill_id)
        if skill is None:
            return
        if skill.security_status != JoySafeterSkillSecurityStatus.SCANNING.value:
            skill.security_status = JoySafeterSkillSecurityStatus.SCANNING.value
            await self.db.flush()


# ============================================================================
# skill_async_scan.py
# ============================================================================

"""Background skill security scans.

Async scan dispatch handles skills whose content is too big
to comfortably block the request — see ``Settings.skill_security_async_threshold_bytes``.
The async path:

  1. Caller computes the input size via :func:`scan_input_bytes`.
  2. If it's >= the threshold (and async is allowed), caller marks the
     skill row ``security_status='scanning'``, commits, and schedules
     :func:`run_scan_in_background` on a FastAPI ``BackgroundTasks``.
  3. The background task opens its own async DB session, calls the
     same :meth:`SkillSecurityService.scan_for_write` with
     ``mode='sync'`` to actually hit SkillSpector, and then writes the
     verdict back onto the skill row + commits.

The async path uses a separate ``AsyncSession`` so it doesn't depend on
the request-scoped DB session that already closed by the time the BG
task runs.

The ``scanning`` state is informational and never affects published versions.
"""


def scan_input_bytes(
    *,
    name: str,
    description: str,
    content: str,
    files: Optional[list[dict[str, Any]]],
) -> int:
    """Approximate total size of what SkillSpector will receive.

    Used to decide between sync and async dispatch. We deliberately
    keep this cheap — sum of UTF-8 bytes for the user-visible
    surface — rather than constructing the canonical scan files (that
    would double the work for skills near the threshold). Drift in
    this estimate vs the real payload is fine; the threshold is a
    soft hint, not a hard contract.
    """
    total = len(name.encode("utf-8")) + len(description.encode("utf-8"))
    total += len(content.encode("utf-8"))
    for file_data in files or []:
        body = file_data.get("content") or ""
        if isinstance(body, str):
            total += len(body.encode("utf-8"))
        elif isinstance(body, (bytes, bytearray)):
            total += len(body)
    return total


async def run_scan_in_background(
    *,
    skill_id: SkillId,
    trigger: str,
    created_by_id: UserId,
    owner_id: UserId | None,
    project_id: ProjectId | None,
    name: str,
    description: str,
    content: str,
    tags: Optional[list[str]],
    license: Optional[str],
    files: Optional[list[dict[str, Any]]],
) -> None:
    """Run a forced-sync scan against the persisted skill content and
    write the verdict back. Designed to be wired into FastAPI's
    ``BackgroundTasks.add_task(...)``.

    Failure handling: scanner failures return a ``failed`` scan via
    ``scan_for_write(...)``. If the background task
    itself fails outside that scanner path, record a synthetic ``failed`` scan
    with a structured error payload and apply it to the skill row. This avoids
    leaving clients stuck on the transient ``scanning`` state.

    The function lives in this module (not inside the service) because
    it needs to open a fresh DB session — the request's session has
    long since been closed by the time the BG task runs.
    """
    # Lazy imports keep the orchestrator import graph clean: this
    # module is loaded by the FastAPI request path, but the BG task
    # only needs the session factory and the service when invoked.
    from sqlalchemy import select as _bg_select

    from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill
    from app.joysafeter_shared.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            svc = SkillSecurityService(db)
            scan = await svc.scan_for_write(
                trigger=trigger,
                created_by_id=created_by_id,
                owner_id=owner_id,
                project_id=project_id,
                skill_id=skill_id,
                name=name,
                description=description,
                content=content,
                tags=tags,
                license=license,
                files=files,
            )
            if scan is None:
                # Scanner disabled at the deployment level — clear the
                # ``scanning`` placeholder so clients stop treating the row as in-flight.
                skill = await db.get(JoySafeterSkill, skill_id)
                if skill and skill.security_status == JoySafeterSkillSecurityStatus.SCANNING.value:
                    skill.security_status = JoySafeterSkillSecurityStatus.NOT_SCANNED.value
                    await db.commit()
                return
                # Refresh the skill row with the latest verdict.
            _bg_result = await db.execute(
                _bg_select(JoySafeterSkill).where(JoySafeterSkill.id == skill_id).with_for_update()
            )
            skill = _bg_result.scalar_one_or_none()
            if skill is None:
                log_boundary_failure_loguru(
                    logger,
                    boundary="skill_security",
                    code="SKILL_SECURITY_ASYNC_SCAN_TARGET_MISSING",
                    message="Skill vanished before async scan finished; verdict dropped",
                    operation="apply_async_scan_verdict",
                    data={"skill_id": str(skill_id), "trigger": trigger, "project_id": project_id},
                    retryable=False,
                    user_action=None,
                )
                return
            svc.apply_latest_scan(skill, scan)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — see docstring
            error_payload = async_boundary_error_payload(
                code="SKILL_SECURITY_BACKGROUND_SCAN_FAILED",
                message="Background skill security scan failed",
                boundary="skill_security",
                operation="run_background_scan",
                data={
                    "skill_id": str(skill_id),
                    "trigger": trigger,
                    "project_id": str(project_id) if project_id is not None else None,
                    "owner_id": str(owner_id) if owner_id is not None else None,
                },
                source="runtime",
                retryable=True,
                user_action="retry",
                detail=exc.__class__.__name__,
            )
            logger.exception(
                "Background skill security scan failed for skill_id=%s",
                skill_id,
                extra={"error": error_payload},
            )
            try:
                await db.rollback()
            except Exception:
                logger.debug("Failed to rollback after background skill scan failure", exc_info=True)
            try:
                svc = SkillSecurityService(db)
                scan_files = svc._build_scan_files(
                    name=name,
                    description=description,
                    content=content,
                    tags=tags or [],
                    license=license,
                    files=files,
                )
                target_hash = svc._target_hash(
                    name=name,
                    description=description,
                    content=content,
                    tags=tags or [],
                    license=license,
                    files=scan_files,
                )
                failed_scan = JoySafeterSkillSecurityScan(
                    id=SkillSecurityScanId.new(),
                    skill_id=skill_id,
                    project_id=project_id,
                    owner_id=owner_id,
                    created_by_id=created_by_id,
                    trigger=trigger,
                    target_name=name,
                    target_hash=target_hash,
                    scanner="skillspector",
                    scanner_version=None,
                    status=JoySafeterSkillSecurityStatus.FAILED.value,
                    score=None,
                    severity=None,
                    recommendation=None,
                    issues_count=0,
                    critical_count=0,
                    high_count=0,
                    medium_count=0,
                    low_count=0,
                    report={"error": error_payload},
                    error_message=error_payload["message"],
                )
                db.add(failed_scan)
                await db.flush()
                _fail_result = await db.execute(
                    _bg_select(JoySafeterSkill).where(JoySafeterSkill.id == skill_id).with_for_update()
                )
                skill = _fail_result.scalar_one_or_none()
                if skill and skill.security_status == JoySafeterSkillSecurityStatus.SCANNING.value:
                    svc.apply_latest_scan(skill, failed_scan)
                await db.commit()
            except Exception:
                logger.exception(
                    "Failed to record background skill security scan failure for skill_id=%s",
                    skill_id,
                    extra={"error": error_payload},
                )
