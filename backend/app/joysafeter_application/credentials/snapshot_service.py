from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from app.joysafeter_domain.credentials.dependencies import (
    CredentialDependency,
    ReferenceScannerId,
    ReferenceSurfaceDescriptor,
)
from app.joysafeter_domain.credentials.types import CredentialId, ProjectId

from .ports import ReferenceScanner


@dataclass(frozen=True, slots=True)
class NoPersistentDependencyScanner:
    scanner_id: ReferenceScannerId
    reason: str = "ephemeral_consumer"

    async def scan_resource(
        self,
        project_id: ProjectId,
        credential_id: CredentialId,
    ) -> tuple[CredentialDependency, ...]:
        return ()


class CredentialSnapshotService:
    """Task 5 composition seam; Task 11 owns snapshot locking/linearization."""

    def __init__(
        self,
        descriptors: Iterable[ReferenceSurfaceDescriptor] = (),
        scanners: Iterable[ReferenceScanner] = (),
    ) -> None:
        self.descriptors = tuple(descriptors)
        scanner_list = tuple(scanners)
        self._scanner_id_counts = Counter(scanner.scanner_id for scanner in scanner_list)
        self.scanners = {scanner.scanner_id: scanner for scanner in scanner_list}

    def validate_scanner_registration(self) -> None:
        duplicate_scanners = sorted(
            str(scanner_id) for scanner_id, count in self._scanner_id_counts.items() if count > 1
        )
        descriptor_scanner_counts = Counter(
            descriptor.scanner_id for descriptor in self.descriptors if descriptor.scanner_id is not None
        )
        duplicate_descriptors = sorted(
            str(scanner_id) for scanner_id, count in descriptor_scanner_counts.items() if count > 1
        )
        descriptors_without_scanners = sorted(
            str(descriptor.surface_id) for descriptor in self.descriptors if descriptor.scanner_id is None
        )
        required = set(descriptor_scanner_counts)
        extra = set(self.scanners) - required
        missing = required - set(self.scanners)
        wrong_scanner_kinds = sorted(
            str(descriptor.scanner_id)
            for descriptor in self.descriptors
            if descriptor.scanner_id in self.scanners
            and (
                descriptor.persistent == isinstance(self.scanners[descriptor.scanner_id], NoPersistentDependencyScanner)
            )
        )
        if (
            duplicate_scanners
            or duplicate_descriptors
            or descriptors_without_scanners
            or missing
            or extra
            or wrong_scanner_kinds
        ):
            raise ValueError(
                "credential scanner registry mismatch: "
                f"duplicate_scanners={duplicate_scanners}, "
                f"duplicate_descriptors={duplicate_descriptors}, "
                f"descriptors_without_scanners={descriptors_without_scanners}, "
                f"missing={sorted(map(str, missing))}, "
                f"extra={sorted(map(str, extra))}, "
                f"wrong_scanner_kinds={wrong_scanner_kinds}"
            )

    def scanner(self, scanner_id: ReferenceScannerId) -> ReferenceScanner:
        return self.scanners[scanner_id]
