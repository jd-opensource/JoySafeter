"""Skill security scanning service."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.skill import Skill, SkillSecurityScan
from app.joysafeter_domain.repositories.skill import SkillRepository, SkillSecurityScanRepository
from app.joysafeter_shared.common.app_errors import AccessDeniedError, InvalidRequestError, NotFoundError
from app.joysafeter_shared.common.skill_permissions import check_skill_access
from app.joysafeter_shared.config.settings import settings
from app.joysafeter_shared.skill.yaml_parser import is_system_file
from app.joysafeter_shared.utils.datetime import utc_now

from app.joysafeter_domain.models.skill_collaborator import CollaboratorRole


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

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SkillSecurityScanRepository(db)
        self.skill_repo = SkillRepository(db)
        self.client = SkillSecurityScannerClient(
            settings.skill_security_scanner_url,
            settings.skill_security_timeout_seconds,
        )

    async def scan_for_write(
        self,
        *,
        enforce_write_policy: bool = True,
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
    ) -> Optional[SkillSecurityScan]:
        """Scan a candidate skill before it is persisted."""
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
                trigger=trigger,
                created_by_id=created_by_id,
                owner_id=owner_id,
                project_id=project_id,
                skill_id=skill_id,
                target_name=name,
                target_hash=target_hash,
            )
        except Exception as exc:
            logger.exception("Skill security scan failed")
            scan = SkillSecurityScan(
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
            if enforce_write_policy and settings.skill_security_fail_closed:
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

    async def rescan_existing_skill(self, skill_id: uuid.UUID, current_user_id: str) -> SkillSecurityScan:
        """Rescan persisted skill content and update the skill's current security state."""
        skill = await self.skill_repo.get_with_files(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        await check_skill_access(self.db, skill, current_user_id, CollaboratorRole.editor)

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
            scan = SkillSecurityScan(
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
    ) -> tuple[list[SkillSecurityScan], bool]:
        skill = await self.skill_repo.get(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        await check_skill_access(self.db, skill, current_user_id, CollaboratorRole.viewer)
        return await self.repo.list_by_skill(skill_id, limit=limit, after_id=after_id)

    async def get_latest_scan(self, skill_id: uuid.UUID, current_user_id: str) -> SkillSecurityScan:
        skill = await self.skill_repo.get(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        await check_skill_access(self.db, skill, current_user_id, CollaboratorRole.viewer)
        scan = await self.repo.get_latest_by_skill(skill_id)
        if not scan:
            raise NotFoundError(
                "Skill security scan not found",
                code="SKILL_SECURITY_SCAN_NOT_FOUND",
                data={"skill_id": str(skill_id)},
            )
        return scan

    async def get_scan(self, scan_id: uuid.UUID, current_user_id: str) -> SkillSecurityScan:
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
            await check_skill_access(self.db, skill, current_user_id, CollaboratorRole.viewer)
        elif scan.created_by_id != current_user_id and scan.owner_id != current_user_id:
            raise AccessDeniedError(
                "You don't have permission to access this scan",
                code="SKILL_SECURITY_SCAN_ACCESS_DENIED",
            )
        return scan

    def apply_latest_scan(self, skill: Skill, scan: SkillSecurityScan) -> None:
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

    def files_from_skill(self, skill: Skill) -> list[dict[str, Any]]:
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
        scan_files: list[SkillScanFile] = []
        for file_data in files or []:
            path = self._scan_path(file_data)
            file_name = str(file_data.get("file_name") or path.rsplit("/", 1)[-1] or "").strip()
            if (
                not path
                or self._is_skill_md(path, file_name)
                or is_system_file(path)
                or is_system_file(file_name)
                or self._is_generated_file(path, file_name)
                or self._is_non_security_context_file(path, file_name)
            ):
                continue
            scan_files.append(
                SkillScanFile(
                    path=path,
                    file_name=file_name,
                    file_type=str(file_data.get("file_type") or "text"),
                    content=self._coerce_content(file_data.get("content")),
                )
            )

        scan_files.insert(
            0,
            SkillScanFile(
                path="SKILL.md",
                file_name="SKILL.md",
                file_type="markdown",
                content=self._generated_skill_md(name, description, content, tags, license),
            ),
        )
        return sorted(scan_files, key=lambda item: item.path)

    def _generated_skill_md(
        self,
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

    def _scan_path(self, file_data: dict[str, Any]) -> str:
        raw_path = str(file_data.get("path") or "").replace("\\", "/").strip()
        file_name = str(file_data.get("file_name") or "").replace("\\", "/").strip()
        if not raw_path:
            return file_name
        if raw_path.endswith("/") and file_name:
            return f"{raw_path}{file_name}"
        if file_name and raw_path.rsplit("/", 1)[-1] != file_name:
            return f"{raw_path.rstrip('/')}/{file_name}"
        return raw_path

    def _is_skill_md(self, path: str, file_name: str) -> bool:
        return path.strip("/").lower() == "skill.md" or file_name.lower() == "skill.md"

    def _is_generated_file(self, path: str, file_name: str) -> bool:
        normalized_path = path.replace("\\", "/").lower()
        normalized_name = file_name.lower()
        parts = [part for part in normalized_path.split("/") if part]
        return (
            "__pycache__" in parts
            or normalized_name.endswith((".pyc", ".pyo"))
            or normalized_name in {".coverage", "coverage.xml"}
        )

    def _is_non_security_context_file(self, path: str, file_name: str) -> bool:
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

    def _scan_from_report(
        self,
        *,
        report: dict[str, Any],
        scanner_version: Optional[str],
        trigger: str,
        created_by_id: str,
        owner_id: Optional[str],
        project_id: Optional[str],
        skill_id: Optional[uuid.UUID],
        target_name: str,
        target_hash: str,
    ) -> SkillSecurityScan:
        risk = report.get("risk_assessment") if isinstance(report.get("risk_assessment"), dict) else {}
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
        return SkillSecurityScan(
            skill_id=skill_id,
            project_id=project_id,
            owner_id=owner_id,
            created_by_id=created_by_id,
            trigger=trigger,
            target_name=target_name,
            target_hash=target_hash,
            scanner="skillspector",
            scanner_version=scanner_version,
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

    def _is_blocked(self, scan: SkillSecurityScan) -> bool:
        return scan.status == "blocked" or (scan.status == "failed" and settings.skill_security_fail_closed)

    def _error_data(self, scan: SkillSecurityScan) -> dict[str, Any]:
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

    def _coerce_content(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)

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
