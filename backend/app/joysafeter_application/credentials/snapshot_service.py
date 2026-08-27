from __future__ import annotations

import copy
import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from app.joysafeter_domain.credentials.bindings import (
    EgressInjectKind,
    EgressInjectPolicy,
    EnvironmentInjectionBinding,
    HttpEgressBinding,
    McpCredentialRequirement,
    McpEndpointRequirement,
    McpGroupBinding,
)
from app.joysafeter_domain.credentials.dependencies import (
    CredentialDependency,
    ReferenceScannerId,
    ReferenceSurfaceDescriptor,
    ReferenceTarget,
)
from app.joysafeter_domain.credentials.policies import (
    CredentialPolicyError,
    CredentialPolicyErrorCode,
    validate_mcp_group_binding,
)
from app.joysafeter_domain.credentials.references import CredentialReferenceCodec, DecodedSnapshot
from app.joysafeter_domain.credentials.types import (
    CredentialFieldName,
    CredentialGroupId,
    CredentialId,
    NormalizedEndpoint,
    NormalizedMcpUrl,
    ProjectId,
)
from app.joysafeter_domain.llm.catalog import get_llm_catalog
from app.joysafeter_domain.llm.model_inference_policy import build_model_inference_policy
from app.joysafeter_domain.services.credential_binding_errors import raise_public_credential_error
from app.joysafeter_shared.common.app_errors import NotFoundError, ResourceConflictError
from app.joysafeter_shared.ids import AgentId, EnvironmentId, SecurityAuditId, SessionId
from app.joysafeter_shared.utils.datetime import platform_now

from .binding_service import BindingIssuanceAuthority, CredentialBindingService
from .ports import (
    CredentialAuditEntry,
    CredentialSnapshotSession,
    CredentialUnitOfWork,
    ReferenceScanner,
)

logger = logging.getLogger(__name__)
_MAX_SOURCE_ATTEMPTS = 3
_REFERENCE_CODEC = CredentialReferenceCodec()
_ENVIRONMENT_CONFIG_OVERLAY_KEYS = frozenset({"type", "packages", "networking", "env_vars"})


@dataclass(frozen=True, slots=True)
class CreateCredentialAwareSession:
    project_id: ProjectId | None
    agent_id: AgentId
    pinned_agent_version: int | None = None
    environment_id: EnvironmentId | None = None
    credential_group_ids: tuple[CredentialGroupId, ...] = ()
    title: str | None = None
    metadata: Mapping[str, object] | None = None
    caller: str = "session_api"
    environment_config_overlay: Mapping[str, object] | None = None
    environment_mount_resources: tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        if self.project_id is not None and type(self.project_id) is not ProjectId:
            raise TypeError("project_id must be ProjectId")
        if self.agent_id is None:
            raise ValueError("snapshot session agent_id is required")
        if self.pinned_agent_version is not None and self.pinned_agent_version < 1:
            raise ValueError("pinned agent version must be positive")
        group_ids = tuple(dict.fromkeys(self.credential_group_ids))
        object.__setattr__(self, "credential_group_ids", group_ids)
        overlay = copy.deepcopy(dict(self.environment_config_overlay or {}))
        unsupported_overlay_keys = sorted(set(overlay) - _ENVIRONMENT_CONFIG_OVERLAY_KEYS)
        if unsupported_overlay_keys:
            raise ValueError(
                "environment_config_overlay contains unsupported keys: " + ", ".join(unsupported_overlay_keys)
            )
        object.__setattr__(self, "metadata", copy.deepcopy(dict(self.metadata or {})))
        object.__setattr__(self, "environment_config_overlay", overlay)
        object.__setattr__(
            self,
            "environment_mount_resources",
            tuple(copy.deepcopy(dict(resource)) for resource in self.environment_mount_resources),
        )


def _session_title(requested: str | None, agent_name: str) -> str:
    title = (requested or "").strip()
    if title:
        return title
    display_name = agent_name.strip() or "Session"
    return f"{display_name} · {platform_now().strftime('%m-%d %H:%M')}"


def _decoded_snapshot(snapshot: Mapping[str, object]) -> DecodedSnapshot:
    try:
        return _REFERENCE_CODEC.decode_snapshot(snapshot)
    except Exception as exc:
        raise_public_credential_error(exc)
        raise AssertionError("unreachable")


def _mcp_endpoint_requirements(snapshot: Mapping[str, object]) -> tuple[McpEndpointRequirement, ...]:
    try:
        requirements: list[McpEndpointRequirement] = []
        for item in snapshot.get("mcp_servers") or []:
            if not isinstance(item, Mapping) or item.get("type") == "local_stdio":
                continue
            requirements.append(
                McpEndpointRequirement(
                    server_url=NormalizedMcpUrl(item["url"]),
                    auth_requirement=McpCredentialRequirement(item["auth_requirement"]),
                )
            )
        return tuple(requirements)
    except (TypeError, ValueError) as exc:
        raise_public_credential_error(exc, constructor_error="url_conflict")
        raise AssertionError("unreachable")


