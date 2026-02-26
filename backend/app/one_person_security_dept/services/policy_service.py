"""Policy definitions for Security Dept execution."""

from __future__ import annotations

from dataclasses import dataclass

from app.common.exceptions import BadRequestException


@dataclass(frozen=True)
class SecurityDeptProfile:
    name: str
    description: str
    permission_mode: str
    scenario: str


PENTEST_FULL_ACCESS_V1 = SecurityDeptProfile(
    name="pentest_full_access_v1",
    description="Pentest profile with broad tool permissions for controlled lab execution.",
    permission_mode="bypassPermissions",
    scenario="pentest",
)

AVAILABLE_PROFILES = {
    PENTEST_FULL_ACCESS_V1.name: PENTEST_FULL_ACCESS_V1,
}


class SecurityDeptPolicyService:
    """Policy helper for validating scenario/profile combinations."""

    @staticmethod
    def validate_scenario(scenario: str) -> None:
        if scenario != "pentest":
            raise BadRequestException(f"Unsupported scenario: {scenario}")

    @staticmethod
    def get_profile(name: str) -> SecurityDeptProfile:
        profile = AVAILABLE_PROFILES.get(name)
        if profile is None:
            raise BadRequestException(f"Unknown profile: {name}")
        return profile

    @staticmethod
    def list_profiles() -> list[SecurityDeptProfile]:
        return list(AVAILABLE_PROFILES.values())
