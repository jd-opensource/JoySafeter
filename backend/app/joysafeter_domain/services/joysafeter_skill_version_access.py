from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import semver

from app.joysafeter_shared.ids import OrganizationId, ProjectId


@dataclass(frozen=True)
class SkillVersionExposure:
    skill_project_id: ProjectId
    skill_org_id: Optional[OrganizationId]
    consumer_project_id: Optional[ProjectId]
    consumer_org_id: Optional[OrganizationId]
    org_version: Optional[str] = None
    public_version: Optional[str] = None

    @property
    def same_project(self) -> bool:
        return self.consumer_project_id is not None and self.consumer_project_id == self.skill_project_id

    @property
    def same_org(self) -> bool:
        return (
            self.consumer_org_id is not None
            and self.skill_org_id is not None
            and self.consumer_org_id == self.skill_org_id
        )

    def exposed_versions(self) -> tuple[str, ...]:
        if self.same_project:
            return ()
        candidates = [self.public_version]
        if self.same_org:
            candidates.append(self.org_version)
        return tuple(dict.fromkeys(version for version in candidates if version))

    def resolve_latest(self, project_latest: Optional[str] = None) -> Optional[str]:
        if self.same_project:
            return project_latest
        candidates = self.exposed_versions()
        if not candidates:
            return None
        return max(candidates, key=semver.Version.parse)

    def allows(self, version: str) -> bool:
        return self.same_project or version in self.exposed_versions()