def _lock_set_fingerprint(
    command: CreateCredentialAwareSession,
    source,
    decoded: DecodedSnapshot,
) -> tuple[object, ...]:
    return (
        str(source.agent_id),
        str(source.source_version_id) if source.source_version_id is not None else None,
        str(source.environment_id) if source.environment_id is not None else None,
        tuple(str(credential_id) for credential_id in decoded.credential_ids),
        tuple(sorted(str(group_id) for group_id in command.credential_group_ids)),
    )


async def _validate_resource_references(
    decoded: DecodedSnapshot,
    *,
    project_id: ProjectId,
    binding_service: CredentialBindingService,
) -> None:
    if decoded.model is not None:
        try:
            binding = build_model_inference_policy(
                get_llm_catalog(),
                project_id=project_id,
                credential_id=decoded.model.credential_id,
                engine_kind=decoded.model.engine_kind,
                model_id=decoded.model.model_id,
            )
            await binding_service.validate_model_inference_reference(binding)
        except Exception as exc:
            raise_public_credential_error(exc, credential_id=decoded.model.credential_id)

    for credential_id in decoded.environment_credential_ids:
        try:
            await binding_service.validate_reference(
                EnvironmentInjectionBinding(
                    project_id=project_id,
                    credential_id=credential_id,
                )
            )
        except Exception as exc:
            raise_public_credential_error(exc, credential_id=credential_id)

    for reference in decoded.http_egress:
        try:
            await binding_service.validate_reference(
                HttpEgressBinding(
                    project_id=project_id,
                    credential_id=reference.credential_id,
                    endpoint=NormalizedEndpoint(reference.endpoint),
                    inject=EgressInjectPolicy(
                        kind=EgressInjectKind(reference.inject_kind),
                        credential_field=CredentialFieldName(reference.credential_field),
                        header=reference.header,
                    ),
                )
            )
        except Exception as exc:
            raise_public_credential_error(exc, credential_id=reference.credential_id)


async def _validate_group_references(
    command: CreateCredentialAwareSession,
    snapshot: Mapping[str, object],
    uow: CredentialUnitOfWork,
) -> None:
    endpoint_requirements = _mcp_endpoint_requirements(snapshot)
    if not command.credential_group_ids and not endpoint_requirements:
        return
    if command.project_id is None:
        raise NotFoundError(
            code="SESSION_CREDENTIAL_GROUP_NOT_FOUND",
            message="Credential group not found",
        )
    project_id = command.project_id
    group_ids = command.credential_group_ids
    groups = tuple(await uow.groups.get_many(group_ids, project_id=command.project_id))
    members = tuple(await uow.groups.list_members(group_ids, project_id=command.project_id))
    try:
        validate_mcp_group_binding(
            McpGroupBinding(
                project_id=project_id,
                group_ids=group_ids,
                endpoint_requirements=endpoint_requirements,
            ),
            groups=groups,
            members=members,
        )
    except CredentialPolicyError as exc:
        if exc.code is CredentialPolicyErrorCode.ARCHIVED:
            raise ResourceConflictError(
                code="SESSION_CREDENTIAL_GROUP_ARCHIVED",
                message="Credential group is archived",
            ) from exc
        if exc.code is CredentialPolicyErrorCode.REQUIRED_CREDENTIAL_MISSING:
            raise ResourceConflictError(
                code="SESSION_MCP_CREDENTIAL_REQUIRED",
                message="A required MCP credential was not selected for this Session",
                data=exc.data,
                user_action="fix_input",
            ) from exc
        if exc.code in {
            CredentialPolicyErrorCode.GROUP_MISMATCH,
            CredentialPolicyErrorCode.DELETED,
            CredentialPolicyErrorCode.PROJECT_MISMATCH,
        }:
            raise NotFoundError(
                code="SESSION_CREDENTIAL_GROUP_NOT_FOUND",
                message="Credential group not found",
            ) from exc
        raise_public_credential_error(exc)
    except (TypeError, ValueError) as exc:
        raise_public_credential_error(exc, constructor_error="url_conflict")


