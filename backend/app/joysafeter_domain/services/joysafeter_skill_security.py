"""
JoySafeter skill security services.

Merged from skill_security_service.py, skill_runtime_policy.py,
skill_packer.py, and skill_async_scan.py (v1 cleanup consolidation):
  - SkillScanFile / SkillSecurityPolicyDecision / SkillSecurityService — SkillSpector scans
  - is_skill_usable — runtime gate (lifecycle + security + hash drift)
  - SkillPacker — pack approved skills into tar.gz bundles
  - scan_input_bytes / run_scan_in_background — async scan dispatch
"""

from __future__ import annotations

# ruff: noqa: E402 — sections merged verbatim; imports intentionally follow their banners

# ============================================================================
# skill_security_service.py
# ============================================================================

"""Skill security scanning service."""


import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Literal, Optional

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_skill import (
    JoySafeterCollaboratorRole,
    JoySafeterSkill,
    JoySafeterSkillLifecycleStatus,
    JoySafeterSkillSecurityScan,
)
from app.joysafeter_domain.repositories.joysafeter_skill import SkillRepository, SkillSecurityScanRepository
from app.joysafeter_shared.common.app_errors import (
    AccessDeniedError,
    InvalidRequestError,
    NotFoundError,
    ResourceConflictError,
)
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure_loguru
from app.joysafeter_shared.common.skill_permissions import check_skill_access
from app.joysafeter_shared.config.settings import settings
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
    # ``SkillSecurityService``. They are pure (no DB, no settings), and the
    # runtime gate in ``skill_runtime_policy`` needs the same definitions to
    # detect drift. Lifting them to the module avoids ``__new__`` tricks at
    # the call site and keeps the canonical definition in one place — the
    # service still wraps them so existing call sites stay unchanged.


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

    Pure function used by both ``scan_for_write`` and the runtime drift
    gate (``skill_runtime_policy``) so the two paths agree on which files
    are part of the canonical scan input.
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
    """Coordinates SkillSpector scans, persistence, and write policy."""

    def __init__(self, db: AsyncSession, *, active_org_id: Optional[str] = None):
        self.db = db
        self.repo = SkillSecurityScanRepository(db)
        self.skill_repo = SkillRepository(db)
        self.client = SkillSecurityScannerClient(
            settings.skill_security_scanner_url,
            settings.skill_security_timeout_seconds,
        )
        # P2.9 — see ``SkillService`` for the same field. Used to
        # pass ``active_org_id`` through to ``check_skill_access`` so
        # scan-history reads / rescan triggers also respect the strict
        # cross-org isolation rule.
        self._active_org_id = active_org_id

    async def scan_for_write(
        self,
        *,
        enforce_write_policy: bool = True,
        failure_mode: Literal["default", "fail_open", "fail_closed"] = "default",
        trigger: str,
        created_by_id: str,
        owner_id: Optional[str],
        project_id: Optional[str],
        skill_id: Optional[uuid.UUID],
        name: str,
        description: str,
        content: str,
        tags: Optional[list[str]],
        license: Optional[str],
        files: Optional[list[dict[str, Any]]],
    ) -> Optional[JoySafeterSkillSecurityScan]:
        """Scan a candidate skill before it is persisted.

        :param enforce_write_policy: When ``True``, a ``blocked`` verdict
            raises ``SKILL_SECURITY_SCAN_REJECTED`` so the caller's write
            path aborts. ``False`` returns the scan row for inspection
            instead (used by ``rescan_existing_skill``, which only
            refreshes the cached verdict).
        :param failure_mode: Independent control over what happens when
            SkillSpector itself is unreachable / times out / 5xx's. Three
            values:

              - ``"default"`` — fall back to ``settings.skill_security_fail_closed``
                (preserves the pre-P0 behavior; this is the right pick for
                callers that aren't sure whether their write is a draft
                save or a runnable artifact).
              - ``"fail_open"`` — record a ``failed`` scan and return it,
                never raise. Used by the draft-save trigger paths
                (``create`` / ``update`` / ``file_*``): a scanner outage
                shouldn't block the owner from saving in-progress work.
              - ``"fail_closed"`` — record the ``failed`` scan and raise
                ``SKILL_SECURITY_SCAN_FAILED``. Used by paths where the
                scan result is a runtime prerequisite (publish, manual
                rescan, or future "promote to approved" flows).

            ``enforce_write_policy=False`` always overrides ``failure_mode``
            for the scanner-failure path: a rescan that just wants the
            verdict refreshed never raises, regardless of ``failure_mode``.
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
                skill_id=skill_id,
                project_id=project_id,
                owner_id=owner_id,
                created_by_id=created_by_id,
                trigger=trigger,
                target_name=name,
                target_hash=target_hash,
                scanner="skillspector",
                scanner_version=None,
                status="failed",
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
            # Decide whether a scanner outage should abort the write. The
            # caller's `failure_mode` wins over the global setting so
            # draft saves can stay fail-open even when the deployment
            # default is fail-closed.
            if failure_mode == "fail_closed":
                should_fail_closed = True
            elif failure_mode == "fail_open":
                should_fail_closed = False
            else:
                should_fail_closed = settings.skill_security_fail_closed
            if enforce_write_policy and should_fail_closed:
                await self.db.commit()
                raise InvalidRequestError(
                    "Skill security scan failed",
                    code="SKILL_SECURITY_SCAN_FAILED",
                    data={
                        "scan_id": str(scan.id),
                        "status": scan.status,
                        "error_message": scan.error_message,
                    },
                    retryable=True,
                ) from exc
            return scan

        self.db.add(scan)
        await self.db.flush()
        if enforce_write_policy and self._is_blocked(scan):
            await self.db.commit()
            raise InvalidRequestError(
                "Skill security scan rejected this skill",
                code="SKILL_SECURITY_SCAN_REJECTED",
                data=self._error_data(scan),
            )
        return scan

    async def rescan_existing_skill(self, skill_id: uuid.UUID, current_user_id: str) -> JoySafeterSkillSecurityScan:
        """Rescan persisted skill content and update the skill's current security state."""
        skill = await self.skill_repo.get_with_files(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        await check_skill_access(
            self.db, skill, current_user_id, JoySafeterCollaboratorRole.EDITOR, active_org_id=self._active_org_id
        )
        _ensure_scan_target_mutable(skill)

        scan = await self.scan_for_write(
            enforce_write_policy=False,
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
                status="not_scanned",
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
        skill_id: uuid.UUID,
        current_user_id: str,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
    ) -> tuple[list[JoySafeterSkillSecurityScan], bool]:
        skill = await self.skill_repo.get(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        await check_skill_access(
            self.db, skill, current_user_id, JoySafeterCollaboratorRole.VIEWER, active_org_id=self._active_org_id
        )
        return await self.repo.list_by_skill(skill_id, limit=limit, after_id=after_id)

    async def get_latest_scan(self, skill_id: uuid.UUID, current_user_id: str) -> JoySafeterSkillSecurityScan:
        skill = await self.skill_repo.get(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        await check_skill_access(
            self.db, skill, current_user_id, JoySafeterCollaboratorRole.VIEWER, active_org_id=self._active_org_id
        )
        scan = await self.repo.get_latest_by_skill(skill_id)
        if not scan:
            raise NotFoundError(
                "Skill security scan not found",
                code="SKILL_SECURITY_SCAN_NOT_FOUND",
                data={"skill_id": str(skill_id)},
            )
        return scan

    async def get_scan(self, scan_id: uuid.UUID, current_user_id: str) -> JoySafeterSkillSecurityScan:
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
                self.db, skill, current_user_id, JoySafeterCollaboratorRole.VIEWER, active_org_id=self._active_org_id
            )
        elif scan.created_by_id != current_user_id and scan.owner_id != current_user_id:
            raise AccessDeniedError(
                "You don't have permission to access this scan",
                code="SKILL_SECURITY_SCAN_ACCESS_DENIED",
            )
        return scan

    def apply_latest_scan(self, skill: JoySafeterSkill, scan: JoySafeterSkillSecurityScan) -> None:
        """Copy the latest scan summary onto the skill row for list/detail APIs."""
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
        created_by_id: str,
        owner_id: Optional[str],
        project_id: Optional[str],
        skill_id: Optional[uuid.UUID],
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
        """Normalize scanner output into JoySafeter's write-admission policy.

        SkillSpector's aggregate score intentionally accumulates many LOW findings. For product
        write policy, a large number of LOW findings should surface as reviewable risk, not as an
        automatic install block. Blocking is reserved for concrete HIGH/CRITICAL findings or for
        aggregate-only scanner results where no finding details are available.
        """
        if counts["critical"] > 0:
            score = min(100, 90 + (counts["critical"] - 1) * 5 + counts["high"] * 3 + counts["medium"])
            return SkillSecurityPolicyDecision("blocked", score, "CRITICAL", "DO_NOT_INSTALL", "critical_issue")

        if counts["high"] > 0:
            score = min(89, 70 + (counts["high"] - 1) * 5 + counts["medium"] * 2 + min(counts["low"], 10))
            return SkillSecurityPolicyDecision("blocked", score, "HIGH", "DO_NOT_INSTALL", "high_issue")

        if counts["medium"] > 0:
            score = min(69, 30 + (counts["medium"] - 1) * 5 + min(counts["low"], 10))
            return SkillSecurityPolicyDecision("warning", score, "MEDIUM", "CAUTION", "medium_issue")

        if counts["low"] > 0:
            score = min(29, 5 + min(counts["low"] * 2, 24))
            return SkillSecurityPolicyDecision("warning", score, "LOW", "CAUTION", "low_issue")

        if counts["issues"] > 0:
            score = min(49, max(1, scanner_score or counts["issues"]))
            return SkillSecurityPolicyDecision("warning", score, "LOW", "CAUTION", "unknown_issue_severity")

        if self._scanner_aggregate_blocks(scanner_recommendation, scanner_severity, scanner_score):
            score = min(100, max(70, scanner_score or 70))
            severity = scanner_severity if scanner_severity in {"HIGH", "CRITICAL"} else "HIGH"
            return SkillSecurityPolicyDecision(
                "blocked",
                score,
                severity,
                "DO_NOT_INSTALL",
                "scanner_aggregate_without_issue_details",
            )

        if scanner_recommendation == "CAUTION" or (scanner_score is not None and scanner_score > 0):
            score = min(49, max(1, scanner_score or 1))
            severity = scanner_severity if scanner_severity in {"MEDIUM", "LOW"} else "LOW"
            return SkillSecurityPolicyDecision("warning", score, severity, "CAUTION", "scanner_caution_without_issues")

        return SkillSecurityPolicyDecision("passed", 0, "LOW", "SAFE", "no_issues")

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

    def _is_blocked(self, scan: JoySafeterSkillSecurityScan) -> bool:
        return scan.status == "blocked" or (scan.status == "failed" and settings.skill_security_fail_closed)

    def _error_data(self, scan: JoySafeterSkillSecurityScan) -> dict[str, Any]:
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

            # ── P2: async dispatch decision ────────────────────────────────

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
        the pre-P2 sync-only behavior.
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

    async def mark_scanning(self, skill_id: uuid.UUID) -> None:
        """Flip the skill row to ``security_status='scanning'`` so the
        runtime gate refuses to load while a BG scan is in flight.

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
        if skill.security_status != "scanning":
            skill.security_status = "scanning"
            await self.db.flush()


# ============================================================================
# skill_runtime_policy.py
# ============================================================================

"""Runtime policy gate for skills.

A single function the runtime calls before loading a skill into a sandbox.
Centralizes the three checks any loader needs:

  1. ``lifecycle_status == 'approved'`` — owner has not paused or retired
     the skill (P0 universally returns ``approved``, so this is a no-op
     until P1 turns on the state machine; the gate is wired now so the
     loader contract doesn't change again later).
  2. ``security_status in {'passed', 'warning'}`` — SkillSpector has not
     blocked the skill outright.
  3. ``security_scan_hash`` matches a fresh recompute of the skill's
     current content. This is the **drift gate**: if the owner edited a
     file or the description after the last scan, the cached verdict no
     longer reflects what the runtime would actually load. The skill is
     refused until the owner runs ``POST /skills/{id}/security-scans/rescan``.

The function intentionally does NOT raise. It returns a verdict tuple so
the caller can choose between "skip this skill silently" (the
:class:`SkillPacker` path: an unusable skill is just absent from the
session's bundle, the rest of the agent still runs) and "fail loud"
(future API validation paths).

P2 adds a ``scanning`` intermediate state for the async scan flow —
treated as "no scan completed" until SkillSpector returns.
"""


# Severities that are allowed at runtime. ``passed`` is the normal good
# verdict; ``warning`` lets a skill with non-critical findings still run
# (the writer flow already surfaced the warning to the owner). Other
# states — ``not_scanned``, ``scanning``, ``failed``, ``blocked`` —
# are runtime-fatal. ``scanning`` is the P2 async-scan intermediate
# state; runtime treats it the same as ``not_scanned`` so an in-flight
# rescan never accidentally loads stale content.
_RUNTIME_ALLOWED_SECURITY_STATUSES = frozenset({"passed", "warning"})


def is_skill_usable(skill: JoySafeterSkill) -> tuple[bool, Optional[str]]:
    """Return whether a skill row may be packed into a running session.

    :param skill: A ``Skill`` row already loaded with its ``files``
        relationship (the drift check needs the file contents to recompute
        ``target_hash``).
    :returns: ``(True, None)`` when every gate passes, otherwise
        ``(False, reason)`` where ``reason`` is a stable machine code the
        loader can log or surface to the caller. Codes:

        - ``"skill_not_approved"`` — ``lifecycle_status`` not ``approved``
        - ``"security_<status>"`` — ``security_status`` not in the runtime
          allowlist (e.g. ``security_blocked``, ``security_failed``,
          ``security_not_scanned``)
        - ``"content_changed_after_scan"`` — drift detected; the skill's
          current content hashes to something other than the last scan's
          ``target_hash``
        - ``"no_security_scan_hash"`` — the skill row carries no
          ``security_scan_hash``; treated as drift because we cannot
          confirm the current content was ever scanned
    """
    if skill.lifecycle_status != "approved":
        return False, "skill_not_approved"

    if skill.security_status not in _RUNTIME_ALLOWED_SECURITY_STATUSES:
        return False, f"security_{skill.security_status}"

    if not skill.security_scan_hash:
        return False, "no_security_scan_hash"

        # Drift gate: recompute the canonical hash from the skill's current
        # content and compare to whatever the last scan locked in. ``build_scan_files``
        # and ``target_hash`` are the canonical implementations used by
        # ``scan_for_write`` — calling them here keeps the two paths byte-identical.
    files_payload = _files_payload(skill)
    scan_files = build_scan_files(
        name=skill.name,
        description=skill.description,
        content=skill.content,
        tags=list(skill.tags or []),
        license=skill.license,
        files=files_payload,
    )
    current_hash = target_hash(
        name=skill.name,
        description=skill.description,
        content=skill.content,
        tags=list(skill.tags or []),
        license=skill.license,
        files=scan_files,
    )
    if current_hash != skill.security_scan_hash:
        return False, "content_changed_after_scan"

    return True, None


def _files_payload(skill: JoySafeterSkill) -> list[dict]:
    """Project the loaded ``skill.files`` relationship into the dict shape
    :func:`build_scan_files` expects. Mirrors
    ``SkillSecurityService.files_from_skill`` so a skill that was just
    scanned and a skill being re-hashed at load time get the same input.
    """
    result: list[dict] = []
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


# ============================================================================
# skill_packer.py
# ============================================================================

"""
SkillPacker — resolves skill references to tar.gz archives at session start time.

Supports two formats:
1. SkillRef (new): {"type": "custom", "skill_id": "uuid", "version": "latest"}
2. PackedItem (legacy): {"name": "xxx", "tar_gz_b64": "base64..."}
"""

import base64
import io
import os
import tarfile

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.joysafeter_shared.orchestrator_bridge.types import SkillArchive


class SkillPacker:
    def __init__(
        self,
        db: AsyncSession,
        project_id: Optional[str] = None,
        *,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        """Pack skill bundles into sandbox-loadable tar.gz archives.

        The four optional context ids (``project_id``, ``session_id``,
        ``agent_id``, ``user_id``) are recorded in ``SkillUsageLog``
        whenever a pack succeeds. They are kept optional so callers
        with partial context (e.g. cron rescan jobs that pack without a
        live session) still work — the log row carries NULL for any id
        the caller couldn't supply.
        """
        self.db = db
        self._project_id = project_id
        self._session_id = session_id
        self._agent_id = agent_id
        self._user_id = user_id

    async def resolve_and_pack(self, skill_items: list[dict], target: str = "skills") -> list[SkillArchive]:
        """Resolve a list of skill entries (refs or packed) into SkillArchive objects."""
        archives: list[SkillArchive] = []

        for item in skill_items:
            archive = await self._resolve_item(item, target)
            if archive:
                archives.append(archive)

        return archives

    async def _resolve_item(self, item: dict, target: str) -> Optional[SkillArchive]:
        """Resolve a single skill item to a SkillArchive."""
        # Legacy format: pre-packed tar.gz
        if item.get("tar_gz_b64"):
            try:
                data = base64.b64decode(item["tar_gz_b64"])
                return SkillArchive(
                    name=item.get("name", "unknown"),
                    data=data,
                    target=target,
                )
            except Exception as e:
                log_boundary_failure_loguru(
                    logger,
                    boundary="skill_security",
                    code="SKILL_PACKED_ARCHIVE_DECODE_FAILED",
                    message="Failed to decode packed skill archive",
                    operation="decode_packed_skill",
                    error=e,
                    data={"skill_name": str(item.get("name") or "unknown")},
                    retryable=False,
                    user_action="correct_request",
                )
                return None

                # New format: skill reference
        if item.get("skill_id"):
            return await self._pack_custom(
                skill_id=item["skill_id"],
                version=item.get("version", "latest"),
                target=target,
            )

        logger.warning("Skill item has neither tar_gz_b64 nor skill_id: %s", item)
        return None

    async def _pack_custom(self, skill_id: str, version: str, target: str) -> Optional[SkillArchive]:
        """Resolve a custom skill by ID, fetch files from DB, and pack into tar.gz.

        Version keyword semantics (aligned with npm/Cargo/MCP conventions):

        - ``"latest"`` (or unset) → the highest published ``SkillVersion``;
          falls back to draft only when the skill has never been published.
        - ``"draft"`` → the current mutable working copy (``skill_files``).
        - explicit ``"x.y.z"`` → that exact published version.
        """
        sid = skill_id.removeprefix("skill_")
        try:
            uid = uuid.UUID(sid)
        except ValueError:
            logger.warning("Invalid skill_id format: %s", skill_id)
            return None

            # Explicit draft request always uses the working copy.
        if version == "draft":
            return await self._pack_draft(uid, target)

            # Explicit semver — must hit a published version.
        if version and version != "latest":
            return await self._pack_version(uid, version, target)

            # "latest" (or empty): prefer the highest published version; fall back to
            # draft when nothing has been published yet, so brand-new skills still work.
        from app.joysafeter_domain.repositories.joysafeter_skill_version import SkillVersionRepository

        repo = SkillVersionRepository(self.db)
        highest = await repo.get_highest_version_str(uid)
        if highest:
            return await self._pack_version(uid, highest, target)
        return await self._pack_draft(uid, target)

    async def _pack_draft(self, skill_id: uuid.UUID, target: str) -> Optional[SkillArchive]:
        """Pack the mutable working copy (``Skill`` + ``SkillFile``)."""
        from sqlalchemy import and_
        from sqlalchemy import select as sa_select

        conditions = [JoySafeterSkill.id == skill_id]
        if self._project_id:
            conditions.append(JoySafeterSkill.project_id == self._project_id)
        result = await self.db.execute(
            sa_select(JoySafeterSkill).where(and_(*conditions)).options(selectinload(JoySafeterSkill.files))
        )
        skill = result.scalar_one_or_none()
        if not skill:
            logger.warning("Skill not found: %s", skill_id)
            return None

            # Runtime gate: lifecycle + security verdict + content-drift check.
            # A disapproved / unscanned / drifted skill is dropped from the
            # session bundle silently — the rest of the agent still runs. The
            # owner sees the reason via the skill's stored status fields.

        usable, reason = is_skill_usable(skill)
        if not usable:
            logger.warning(
                "Skill %s (%s) refused by runtime gate: %s",
                skill.name,
                skill_id,
                reason,
            )
            return None

        if not skill.files:
            logger.warning("Skill %s has no files", skill.name)
            return None

        tar_data = self._create_targz(skill.files, root_dir=skill.name)
        await self._record_usage(skill_id=skill.id, skill_version="draft")
        return SkillArchive(name=skill.name, data=tar_data, target=target)

    async def _pack_version(self, skill_id: uuid.UUID, version: str, target: str) -> Optional[SkillArchive]:
        """Pack a specific published version of a skill."""

        # Verify skill belongs to project before fetching version, and apply
        # the runtime gate on the parent skill row. Published versions are
        # only as trustworthy as the skill they belong to — a disapproved
        # parent skill drops every version with it. (Version-level
        # lifecycle/security verdicts are P2 work.)
        from sqlalchemy import select as sa_select

        from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkillVersion

        owner_query = sa_select(JoySafeterSkill).where(JoySafeterSkill.id == skill_id)
        if self._project_id:
            owner_query = owner_query.where(JoySafeterSkill.project_id == self._project_id)
        owner_check = await self.db.execute(owner_query.options(selectinload(JoySafeterSkill.files)))
        parent_skill = owner_check.scalar_one_or_none()
        if not parent_skill:
            if self._project_id:
                logger.warning("Skill %s not found in project %s", skill_id, self._project_id)
            else:
                logger.warning("Skill %s not found", skill_id)
            return None

        usable, reason = is_skill_usable(parent_skill)
        if not usable:
            logger.warning(
                "Skill %s (%s) version %s refused by runtime gate: %s",
                parent_skill.name,
                skill_id,
                version,
                reason,
            )
            return None

        result = await self.db.execute(
            select(JoySafeterSkillVersion)
            .where(JoySafeterSkillVersion.skill_id == skill_id, JoySafeterSkillVersion.version == version)
            .options(selectinload(JoySafeterSkillVersion.files))
        )
        sv = result.scalar_one_or_none()
        if not sv:
            logger.warning("Skill version not found: skill=%s version=%s", skill_id, version)
            return None

        if not sv.files:
            logger.warning("Skill version %s/%s has no files", skill_id, version)
            return None

        tar_data = self._create_targz(sv.files, root_dir=parent_skill.name)
        await self._record_usage(skill_id=skill_id, skill_version=version)
        return SkillArchive(name=parent_skill.name, data=tar_data, target=target)

    async def _record_usage(
        self,
        *,
        skill_id: uuid.UUID,
        skill_version: Optional[str],
    ) -> None:
        """Append a row to ``joysafeter_skill_usage_log``.

        Fire-and-forget: a failure to record the log MUST NOT break the
        pack — the agent is loading a skill it has every right to load,
        and we'd rather miss an audit row than refuse to run. The DB
        error is logged at warning level so an outage stays visible.
        ``flush`` (not ``commit``) keeps the caller's transaction
        semantics intact — the orchestrator commits the whole bundle
        in one shot upstream.
        """
        from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkillUsageLog

        try:
            self.db.add(
                JoySafeterSkillUsageLog(
                    skill_id=skill_id,
                    skill_version=skill_version,
                    session_id=self._session_id,
                    agent_id=self._agent_id,
                    project_id=self._project_id,
                    user_id=self._user_id,
                )
            )
            await self.db.flush()
        except Exception as exc:  # noqa: BLE001 — never fail a pack on logging
            log_boundary_failure_loguru(
                logger,
                boundary="skill_security",
                code="SKILL_USAGE_LOG_WRITE_FAILED",
                message="Failed to write skill usage log",
                operation="write_skill_usage_log",
                error=exc,
                data={
                    "skill_id": str(skill_id),
                    "skill_version": str(skill_version) if skill_version is not None else None,
                    "session_id": str(self._session_id) if self._session_id is not None else None,
                    "agent_id": str(self._agent_id) if self._agent_id is not None else None,
                    "project_id": str(self._project_id) if self._project_id is not None else None,
                    "user_id": self._user_id,
                },
            )

    def _create_targz(self, files, root_dir: Optional[str] = None) -> bytes:
        """Pack a list of SkillFile/SkillVersionFile objects into a tar.gz archive."""
        safe_root = self._safe_archive_component(root_dir) if root_dir else None
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for f in files:
                safe_path = self._safe_archive_path(f)
                if not safe_path:
                    continue
                if safe_root:
                    safe_path = f"{safe_root}/{safe_path}"
                content = (f.content or "").encode("utf-8")
                info = tarfile.TarInfo(name=safe_path)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
        return buf.getvalue()

    def _safe_archive_component(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        component = os.path.basename(value.replace("\\", "/").strip())
        component = os.path.normpath(component).replace("\\", "/").strip("/")
        if not component or component == "." or component == ".." or "/" in component:
            logger.warning("Skill packer: unsafe archive root skipped: %s", value)
            return None
        return component

    def _safe_archive_path(self, file_obj) -> Optional[str]:
        """Return a normalized relative path for a skill file inside the archive."""
        raw_path = (getattr(file_obj, "path", None) or "").replace("\\", "/")
        file_name = (getattr(file_obj, "file_name", None) or "").replace("\\", "/")

        # Historical imports stored `path` inconsistently: some rows keep the
        # complete relative file path in `path`, while newer ZIP imports store
        # the directory in `path` and the basename in `file_name`.  Build the
        # archive path defensively so Claude always receives
        # .claude/skills/<skill>/<relative-file>.
        if raw_path in ("", "."):
            candidate = file_name
        elif raw_path.endswith("/"):
            candidate = f"{raw_path}{file_name}"
        elif file_name and os.path.basename(raw_path) != file_name:
            candidate = f"{raw_path}/{file_name}"
        else:
            candidate = raw_path

        safe_path = os.path.normpath(candidate).replace("\\", "/").lstrip("/")
        if not safe_path or safe_path == "." or safe_path.endswith("/"):
            logger.warning("Skill packer: empty archive path skipped: path=%s file_name=%s", raw_path, file_name)
            return None
        if ".." in safe_path.split("/"):
            logger.warning("Skill packer: path traversal blocked: %s", candidate)
            return None
        return safe_path


# ============================================================================
# skill_async_scan.py
# ============================================================================

"""Background skill security scans.

P2 introduces async scan dispatch for skills whose content is too big
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

The runtime gate (``skill_runtime_policy.is_skill_usable``) treats
``scanning`` like ``not_scanned`` — no agent loads a skill while its
scan is in flight.
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
    skill_id: uuid.UUID,
    trigger: str,
    created_by_id: str,
    owner_id: Optional[str],
    project_id: Optional[str],
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

    Failure handling: scanner failures normally return a ``failed`` scan via
    ``scan_for_write(..., failure_mode='fail_open')``. If the background task
    itself fails outside that scanner path, record a synthetic ``failed`` scan
    with a structured error payload and apply it to the skill row. This avoids
    leaving the runtime gate stuck on the transient ``scanning`` state.

    The function lives in this module (not inside the service) because
    it needs to open a fresh DB session — the request's session has
    long since been closed by the time the BG task runs.
    """
    # Lazy imports keep the orchestrator import graph clean: this
    # module is loaded by the FastAPI request path, but the BG task
    # only needs the session factory and the service when invoked.
    from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill
    from app.joysafeter_shared.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            svc = SkillSecurityService(db)
            scan = await svc.scan_for_write(
                enforce_write_policy=False,  # async path never aborts a write
                failure_mode="fail_open",
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
                # ``scanning`` placeholder so the runtime gate stops
                # treating the row as in-flight.
                skill = await db.get(JoySafeterSkill, skill_id)
                if skill and skill.security_status == "scanning":
                    skill.security_status = "not_scanned"
                    await db.commit()
                return
                # Refresh the skill row with the latest verdict.
            skill = await db.get(JoySafeterSkill, skill_id)
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
                    "project_id": project_id,
                    "owner_id": owner_id,
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
                    skill_id=skill_id,
                    project_id=project_id,
                    owner_id=owner_id,
                    created_by_id=created_by_id,
                    trigger=trigger,
                    target_name=name,
                    target_hash=target_hash,
                    scanner="skillspector",
                    scanner_version=None,
                    status="failed",
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
                skill = await db.get(JoySafeterSkill, skill_id)
                if skill and skill.security_status == "scanning":
                    svc.apply_latest_scan(skill, failed_scan)
                await db.commit()
            except Exception:
                logger.exception(
                    "Failed to record background skill security scan failure for skill_id=%s",
                    skill_id,
                    extra={"error": error_payload},
                )
