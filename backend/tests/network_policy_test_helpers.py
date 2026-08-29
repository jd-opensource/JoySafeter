from __future__ import annotations

from typing import Protocol

DEFAULT_TEST_NETWORK_POLICY_HASH = "test-network-policy"
DEFAULT_TEST_NETWORK_POLICY_VERSION = 1


class MutableNetworkPolicyState(Protocol):
    networking_status: str
    networking_policy_hash: str | None
    networking_policy_version: int
    networking_applied_hash: str | None
    networking_applied_version: int | None


def acknowledged_network_policy_fields(
    *,
    policy_hash: str = DEFAULT_TEST_NETWORK_POLICY_HASH,
    policy_version: int = DEFAULT_TEST_NETWORK_POLICY_VERSION,
) -> dict[str, str | int]:
    if not policy_hash:
        raise ValueError("acknowledged network policy hash must not be empty")
    if policy_version <= 0:
        raise ValueError("acknowledged network policy version must be positive")
    return {
        "networking_status": "ready",
        "networking_policy_hash": policy_hash,
        "networking_policy_version": policy_version,
        "networking_applied_hash": policy_hash,
        "networking_applied_version": policy_version,
    }


def mark_network_policy_ready(
    sandbox: MutableNetworkPolicyState,
    *,
    policy_hash: str = DEFAULT_TEST_NETWORK_POLICY_HASH,
    policy_version: int = DEFAULT_TEST_NETWORK_POLICY_VERSION,
) -> None:
    fields = acknowledged_network_policy_fields(
        policy_hash=policy_hash,
        policy_version=policy_version,
    )
    for field, value in fields.items():
        setattr(sandbox, field, value)
