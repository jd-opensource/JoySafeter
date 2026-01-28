"""
Data models for whitebox scanning feature
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID


class ScanStatus(str, Enum):
    """Status of a scan job."""

    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AgentVerificationStatus(str, Enum):
    """Status of agent verification for a finding."""

    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    UNCERTAIN = "UNCERTAIN"
    NOT_REQUIRED = "NOT_REQUIRED"


@dataclass
class ScanJobResponse:
    """Response when starting a scan job."""

    job_id: UUID
    status: ScanStatus
    message: str


@dataclass
class ScanJobStatus:
    """Status response for a scan job."""

    job_id: UUID
    status: ScanStatus
    progress: int
    error: Optional[str] = None
    result: Optional["ScanReport"] = None


@dataclass
class ScanReport:
    """Complete scan report with findings."""

    summary: Dict[str, int]
    findings: List["Finding"]
    scanned_files: int
    scan_duration_ms: int


@dataclass
class Finding:
    """A detected vulnerability finding."""

    id: str
    rule_id: str
    type: str
    severity: str
    file_path: str
    line_number: int
    code_snippet: str
    agent_verification: str = AgentVerificationStatus.PENDING.value
    agent_comment: Optional[str] = None