async def create_session_from_source(
    command: CreateCredentialAwareSession,
    uow: CredentialUnitOfWork,
):
    binding_service = CredentialBindingService(uow.credentials, BindingIssuanceAuthority())
    for attempt in range(_MAX_SOURCE_ATTEMPTS):
        try:
            prelock_source = await uow.sources.load(command, for_update=False)
            prelock_decoded = _decoded_snapshot(prelock_source.snapshot)
            prelock_fingerprint = _lock_set_fingerprint(command, prelock_source, prelock_decoded)
            if prelock_decoded.credential_ids and command.project_id is None:
                credential_id = prelock_decoded.credential_ids[0]
                raise NotFoundError(
                    code="CREDENTIAL_NOT_FOUND",
                    message="Credential not found",
                    data={"credential_id": str(credential_id)},
                )

            await uow.groups.lock_credential_groups(
                list(command.credential_group_ids),
                project_id=command.project_id,
            )
            locked_source = await uow.sources.load(command, for_update=True)
            decoded = _decoded_snapshot(locked_source.snapshot)
            if _lock_set_fingerprint(command, locked_source, decoded) != prelock_fingerprint:
                await uow.rollback()
                continue

            group_ids = command.credential_group_ids
            members = tuple(await uow.groups.list_members(group_ids, project_id=command.project_id))
            credential_ids = set(decoded.credential_ids)
            credential_ids.update(member.id for member in members)
            await uow.credentials.lock_credentials(
                list(credential_ids),
                project_id=command.project_id,
            )

            if decoded.credential_ids:
                if command.project_id is None:
                    credential_id = decoded.credential_ids[0]
                    raise NotFoundError(
                        code="CREDENTIAL_NOT_FOUND",
                        message="Credential not found",
                        data={"credential_id": str(credential_id)},
                    )
                await _validate_resource_references(
                    decoded,
                    project_id=command.project_id,
                    binding_service=binding_service,
                )
            await _validate_group_references(command, locked_source.snapshot, uow)
            persistent_snapshot = _REFERENCE_CODEC.encode_snapshot(locked_source.snapshot)

            session = await uow.sessions.create(
                CredentialSnapshotSession(
                    id=SessionId.new(),
                    agent_id=locked_source.agent_id,
                    project_id=command.project_id,
                    title=_session_title(command.title, locked_source.agent_name),
                    metadata=command.metadata or {},
                    credential_group_ids=command.credential_group_ids,
                    environment_id=locked_source.environment_id,
                    agent_version=locked_source.agent_version,
                    agent_snapshot=persistent_snapshot,
                )
            )
            await uow.audit.append(
                CredentialAuditEntry(
                    id=SecurityAuditId.new(),
                    action="session.snapshot.created",
                    project_id=command.project_id,
                    target_type="session",
                    target_id=str(session.id),
                    details={
                        "agent_id": str(locked_source.agent_id),
                        "agent_version": locked_source.agent_version,
                        "caller": command.caller,
                    },
                )
            )
            await uow.sessions.refresh(session)
            await uow.commit()
            try:
                await uow.impacts.nudge_after_commit()
            except Exception:
                logger.warning("snapshot credential impact nudge failed after commit", exc_info=True)
            return session
        except Exception:
            await uow.rollback()
            raise

    raise ResourceConflictError(
        code="SESSION_SOURCE_CHANGED",
        message="Session source changed repeatedly during activation",
        retryable=True,
        user_action="retry",
    )


@dataclass(frozen=True, slots=True)
class NoPersistentDependencyScanner:
    scanner_id: ReferenceScannerId
    reason: Literal["ephemeral_consumer"] = "ephemeral_consumer"

    def __post_init__(self) -> None:
        if self.reason != "ephemeral_consumer":
            raise ValueError("NoPersistentDependencyScanner reason must be ephemeral_consumer")

    async def scan_resource(
        self,
        project_id: ProjectId,
        credential_id: CredentialId,
    ) -> tuple[CredentialDependency, ...]:
        return ()

    async def scan_group(
        self,
        project_id: ProjectId,
        group_id: CredentialGroupId,
    ) -> tuple[CredentialDependency, ...]:
        return ()


class CredentialSnapshotService:
    """Compose session creation with credential snapshot locking."""

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

    async def scan_resource(
        self,
        project_id: ProjectId,
        credential_id: CredentialId,
    ) -> tuple[CredentialDependency, ...]:
        dependencies = []
        for descriptor in self.descriptors:
            if descriptor.target is not ReferenceTarget.RESOURCE:
                continue
            dependencies.extend(await self.scanner(descriptor.scanner_id).scan_resource(project_id, credential_id))
        return tuple(sorted(set(dependencies), key=lambda item: (str(item.surface_id), item.source_id)))

    async def scan_group(
        self,
        project_id: ProjectId,
        group_id: CredentialGroupId,
    ) -> tuple[CredentialDependency, ...]:
        dependencies = []
        for descriptor in self.descriptors:
            if descriptor.target is not ReferenceTarget.GROUP:
                continue
            dependencies.extend(await self.scanner(descriptor.scanner_id).scan_group(project_id, group_id))
        return tuple(sorted(set(dependencies), key=lambda item: (str(item.surface_id), item.source_id)))
