from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .bindings import (
    CredentialBinding,
    EnvironmentInjectionBinding,
    HttpEgressBinding,
    McpGroupBinding,
    ModelCatalogContext,
    ModelInferenceBinding,
    WebhookAuthBinding,
)
from .resource import (
    CredentialGroupResource,
    CredentialResource,
    McpCredentialIdentity,
    ModelCredentialIdentity,
    ServiceCredentialIdentity,
)
from .types import (
    CredentialAuthScheme,
    CredentialFieldName,
    CredentialKind,
    CredentialState,
    NormalizedMcpUrl,
    ProjectId,
    require_project_id,
)


class CredentialPolicyErrorCode(StrEnum):
    PROJECT_MISMATCH = "project_mismatch"
    CREDENTIAL_ID_MISMATCH = "credential_id_mismatch"
    ARCHIVED = "archived"
    DELETED = "deleted"
    KIND_MISMATCH = "kind_mismatch"
    FIELD_MISSING = "field_missing"
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    GROUP_MISMATCH = "group_mismatch"
    URL_CONFLICT = "url_conflict"
    CATALOG_MISMATCH = "catalog_mismatch"


class CredentialPolicyError(ValueError):
    def __init__(self, code: CredentialPolicyErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class CredentialGroupRestoreContext:
    project_id: ProjectId
    members: tuple[CredentialResource, ...]
    occupied_server_urls: frozenset[NormalizedMcpUrl]

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", require_project_id(self.project_id))
        object.__setattr__(self, "members", tuple(self.members))
        urls = frozenset(self.occupied_server_urls)
        if any(not isinstance(url, NormalizedMcpUrl) for url in urls):
            raise TypeError("occupied MCP server URLs must be normalized")
        object.__setattr__(self, "occupied_server_urls", urls)


def validate_credential_binding(
    resource: CredentialResource,
    binding: CredentialBinding,
    *,
    catalog_context: ModelCatalogContext | None = None,
) -> None:
    if isinstance(binding, McpGroupBinding):
        raise TypeError("MCP Group bindings require validate_mcp_group_binding")
    if resource.project_id != binding.project_id:
        raise CredentialPolicyError(CredentialPolicyErrorCode.PROJECT_MISMATCH, "credential project mismatch")
    if resource.id != binding.credential_id:
        raise CredentialPolicyError(
            CredentialPolicyErrorCode.CREDENTIAL_ID_MISMATCH,
            "credential id mismatch",
        )
    _require_active(resource.state, subject="credential")

    expected_kind = CredentialKind.MODEL if isinstance(binding, ModelInferenceBinding) else CredentialKind.SERVICE
    if resource.kind is not expected_kind:
        raise CredentialPolicyError(
            CredentialPolicyErrorCode.KIND_MISMATCH,
            f"credential kind mismatch: expected {expected_kind.value}",
        )

    if isinstance(resource.identity, ServiceCredentialIdentity):
        _require_runnable_scheme(resource.identity.auth_scheme)

    if isinstance(binding, ModelInferenceBinding):
        _validate_model_catalog_context(resource, binding, catalog_context)
    elif isinstance(binding, WebhookAuthBinding):
        _require_field(resource, binding.credential_field)
    elif isinstance(binding, EnvironmentInjectionBinding):
        try:
            resource.material.validate_environment_field_names()
        except ValueError as exc:
            raise CredentialPolicyError(CredentialPolicyErrorCode.FIELD_MISSING, str(exc)) from exc
    elif isinstance(binding, HttpEgressBinding):
        _require_field(resource, binding.inject.credential_field)


def validate_mcp_group_binding(
    binding: McpGroupBinding,
    *,
    groups: tuple[CredentialGroupResource, ...],
    members: tuple[CredentialResource, ...],
) -> None:
    groups_by_id = {group.id: group for group in groups}
    if set(groups_by_id) != set(binding.group_ids):
        raise CredentialPolicyError(
            CredentialPolicyErrorCode.GROUP_MISMATCH,
            "MCP Group binding group ids do not match loaded groups",
        )
    for group_id in binding.group_ids:
        group = groups_by_id[group_id]
        if group.project_id != binding.project_id:
            raise CredentialPolicyError(CredentialPolicyErrorCode.PROJECT_MISMATCH, "credential group project mismatch")
        _require_active(group.state, subject="credential group")

    normalized_urls = set(binding.declared_server_urls)
    for member in members:
        if member.project_id != binding.project_id:
            raise CredentialPolicyError(CredentialPolicyErrorCode.PROJECT_MISMATCH, "MCP member project mismatch")
        _require_active(member.state, subject="credential")
        if member.kind is not CredentialKind.MCP or not isinstance(member.identity, McpCredentialIdentity):
            raise CredentialPolicyError(CredentialPolicyErrorCode.KIND_MISMATCH, "MCP member kind mismatch")
        if member.identity.group_id not in groups_by_id:
            raise CredentialPolicyError(CredentialPolicyErrorCode.GROUP_MISMATCH, "MCP member group mismatch")
        _require_runnable_scheme(member.identity.auth_scheme)
        _require_field(member, CredentialFieldName("token_value"))
        if member.identity.server_url in normalized_urls:
            raise CredentialPolicyError(
                CredentialPolicyErrorCode.URL_CONFLICT,
                f"MCP normalized URL conflict: {member.identity.server_url}",
            )
        normalized_urls.add(member.identity.server_url)


def validate_group_restore(
    group: CredentialGroupResource,
    context: CredentialGroupRestoreContext,
) -> None:
    if group.project_id != context.project_id:
        raise CredentialPolicyError(
            CredentialPolicyErrorCode.PROJECT_MISMATCH,
            "credential group restore project mismatch",
        )

    normalized_urls = set(context.occupied_server_urls)
    for member in context.members:
        if member.project_id != group.project_id:
            raise CredentialPolicyError(CredentialPolicyErrorCode.PROJECT_MISMATCH, "MCP member project mismatch")
        if member.state is CredentialState.ARCHIVED:
            continue
        _require_active(member.state, subject="credential")
        if member.kind is not CredentialKind.MCP or not isinstance(member.identity, McpCredentialIdentity):
            raise CredentialPolicyError(CredentialPolicyErrorCode.KIND_MISMATCH, "MCP member kind mismatch")
        if member.identity.group_id != group.id:
            raise CredentialPolicyError(CredentialPolicyErrorCode.GROUP_MISMATCH, "MCP member group mismatch")
        _require_runnable_scheme(member.identity.auth_scheme)
        _require_field(member, CredentialFieldName("token_value"))
        if member.identity.server_url in normalized_urls:
            raise CredentialPolicyError(
                CredentialPolicyErrorCode.URL_CONFLICT,
                f"MCP normalized URL conflict: {member.identity.server_url}",
            )
        normalized_urls.add(member.identity.server_url)


def _require_active(state: CredentialState, *, subject: str) -> None:
    if state is CredentialState.ARCHIVED:
        raise CredentialPolicyError(CredentialPolicyErrorCode.ARCHIVED, f"{subject} is archived")
    if state is CredentialState.DELETED:
        raise CredentialPolicyError(CredentialPolicyErrorCode.DELETED, f"{subject} is deleted")


def _require_runnable_scheme(auth_scheme: CredentialAuthScheme) -> None:
    if auth_scheme is CredentialAuthScheme.OAUTH2_LEGACY_DISABLED:
        raise CredentialPolicyError(
            CredentialPolicyErrorCode.UNSUPPORTED_SCHEME,
            "credential auth scheme OAUTH2_LEGACY_DISABLED cannot be used",
        )
    if auth_scheme is not CredentialAuthScheme.STATIC_BEARER:
        raise CredentialPolicyError(
            CredentialPolicyErrorCode.UNSUPPORTED_SCHEME,
            "credential auth scheme is unsupported",
        )


def _require_field(resource: CredentialResource, field_name: CredentialFieldName) -> None:
    if field_name not in resource.material.field_names:
        raise CredentialPolicyError(
            CredentialPolicyErrorCode.FIELD_MISSING,
            f"credential material field is missing: {field_name}",
        )


def _validate_model_catalog_context(
    resource: CredentialResource,
    binding: ModelInferenceBinding,
    catalog_context: ModelCatalogContext | None,
) -> None:
    if catalog_context is None:
        raise CredentialPolicyError(
            CredentialPolicyErrorCode.CATALOG_MISMATCH,
            "Catalog context is required for model inference",
        )
    identity = resource.identity
    if not isinstance(identity, ModelCredentialIdentity):
        raise CredentialPolicyError(CredentialPolicyErrorCode.CATALOG_MISMATCH, "Catalog identity mismatch")
    if catalog_context.provider_id != identity.provider_id or catalog_context.protocol_id != identity.protocol_id:
        raise CredentialPolicyError(CredentialPolicyErrorCode.CATALOG_MISMATCH, "Catalog provider/protocol mismatch")
    if catalog_context.engine_kind is not binding.engine_kind:
        raise CredentialPolicyError(CredentialPolicyErrorCode.CATALOG_MISMATCH, "Catalog engine mismatch")
    if (
        binding.model_id is not None
        and catalog_context.model_ids is not None
        and binding.model_id not in catalog_context.model_ids
    ):
        raise CredentialPolicyError(CredentialPolicyErrorCode.CATALOG_MISMATCH, "Catalog model mismatch")
