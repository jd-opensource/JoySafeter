from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .policies import CredentialGroupRestoreContext, validate_group_restore
from .resource import CredentialGroupResource, CredentialResource, McpCredentialIdentity, ServiceCredentialIdentity
from .types import CredentialAuthScheme, CredentialState


class CredentialLifecycleCommand(StrEnum):
    ARCHIVE = "archive"
    RESTORE = "restore"
    DELETE = "delete"


class CredentialLifecycleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CredentialLifecycleDecision:
    state: CredentialState
    is_default: bool


@dataclass(frozen=True, slots=True)
class CredentialGroupLifecycleDecision:
    state: CredentialState


def decide_credential_lifecycle(
    resource: CredentialResource,
    command: CredentialLifecycleCommand,
) -> CredentialLifecycleDecision:
    target_state = _target_state(resource.state, command)
    if (
        command is CredentialLifecycleCommand.RESTORE
        and _auth_scheme(resource) is CredentialAuthScheme.OAUTH2_LEGACY_DISABLED
    ):
        raise CredentialLifecycleError("OAUTH2_LEGACY_DISABLED credentials cannot be restored")
    return CredentialLifecycleDecision(
        state=target_state,
        is_default=(
            resource.is_default
            if resource.state is CredentialState.ACTIVE and target_state is CredentialState.ACTIVE
            else False
        ),
    )


def decide_group_lifecycle(
    resource: CredentialGroupResource,
    command: CredentialLifecycleCommand,
    *,
    restore_context: CredentialGroupRestoreContext | None = None,
) -> CredentialGroupLifecycleDecision:
    target_state = _target_state(resource.state, command)
    if command is CredentialLifecycleCommand.RESTORE:
        if restore_context is None:
            raise CredentialLifecycleError("credential group restore context is required")
        validate_group_restore(resource, restore_context)
    return CredentialGroupLifecycleDecision(state=target_state)


def _target_state(state: CredentialState, command: CredentialLifecycleCommand) -> CredentialState:
    if command is CredentialLifecycleCommand.ARCHIVE:
        if state is CredentialState.ARCHIVED:
            return state
        if state is not CredentialState.ACTIVE:
            raise CredentialLifecycleError("deleted resources cannot be archived")
        return CredentialState.ARCHIVED
    if command is CredentialLifecycleCommand.RESTORE:
        if state is CredentialState.ACTIVE:
            return state
        if state is not CredentialState.ARCHIVED:
            raise CredentialLifecycleError("deleted resources cannot be restored")
        return CredentialState.ACTIVE
    if command is CredentialLifecycleCommand.DELETE:
        return CredentialState.DELETED
    raise CredentialLifecycleError(f"unsupported lifecycle command: {command}")


def _auth_scheme(resource: CredentialResource) -> CredentialAuthScheme | None:
    if isinstance(resource.identity, (ServiceCredentialIdentity, McpCredentialIdentity)):
        return resource.identity.auth_scheme
    return None
