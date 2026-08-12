from __future__ import annotations

from dataclasses import dataclass, field
from typing import Type

from app.joysafeter_shared.common.app_errors import (
    AccessDeniedError,
    AppError,
    AuthenticationError,
    ClientClosedError,
    InternalServiceError,
    InvalidRequestError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitExceededError,
    RequestValidationAppError,
    ResourceConflictError,
    ServiceUnavailableError,
)


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    code: str
    error_class: Type[AppError]
    default_message: str
    retryable: bool = False
    user_action: str | None = None
    data_fields: tuple[str, ...] = field(default=())


CATALOG: dict[str, CatalogEntry] = {
    # --- Unified credentials (P0). Flat, stable, actionable codes (design 3.13).
    "CREDENTIAL_NOT_FOUND": CatalogEntry(
        code="CREDENTIAL_NOT_FOUND", error_class=NotFoundError, default_message="Credential not found"
    ),
    "CREDENTIAL_KIND_INVALID": CatalogEntry(
        code="CREDENTIAL_KIND_INVALID",
        error_class=InvalidRequestError,
        default_message="Credential kind is invalid for this operation",
        user_action="fix_input",
    ),
    "CREDENTIAL_NAME_EXISTS": CatalogEntry(
        code="CREDENTIAL_NAME_EXISTS",
        error_class=ResourceConflictError,
        default_message="A credential with this name already exists for this kind in the project",
        user_action="fix_input",
    ),
    "CREDENTIAL_IN_USE": CatalogEntry(
        code="CREDENTIAL_IN_USE",
        error_class=ResourceConflictError,
        default_message="Credential is still referenced and cannot be archived or deleted",
        user_action="fix_input",
    ),
    "CREDENTIAL_FIELD_MISSING": CatalogEntry(
        code="CREDENTIAL_FIELD_MISSING",
        error_class=InvalidRequestError,
        default_message="A required credential field is missing",
        user_action="fix_input",
    ),
    "CREDENTIAL_FIELD_INVALID": CatalogEntry(
        code="CREDENTIAL_FIELD_INVALID",
        error_class=InvalidRequestError,
        default_message="A credential field is invalid",
        user_action="fix_input",
    ),
    "CREDENTIAL_MASK_CONFLICT": CatalogEntry(
        code="CREDENTIAL_MASK_CONFLICT",
        error_class=InvalidRequestError,
        default_message="A masked value was submitted for a field with no stored value to preserve",
        user_action="fix_input",
    ),
    "CREDENTIAL_GROUP_NOT_FOUND": CatalogEntry(
        code="CREDENTIAL_GROUP_NOT_FOUND",
        error_class=NotFoundError,
        default_message="Credential group not found",
    ),
    "CREDENTIAL_GROUP_NAME_EXISTS": CatalogEntry(
        code="CREDENTIAL_GROUP_NAME_EXISTS",
        error_class=ResourceConflictError,
        default_message="A credential group with this name already exists in the project",
        user_action="fix_input",
    ),
    "CREDENTIAL_GROUP_URL_CONFLICT": CatalogEntry(
        code="CREDENTIAL_GROUP_URL_CONFLICT",
        error_class=ResourceConflictError,
        default_message="An mcp credential for this server url already exists in the group",
        user_action="fix_input",
    ),
    "CREDENTIAL_TEST_BASE_URL_REQUIRED": CatalogEntry(
        code="CREDENTIAL_TEST_BASE_URL_REQUIRED",
        error_class=InvalidRequestError,
        default_message="A base URL is required to test this credential",
        user_action="fix_input",
    ),
    "CREDENTIAL_TEST_BASE_URL_INVALID": CatalogEntry(
        code="CREDENTIAL_TEST_BASE_URL_INVALID",
        error_class=InvalidRequestError,
        default_message="The credential base URL is invalid",
        user_action="fix_input",
    ),
    "CREDENTIAL_TEST_BASE_URL_NOT_ALLOWED": CatalogEntry(
        code="CREDENTIAL_TEST_BASE_URL_NOT_ALLOWED",
        error_class=InvalidRequestError,
        default_message="The credential base URL host is not allowlisted",
        user_action="fix_input",
    ),
    "CREDENTIAL_TEST_CREDENTIAL_PROFILE_UNSUPPORTED": CatalogEntry(
        code="CREDENTIAL_TEST_CREDENTIAL_PROFILE_UNSUPPORTED",
        error_class=InvalidRequestError,
        default_message="Test connection is not supported for this credential profile",
        user_action="fix_input",
    ),
    "SESSION_CREDENTIAL_GROUP_NOT_FOUND": CatalogEntry(
        code="SESSION_CREDENTIAL_GROUP_NOT_FOUND",
        error_class=NotFoundError,
        default_message="Credential group not found",
        user_action="refresh",
    ),
    "SESSION_CREDENTIAL_GROUP_ARCHIVED": CatalogEntry(
        code="SESSION_CREDENTIAL_GROUP_ARCHIVED",
        error_class=ResourceConflictError,
        default_message="Credential group is archived",
        user_action="refresh",
    ),
    "TRIGGER_SECRET_KIND_INVALID": CatalogEntry(
        code="TRIGGER_SECRET_KIND_INVALID",
        error_class=InvalidRequestError,
        default_message="Webhook auth credential must be a service credential",
        user_action="fix_input",
    ),
    "AGENT_ACTIVE_TASKS": CatalogEntry(
        code="AGENT_ACTIVE_TASKS",
        error_class=ResourceConflictError,
        default_message="Agent has active tasks. Stop or wait for them before changing secret_ref or environment_ref.",
    ),
    "AGENT_ARCHIVED": CatalogEntry(
        code="AGENT_ARCHIVED",
        error_class=ResourceConflictError,
        default_message="Agent is archived and read-only. Updates are not allowed.",
    ),
    "AGENT_FORCE_CANCEL_ACTIVE_TASKS_FAILED": CatalogEntry(
        code="AGENT_FORCE_CANCEL_ACTIVE_TASKS_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Failed to cancel all active tasks for agent",
    ),
    "AGENT_FORCE_DELETE_ACTIVE_TASKS_REMAIN": CatalogEntry(
        code="AGENT_FORCE_DELETE_ACTIVE_TASKS_REMAIN",
        error_class=ServiceUnavailableError,
        default_message="Agent force delete active tasks remain",
    ),
    "AGENT_NOT_FOUND": CatalogEntry(
        code="AGENT_NOT_FOUND", error_class=NotFoundError, default_message="Agent not found"
    ),
    "AGENT_SANDBOX_STATE_SYNC_FAILED": CatalogEntry(
        code="AGENT_SANDBOX_STATE_SYNC_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Agent could not be deleted because sandbox state sync failed.",
    ),
    "AGENT_SANDBOX_STOP_FAILED": CatalogEntry(
        code="AGENT_SANDBOX_STOP_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Agent could not be deleted because sandbox cleanup failed.",
    ),
    "AGENT_SANDBOX_DESTROY_FAILED": CatalogEntry(
        code="AGENT_SANDBOX_DESTROY_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Agent could not be deleted because sandbox cleanup failed.",
    ),
    "AGENT_REDIS_CANCEL_RELAY_FAILED": CatalogEntry(
        code="AGENT_REDIS_CANCEL_RELAY_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Failed to cancel agent task in sandbox runtime.",
    ),
    "AGENT_SESSION_ARCHIVE_FAILED": CatalogEntry(
        code="AGENT_SESSION_ARCHIVE_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Failed to archive sessions during agent cleanup.",
    ),
    "AGENT_VERSION_CONFLICT": CatalogEntry(
        code="AGENT_VERSION_CONFLICT", error_class=ResourceConflictError, default_message="Agent version conflict"
    ),
    "AGENT_SKILL_REF_INVALID": CatalogEntry(
        code="AGENT_SKILL_REF_INVALID",
        error_class=InvalidRequestError,
        default_message="Invalid skill reference id",
    ),
    "AGENT_SKILL_REF_NOT_FOUND": CatalogEntry(
        code="AGENT_SKILL_REF_NOT_FOUND",
        error_class=InvalidRequestError,
        default_message="Agent references skills that do not exist in this project",
    ),
    "AGENT_SKILL_REF_NOT_RUNTIME_READY": CatalogEntry(
        code="AGENT_SKILL_REF_NOT_RUNTIME_READY",
        error_class=InvalidRequestError,
        default_message="Agent can only reference published, runtime-ready skills",
    ),
    "API_KEY_NOT_FOUND": CatalogEntry(
        code="API_KEY_NOT_FOUND", error_class=NotFoundError, default_message="API key not found"
    ),
    "AUTH_API_KEY_ACCESS_REVOKED": CatalogEntry(
        code="AUTH_API_KEY_ACCESS_REVOKED",
        error_class=AccessDeniedError,
        default_message="API key creator no longer has access to the project",
    ),
    "AUTH_INVALID_ASSIGNABLE_ROLE": CatalogEntry(
        code="AUTH_INVALID_ASSIGNABLE_ROLE",
        error_class=InvalidRequestError,
        default_message="Invalid role for this operation",
    ),
    "AUTH_JWT_CONTEXT_INCOMPLETE": CatalogEntry(
        code="AUTH_JWT_CONTEXT_INCOMPLETE",
        error_class=InternalServiceError,
        default_message="Authentication context is incomplete",
    ),
    "AUTH_JWT_CONTEXT_RESOLVE_FAILED": CatalogEntry(
        code="AUTH_JWT_CONTEXT_RESOLVE_FAILED",
        error_class=InternalServiceError,
        default_message="Failed to resolve authentication context",
    ),
    "AUTH_REQUIRED": CatalogEntry(
        code="AUTH_REQUIRED", error_class=AuthenticationError, default_message="Authentication required"
    ),
    "AUTH_USER_NOT_FOUND": CatalogEntry(
        code="AUTH_USER_NOT_FOUND", error_class=NotFoundError, default_message="User not found with the given email"
    ),
    "BAD_REQUEST": CatalogEntry(code="BAD_REQUEST", error_class=InvalidRequestError, default_message="请求错误"),
    "BEARER_TOKEN_MISSING": CatalogEntry(
        code="BEARER_TOKEN_MISSING", error_class=AuthenticationError, default_message="Missing bearer token"
    ),
    "CLIENT_CLOSED": CatalogEntry(
        code="CLIENT_CLOSED", error_class=ClientClosedError, default_message="客户端已关闭连接"
    ),
    "CONFLICT": CatalogEntry(code="CONFLICT", error_class=ResourceConflictError, default_message="资源冲突"),
    "CSRF_VALIDATION_FAILED": CatalogEntry(
        code="CSRF_VALIDATION_FAILED",
        error_class=AccessDeniedError,
        default_message="CSRF 校验失败，请刷新页面后重试 / CSRF validation failed",
    ),
    "DEFAULT_PROJECT_NOT_FOUND": CatalogEntry(
        code="DEFAULT_PROJECT_NOT_FOUND",
        error_class=NotFoundError,
        default_message="No default project found for the organization",
    ),
    "EMAIL_ALREADY_VERIFIED": CatalogEntry(
        code="EMAIL_ALREADY_VERIFIED", error_class=InvalidRequestError, default_message="Email already verified"
    ),
    "EMAIL_NOT_VERIFIED": CatalogEntry(
        code="EMAIL_NOT_VERIFIED",
        error_class=AccessDeniedError,
        default_message="Email not verified. Please verify your email before logging in.",
    ),
    "ENVIRONMENT_ACTIVE_SESSION_REFERENCE": CatalogEntry(
        code="ENVIRONMENT_ACTIVE_SESSION_REFERENCE",
        error_class=ResourceConflictError,
        default_message="Environment is referenced by one or more active sessions. Archive or remove those sessions first.",
    ),
    "ENVIRONMENT_ACTIVE_TASK": CatalogEntry(
        code="ENVIRONMENT_ACTIVE_TASK", error_class=ResourceConflictError, default_message="Environment active task"
    ),
    "ENVIRONMENT_AGENT_REFERENCE": CatalogEntry(
        code="ENVIRONMENT_AGENT_REFERENCE",
        error_class=ResourceConflictError,
        default_message="Environment agent reference",
    ),
    "ENVIRONMENT_ARCHIVED": CatalogEntry(
        code="ENVIRONMENT_ARCHIVED",
        error_class=ResourceConflictError,
        default_message="Cannot update an archived environment",
    ),
    "ENVIRONMENT_CONFLICT": CatalogEntry(
        code="ENVIRONMENT_CONFLICT", error_class=ResourceConflictError, default_message="Environment conflict"
    ),
    "ENVIRONMENT_ID_INVALID": CatalogEntry(
        code="ENVIRONMENT_ID_INVALID",
        error_class=InvalidRequestError,
        default_message="Invalid environment_id",
    ),
    "ENVIRONMENT_TRIGGER_REFERENCE": CatalogEntry(
        code="ENVIRONMENT_TRIGGER_REFERENCE",
        error_class=ResourceConflictError,
        default_message="Environment cron trigger reference",
    ),
    "ENVIRONMENT_IMAGE_BUILD_FAILED": CatalogEntry(
        code="ENVIRONMENT_IMAGE_BUILD_FAILED",
        error_class=InternalServiceError,
        default_message="Environment image build failed",
    ),
    "ENVIRONMENT_IMAGE_BUILD_RELAY_FAILED": CatalogEntry(
        code="ENVIRONMENT_IMAGE_BUILD_RELAY_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Redis environment image build relay failed",
    ),
    "ENVIRONMENT_IMAGE_BUILDER_UNAVAILABLE": CatalogEntry(
        code="ENVIRONMENT_IMAGE_BUILDER_UNAVAILABLE",
        error_class=ServiceUnavailableError,
        default_message="Image builder is unavailable",
    ),
    "ENVIRONMENT_NOT_FOUND": CatalogEntry(
        code="ENVIRONMENT_NOT_FOUND", error_class=NotFoundError, default_message="Environment not found"
    ),
    "ENVIRONMENT_SECRET_NOT_FOUND": CatalogEntry(
        code="ENVIRONMENT_SECRET_NOT_FOUND",
        error_class=InvalidRequestError,
        default_message="Environment secret not found",
    ),
    "FILE_ID_INVALID": CatalogEntry(
        code="FILE_ID_INVALID", error_class=InvalidRequestError, default_message="Invalid file_id"
    ),
    "FILE_NOT_FOUND": CatalogEntry(code="FILE_NOT_FOUND", error_class=NotFoundError, default_message="File not found"),
    "FILE_UPLOAD_FAILED": CatalogEntry(
        code="FILE_UPLOAD_FAILED", error_class=InternalServiceError, default_message="File upload failed"
    ),
    "FILE_IN_USE_BY_SESSION_RESOURCE": CatalogEntry(
        code="FILE_IN_USE_BY_SESSION_RESOURCE",
        error_class=ResourceConflictError,
        default_message="File is attached to active session resources",
    ),
    "FORBIDDEN": CatalogEntry(code="FORBIDDEN", error_class=AccessDeniedError, default_message="无权限"),
    "IDEMPOTENCY_KEY_IN_PROGRESS": CatalogEntry(
        code="IDEMPOTENCY_KEY_IN_PROGRESS",
        error_class=ResourceConflictError,
        default_message="Idempotency-Key is already in progress",
    ),
    "INTERNAL_ERROR": CatalogEntry(code="INTERNAL_ERROR", error_class=InternalServiceError, default_message="内部错误"),
    "INVALID_API_KEY": CatalogEntry(
        code="INVALID_API_KEY",
        error_class=AuthenticationError,
        default_message="API Key 无效或已过期 / Invalid or expired API key",
    ),
    "INVALID_CREDENTIALS": CatalogEntry(
        code="INVALID_CREDENTIALS", error_class=AuthenticationError, default_message="Incorrect email or password"
    ),
    "JOYSAFETER_ADMIN_REQUIRED": CatalogEntry(
        code="JOYSAFETER_ADMIN_REQUIRED", error_class=AccessDeniedError, default_message="Admin access required"
    ),
    "JOYSAFETER_PROJECT_ADMIN_REQUIRED": CatalogEntry(
        code="JOYSAFETER_PROJECT_ADMIN_REQUIRED",
        error_class=AccessDeniedError,
        default_message="Project admin access required",
    ),
    "JOYSAFETER_UNAUTHORIZED": CatalogEntry(
        code="JOYSAFETER_UNAUTHORIZED",
        error_class=AuthenticationError,
        default_message="凭证缺失或无效，请重新登录 / Missing or invalid credentials",
    ),
    "JOYSAFETER_USER_SESSION_REQUIRED": CatalogEntry(
        code="JOYSAFETER_USER_SESSION_REQUIRED",
        error_class=AccessDeniedError,
        default_message="User session required",
    ),
    "JOYSAFETER_WRITE_REQUIRED": CatalogEntry(
        code="JOYSAFETER_WRITE_REQUIRED", error_class=AccessDeniedError, default_message="Write access required"
    ),
    "MEMBERSHIP_EXPIRED": CatalogEntry(
        code="MEMBERSHIP_EXPIRED",
        error_class=AuthenticationError,
        default_message="组织成员资格已失效，请重新登录 / Organization membership expired, please re-login",
    ),
    "MEMORY_CONTENT_TOO_LARGE": CatalogEntry(
        code="MEMORY_CONTENT_TOO_LARGE", error_class=InvalidRequestError, default_message="Memory content too large"
    ),
    "MEMORY_LIST_ORDER_INVALID": CatalogEntry(
        code="MEMORY_LIST_ORDER_INVALID",
        error_class=InvalidRequestError,
        default_message="order must be 'asc' or 'desc'",
    ),
    "MEMORY_LIVE_VERSION_REDACTION_FORBIDDEN": CatalogEntry(
        code="MEMORY_LIVE_VERSION_REDACTION_FORBIDDEN",
        error_class=ResourceConflictError,
        default_message="Cannot redact a live version. This version is the current version of a memory.",
    ),
    "MEMORY_METADATA_INVALID": CatalogEntry(
        code="MEMORY_METADATA_INVALID", error_class=InvalidRequestError, default_message="Memory metadata invalid"
    ),
    "MEMORY_NOT_FOUND": CatalogEntry(
        code="MEMORY_NOT_FOUND", error_class=NotFoundError, default_message="Memory not found"
    ),
    "MEMORY_PATH_CONFLICT": CatalogEntry(
        code="MEMORY_PATH_CONFLICT", error_class=ResourceConflictError, default_message="Memory path conflict"
    ),
    "MEMORY_PATH_INVALID": CatalogEntry(
        code="MEMORY_PATH_INVALID", error_class=InvalidRequestError, default_message="Memory path invalid"
    ),
    "MEMORY_PRECONDITION_FAILED": CatalogEntry(
        code="MEMORY_PRECONDITION_FAILED",
        error_class=ResourceConflictError,
        default_message="Memory precondition failed",
    ),
    "MEMORY_STORE_ACTIVE_SESSION_REFERENCE": CatalogEntry(
        code="MEMORY_STORE_ACTIVE_SESSION_REFERENCE",
        error_class=ResourceConflictError,
        default_message="Memory store active session reference",
    ),
    "MEMORY_STORE_ARCHIVED": CatalogEntry(
        code="MEMORY_STORE_ARCHIVED",
        error_class=ResourceConflictError,
        default_message="Memory store is archived",
    ),
    "MEMORY_STORE_CONFLICT": CatalogEntry(
        code="MEMORY_STORE_CONFLICT", error_class=ResourceConflictError, default_message="Memory store conflict"
    ),
    "MEMORY_STORE_LIMIT_EXCEEDED": CatalogEntry(
        code="MEMORY_STORE_LIMIT_EXCEEDED",
        error_class=ResourceConflictError,
        default_message="Memory store limit exceeded",
    ),
    "MEMORY_STORE_NOT_FOUND": CatalogEntry(
        code="MEMORY_STORE_NOT_FOUND", error_class=NotFoundError, default_message="Memory store not found"
    ),
    "MEMORY_VERSION_NOT_FOUND": CatalogEntry(
        code="MEMORY_VERSION_NOT_FOUND", error_class=NotFoundError, default_message="Memory version not found"
    ),
    "MISSING_CREDENTIALS": CatalogEntry(
        code="MISSING_CREDENTIALS", error_class=AuthenticationError, default_message="Missing credentials"
    ),
    "NOT_FOUND": CatalogEntry(code="NOT_FOUND", error_class=NotFoundError, default_message="资源不存在"),
    "NOT_ORG_MEMBER": CatalogEntry(
        code="NOT_ORG_MEMBER",
        error_class=AuthenticationError,
        default_message="User is not a member of the requested organization",
    ),
    "NO_PROJECT": CatalogEntry(
        code="NO_PROJECT", error_class=AuthenticationError, default_message="No project found for organization"
    ),
    "OAUTH_EMAIL_REQUIRED": CatalogEntry(
        code="OAUTH_EMAIL_REQUIRED", error_class=InvalidRequestError, default_message="Oauth email required"
    ),
    "OAUTH_LAST_ACCOUNT_UNLINK_FORBIDDEN": CatalogEntry(
        code="OAUTH_LAST_ACCOUNT_UNLINK_FORBIDDEN",
        error_class=InvalidRequestError,
        default_message="Cannot unlink the only OAuth account. Please set a password first.",
    ),
    "OAUTH_PROVIDER_NOT_FOUND": CatalogEntry(
        code="OAUTH_PROVIDER_NOT_FOUND", error_class=InvalidRequestError, default_message="Oauth provider not found"
    ),
    "OAUTH_REGISTRATION_DISABLED": CatalogEntry(
        code="OAUTH_REGISTRATION_DISABLED",
        error_class=AuthenticationError,
        default_message="Registration via OAuth is not allowed. Please sign up first.",
    ),
    "OAUTH_TOKEN_EXCHANGE_FAILED": CatalogEntry(
        code="OAUTH_TOKEN_EXCHANGE_FAILED",
        error_class=InvalidRequestError,
        default_message="Oauth token exchange failed",
    ),
    "OAUTH_TOKEN_URL_INVALID": CatalogEntry(
        code="OAUTH_TOKEN_URL_INVALID",
        error_class=InvalidRequestError,
        default_message="OAuth token URL failed security validation",
    ),
    "OAUTH_USERINFO_FETCH_FAILED": CatalogEntry(
        code="OAUTH_USERINFO_FETCH_FAILED",
        error_class=InvalidRequestError,
        default_message="Oauth userinfo fetch failed",
    ),
    "OAUTH_USERINFO_URL_INVALID": CatalogEntry(
        code="OAUTH_USERINFO_URL_INVALID",
        error_class=InvalidRequestError,
        default_message="OAuth userinfo URL failed security validation",
    ),
    "ORGANIZATION_ACCESS_DENIED": CatalogEntry(
        code="ORGANIZATION_ACCESS_DENIED", error_class=AccessDeniedError, default_message="No access to organization"
    ),
    "ORGANIZATION_MEMBER_ALREADY_EXISTS": CatalogEntry(
        code="ORGANIZATION_MEMBER_ALREADY_EXISTS",
        error_class=ResourceConflictError,
        default_message="User is already a member of this organization",
    ),
    "ORGANIZATION_MEMBER_NOT_FOUND": CatalogEntry(
        code="ORGANIZATION_MEMBER_NOT_FOUND", error_class=NotFoundError, default_message="Member not found"
    ),
    "ORGANIZATION_MEMBER_ROLE_INVALID": CatalogEntry(
        code="ORGANIZATION_MEMBER_ROLE_INVALID", error_class=InvalidRequestError, default_message="Invalid member role"
    ),
    "ORGANIZATION_NAME_REQUIRED": CatalogEntry(
        code="ORGANIZATION_NAME_REQUIRED",
        error_class=InvalidRequestError,
        default_message="Organization name is required",
    ),
    "ORGANIZATION_NOT_FOUND": CatalogEntry(
        code="ORGANIZATION_NOT_FOUND", error_class=NotFoundError, default_message="Organization not found"
    ),
    "ORGANIZATION_OWNER_TRANSFER_SELF": CatalogEntry(
        code="ORGANIZATION_OWNER_TRANSFER_SELF",
        error_class=InvalidRequestError,
        default_message="Cannot transfer ownership to yourself",
    ),
    "ORGANIZATION_PERMISSION_DENIED": CatalogEntry(
        code="ORGANIZATION_PERMISSION_DENIED",
        error_class=AccessDeniedError,
        default_message="Insufficient organization permission",
    ),
    "ORGANIZATION_PROJECT_RESOURCES_EXIST": CatalogEntry(
        code="ORGANIZATION_PROJECT_RESOURCES_EXIST",
        error_class=ResourceConflictError,
        default_message="Organization has project resources",
    ),
    "PROJECT_ACCESS_DENIED": CatalogEntry(
        code="PROJECT_ACCESS_DENIED", error_class=AccessDeniedError, default_message="No access to project"
    ),
    "PROJECT_ACTIVE_TASKS": CatalogEntry(
        code="PROJECT_ACTIVE_TASKS",
        error_class=ResourceConflictError,
        default_message="Project has active tasks. Stop or wait for them before archiving.",
    ),
    "PROJECT_ARCHIVE_REDIS_SHUTDOWN_FAILED": CatalogEntry(
        code="PROJECT_ARCHIVE_REDIS_SHUTDOWN_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Failed to deliver shutdown command to project session sandbox runtime.",
    ),
    "PROJECT_ARCHIVE_REDIS_DESTROY_FAILED": CatalogEntry(
        code="PROJECT_ARCHIVE_REDIS_DESTROY_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Failed to destroy project session sandbox runtime.",
    ),
    "PROJECT_ARCHIVED": CatalogEntry(
        code="PROJECT_ARCHIVED",
        error_class=ResourceConflictError,
        default_message="项目已归档，仅支持只读操作 / Project is archived and read-only",
    ),
    "PROJECT_DEFAULT_ARCHIVE_FORBIDDEN": CatalogEntry(
        code="PROJECT_DEFAULT_ARCHIVE_FORBIDDEN",
        error_class=InvalidRequestError,
        default_message="Cannot archive the default project",
    ),
    "PROJECT_NAME_REQUIRED": CatalogEntry(
        code="PROJECT_NAME_REQUIRED", error_class=InvalidRequestError, default_message="Project name is required"
    ),
    "PROJECT_NAME_TOO_LONG": CatalogEntry(
        code="PROJECT_NAME_TOO_LONG",
        error_class=InvalidRequestError,
        default_message="Project name must be 255 characters or fewer",
    ),
    "PROJECT_NOT_FOUND": CatalogEntry(
        code="PROJECT_NOT_FOUND", error_class=NotFoundError, default_message="Project not found"
    ),
    "PROJECT_MEMBER_NOT_FOUND": CatalogEntry(
        code="PROJECT_MEMBER_NOT_FOUND",
        error_class=NotFoundError,
        default_message="User has no explicit membership in this project",
    ),
    "PROJECT_MEMBER_DEFAULT_REMOVE_FORBIDDEN": CatalogEntry(
        code="PROJECT_MEMBER_DEFAULT_REMOVE_FORBIDDEN",
        error_class=InvalidRequestError,
        default_message="Cannot remove a member from the default project",
    ),
    "PROJECT_SLUG_CONFLICT": CatalogEntry(
        code="PROJECT_SLUG_CONFLICT",
        error_class=ResourceConflictError,
        default_message="Project slug already exists in this organization",
    ),
    "PROJECT_SLUG_INVALID": CatalogEntry(
        code="PROJECT_SLUG_INVALID",
        error_class=InvalidRequestError,
        default_message="Project slug must contain only lowercase letters, numbers, and hyphens",
    ),
    "PROJECT_SLUG_REQUIRED": CatalogEntry(
        code="PROJECT_SLUG_REQUIRED", error_class=InvalidRequestError, default_message="Project slug is required"
    ),
    "PROJECT_SLUG_TOO_LONG": CatalogEntry(
        code="PROJECT_SLUG_TOO_LONG",
        error_class=InvalidRequestError,
        default_message="Project slug must be 255 characters or fewer",
    ),
    "PROJECT_TASK_LIMIT_EXCEEDED": CatalogEntry(
        code="PROJECT_TASK_LIMIT_EXCEEDED",
        error_class=RateLimitExceededError,
        default_message="Project has reached its concurrent task limit.",
        retryable=True,
        user_action="retry",
    ),
    "PROJECT_SANDBOX_DESTROY_FAILED": CatalogEntry(
        code="PROJECT_SANDBOX_DESTROY_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Project could not be archived because sandbox cleanup failed.",
    ),
    "PROJECT_SANDBOX_STATE_SYNC_FAILED": CatalogEntry(
        code="PROJECT_SANDBOX_STATE_SYNC_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Project could not be archived because sandbox state sync failed.",
    ),
    "PROJECT_SANDBOX_STOP_FAILED": CatalogEntry(
        code="PROJECT_SANDBOX_STOP_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Project could not be archived because sandbox cleanup failed.",
    ),
    "QUICKSTART_BASE_URL_INVALID": CatalogEntry(
        code="QUICKSTART_BASE_URL_INVALID",
        error_class=InvalidRequestError,
        default_message="Invalid ANTHROPIC_BASE_URL",
    ),
    "QUICKSTART_BASE_URL_NOT_ALLOWED": CatalogEntry(
        code="QUICKSTART_BASE_URL_NOT_ALLOWED",
        error_class=InvalidRequestError,
        default_message="LLM base URL host is not allowlisted.",
    ),
    "QUICKSTART_BASE_URL_REQUIRED": CatalogEntry(
        code="QUICKSTART_BASE_URL_REQUIRED",
        error_class=InvalidRequestError,
        default_message="Base URL is required for this provider",
        user_action="fix_input",
    ),
    "QUICKSTART_PROTOCOL_UNSUPPORTED": CatalogEntry(
        code="QUICKSTART_PROTOCOL_UNSUPPORTED",
        error_class=InvalidRequestError,
        default_message="Quickstart does not support this protocol",
        user_action="fix_input",
    ),
    "QUICKSTART_SECRET_INCOMPATIBLE": CatalogEntry(
        code="QUICKSTART_SECRET_INCOMPATIBLE",
        error_class=InvalidRequestError,
        default_message="Secret is not compatible with the selected engine kind",
    ),
    "QUICKSTART_SECRET_MISSING_KEY": CatalogEntry(
        code="QUICKSTART_SECRET_MISSING_KEY",
        error_class=InvalidRequestError,
        default_message="Secret not found or missing required keys",
    ),
    "QUICKSTART_SECRET_NOT_FOUND": CatalogEntry(
        code="QUICKSTART_SECRET_NOT_FOUND",
        error_class=NotFoundError,
        default_message="Secret not found or missing required keys",
    ),
    "RATE_LIMITED": CatalogEntry(
        code="RATE_LIMITED", error_class=RateLimitExceededError, default_message="请求过于频繁"
    ),
    "REFRESH_TOKEN_INVALID": CatalogEntry(
        code="REFRESH_TOKEN_INVALID",
        error_class=AuthenticationError,
        default_message="Invalid or expired refresh token",
    ),
    "REQUEST_BODY_TOO_LARGE": CatalogEntry(
        code="REQUEST_BODY_TOO_LARGE",
        error_class=PayloadTooLargeError,
        default_message="请求体过大 / Request body too large",
    ),
    "REQUEST_VALIDATION_ERROR": CatalogEntry(
        code="REQUEST_VALIDATION_ERROR", error_class=RequestValidationAppError, default_message="请求参数校验失败"
    ),
    "RESET_TOKEN_EXPIRED": CatalogEntry(
        code="RESET_TOKEN_EXPIRED", error_class=InvalidRequestError, default_message="Reset token has expired"
    ),
    "RESET_TOKEN_INVALID": CatalogEntry(
        code="RESET_TOKEN_INVALID", error_class=InvalidRequestError, default_message="Invalid or expired reset token"
    ),
    "SANDBOX_NOT_FOUND": CatalogEntry(
        code="SANDBOX_NOT_FOUND", error_class=NotFoundError, default_message="Sandbox not found"
    ),
    "SANDBOX_FILE_NOT_FOUND": CatalogEntry(
        code="SANDBOX_FILE_NOT_FOUND",
        error_class=NotFoundError,
        default_message="Sandbox file path not found",
    ),
    "SANDBOX_FILE_PATH_HIDDEN": CatalogEntry(
        code="SANDBOX_FILE_PATH_HIDDEN",
        error_class=InvalidRequestError,
        default_message="Sandbox hidden files are not accessible",
    ),
    "SANDBOX_FILE_PATH_INVALID": CatalogEntry(
        code="SANDBOX_FILE_PATH_INVALID",
        error_class=InvalidRequestError,
        default_message="Invalid sandbox file path",
    ),
    "SANDBOX_FILE_PATH_OUTSIDE_WORKSPACE": CatalogEntry(
        code="SANDBOX_FILE_PATH_OUTSIDE_WORKSPACE",
        error_class=InvalidRequestError,
        default_message="Sandbox file path must be under /workspace",
    ),
    "SANDBOX_FILE_PATH_TRAVERSAL": CatalogEntry(
        code="SANDBOX_FILE_PATH_TRAVERSAL",
        error_class=InvalidRequestError,
        default_message="Sandbox file path cannot contain '..'",
    ),
    "SANDBOX_FILE_PAYLOAD_INVALID": CatalogEntry(
        code="SANDBOX_FILE_PAYLOAD_INVALID",
        error_class=ServiceUnavailableError,
        default_message="Sandbox file payload is invalid",
    ),
    "SANDBOX_FILE_TOO_LARGE": CatalogEntry(
        code="SANDBOX_FILE_TOO_LARGE",
        error_class=InvalidRequestError,
        default_message="Sandbox file exceeds download size limit",
    ),
    "SERVICE_UNAVAILABLE": CatalogEntry(
        code="SERVICE_UNAVAILABLE", error_class=ServiceUnavailableError, default_message="服务暂不可用"
    ),
    "SESSION_ACTIVE_TASK": CatalogEntry(
        code="SESSION_ACTIVE_TASK",
        error_class=ResourceConflictError,
        default_message="Session has an active task; stop it before deleting session",
    ),
    "SESSION_AGENT_ID_INVALID": CatalogEntry(
        code="SESSION_AGENT_ID_INVALID", error_class=InvalidRequestError, default_message="Session agent id invalid"
    ),
    "SESSION_AGENT_NOT_FOUND": CatalogEntry(
        code="SESSION_AGENT_NOT_FOUND", error_class=NotFoundError, default_message="Agent not found"
    ),
    "SESSION_AGENT_VERSION_NOT_FOUND": CatalogEntry(
        code="SESSION_AGENT_VERSION_NOT_FOUND",
        error_class=NotFoundError,
        default_message="Session agent version not found",
    ),
    "SESSION_ALREADY_RUNNING": CatalogEntry(
        code="SESSION_ALREADY_RUNNING",
        error_class=ResourceConflictError,
        default_message="Running session cannot be deleted. Send user.interrupt first.",
    ),
    "SESSION_ARCHIVED": CatalogEntry(
        code="SESSION_ARCHIVED", error_class=ResourceConflictError, default_message="Session is archived"
    ),
    "SESSION_CONTENT_BLOCK_INVALID": CatalogEntry(
        code="SESSION_CONTENT_BLOCK_INVALID",
        error_class=RequestValidationAppError,
        default_message="Each content block must be an object with {type, text}",
    ),
    "SESSION_CONTENT_EMPTY": CatalogEntry(
        code="SESSION_CONTENT_EMPTY",
        error_class=RequestValidationAppError,
        default_message="Content blocks array must not be empty",
    ),
    "SESSION_CONTENT_INVALID": CatalogEntry(
        code="SESSION_CONTENT_INVALID",
        error_class=RequestValidationAppError,
        default_message="content must be a string or array of content blocks",
    ),
    "SESSION_CONTENT_TOO_LARGE": CatalogEntry(
        code="SESSION_CONTENT_TOO_LARGE",
        error_class=RequestValidationAppError,
        default_message="Message content is too large",
    ),
    "SESSION_CUSTOM_TOOL_RESULT_DELIVERY_FAILED": CatalogEntry(
        code="SESSION_CUSTOM_TOOL_RESULT_DELIVERY_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Failed to deliver custom tool result",
    ),
    "SESSION_EVENTS_EMPTY": CatalogEntry(
        code="SESSION_EVENTS_EMPTY", error_class=InvalidRequestError, default_message="No events provided"
    ),
    "SESSION_ENVIRONMENT_NOT_FOUND": CatalogEntry(
        code="SESSION_ENVIRONMENT_NOT_FOUND",
        error_class=RequestValidationAppError,
        default_message="Environment not found",
    ),
    "SESSION_FILE_ID_INVALID": CatalogEntry(
        code="SESSION_FILE_ID_INVALID", error_class=InvalidRequestError, default_message="Session file id invalid"
    ),
    "SESSION_FILE_NOT_FOUND": CatalogEntry(
        code="SESSION_FILE_NOT_FOUND", error_class=NotFoundError, default_message="Session file not found"
    ),
    "SESSION_FILE_RESOURCE_INVALID": CatalogEntry(
        code="SESSION_FILE_RESOURCE_INVALID", error_class=InvalidRequestError, default_message="Invalid file resource"
    ),
    "SESSION_FILE_RESOURCE_LIMIT_EXCEEDED": CatalogEntry(
        code="SESSION_FILE_RESOURCE_LIMIT_EXCEEDED",
        error_class=InvalidRequestError,
        default_message="Session file resource limit exceeded",
    ),
    "SESSION_IDEMPOTENCY_KEY_MISMATCH": CatalogEntry(
        code="SESSION_IDEMPOTENCY_KEY_MISMATCH",
        error_class=ResourceConflictError,
        default_message="Idempotency-Key was already used for a different session",
    ),
    "SESSION_ID_INVALID": CatalogEntry(
        code="SESSION_ID_INVALID", error_class=InvalidRequestError, default_message="Invalid session_id"
    ),
    "SESSION_INTERRUPT_DELIVERY_FAILED": CatalogEntry(
        code="SESSION_INTERRUPT_DELIVERY_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Failed to deliver interrupt",
    ),
    "SESSION_MEMORY_STORE_NOT_FOUND": CatalogEntry(
        code="SESSION_MEMORY_STORE_NOT_FOUND",
        error_class=NotFoundError,
        default_message="Session memory store not found",
    ),
    "SESSION_MEMORY_STORE_RESOURCE_LIMIT_EXCEEDED": CatalogEntry(
        code="SESSION_MEMORY_STORE_RESOURCE_LIMIT_EXCEEDED",
        error_class=InvalidRequestError,
        default_message="Session memory store resource limit exceeded",
    ),
    "SESSION_NOT_FOUND": CatalogEntry(
        code="SESSION_NOT_FOUND", error_class=NotFoundError, default_message="Session not found"
    ),
    "SESSION_REPO_RESOURCE_INVALID": CatalogEntry(
        code="SESSION_REPO_RESOURCE_INVALID", error_class=InvalidRequestError, default_message="Invalid repo resource"
    ),
    "SESSION_REPO_RESOURCE_LIMIT_EXCEEDED": CatalogEntry(
        code="SESSION_REPO_RESOURCE_LIMIT_EXCEEDED",
        error_class=InvalidRequestError,
        default_message="Session repo resource limit exceeded",
    ),
    "SESSION_REPO_RESOURCE_NOT_FOUND": CatalogEntry(
        code="SESSION_REPO_RESOURCE_NOT_FOUND", error_class=NotFoundError, default_message="Repo resource not found"
    ),
    "SESSION_REPO_URL_REQUIRED": CatalogEntry(
        code="SESSION_REPO_URL_REQUIRED", error_class=InvalidRequestError, default_message="Repo url is required"
    ),
    "SESSION_RESCHEDULING": CatalogEntry(
        code="SESSION_RESCHEDULING",
        error_class=ResourceConflictError,
        default_message="Session is rescheduling, try again later",
    ),
    "SESSION_RESOURCE_BODY_INVALID": CatalogEntry(
        code="SESSION_RESOURCE_BODY_INVALID",
        error_class=InvalidRequestError,
        default_message="Request body must be an object",
    ),
    "SESSION_RESOURCE_ID_INVALID": CatalogEntry(
        code="SESSION_RESOURCE_ID_INVALID", error_class=InvalidRequestError, default_message="Invalid resource_id"
    ),
    "SESSION_RESOURCE_MOUNT_PATH_INVALID": CatalogEntry(
        code="SESSION_RESOURCE_MOUNT_PATH_INVALID",
        error_class=InvalidRequestError,
        default_message="mount_path must be under /workspace/",
    ),
    "SESSION_RESOURCE_NOT_FOUND": CatalogEntry(
        code="SESSION_RESOURCE_NOT_FOUND", error_class=NotFoundError, default_message="Resource not found"
    ),
    "SESSION_RESOURCE_TYPE_UNSUPPORTED": CatalogEntry(
        code="SESSION_RESOURCE_TYPE_UNSUPPORTED",
        error_class=InvalidRequestError,
        default_message="Session resource type unsupported",
    ),
    "SESSION_SANDBOX_DESTROY_FAILED": CatalogEntry(
        code="SESSION_SANDBOX_DESTROY_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Session could not be deleted because its sandbox cleanup failed.",
    ),
    "SESSION_STOP_CANCEL_TASKS_FAILED": CatalogEntry(
        code="SESSION_STOP_CANCEL_TASKS_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Failed to cancel all active tasks",
    ),
    "SESSION_STOP_IDLE_SYNC_FAILED": CatalogEntry(
        code="SESSION_STOP_IDLE_SYNC_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Failed to mark session idle",
    ),
    "SESSION_TERMINATED": CatalogEntry(
        code="SESSION_TERMINATED", error_class=ResourceConflictError, default_message="Session is terminated"
    ),
    "SESSION_TOOL_CONFIRMATION_DELIVERY_FAILED": CatalogEntry(
        code="SESSION_TOOL_CONFIRMATION_DELIVERY_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Failed to deliver tool confirmation",
    ),
    "SESSION_USER_MESSAGE_CONTENT_REQUIRED": CatalogEntry(
        code="SESSION_USER_MESSAGE_CONTENT_REQUIRED",
        error_class=RequestValidationAppError,
        default_message="user.message requires content",
    ),
    "SESSION_FILE_MOUNT_PATH_CONFLICT": CatalogEntry(
        code="SESSION_FILE_MOUNT_PATH_CONFLICT",
        error_class=ResourceConflictError,
        default_message="Session file mount path conflict",
    ),
    "SESSION_MEMORY_STORE_ALREADY_ATTACHED": CatalogEntry(
        code="SESSION_MEMORY_STORE_ALREADY_ATTACHED",
        error_class=ResourceConflictError,
        default_message="Session memory store already attached",
    ),
    "SESSION_MEMORY_STORE_ARCHIVED": CatalogEntry(
        code="SESSION_MEMORY_STORE_ARCHIVED",
        error_class=ResourceConflictError,
        default_message="Session memory store archived",
    ),
    "SESSION_REPO_MOUNT_PATH_CONFLICT": CatalogEntry(
        code="SESSION_REPO_MOUNT_PATH_CONFLICT",
        error_class=ResourceConflictError,
        default_message="Session repo mount path conflict",
    ),
    "SESSION_REPO_MOUNT_PATH_INVALID": CatalogEntry(
        code="SESSION_REPO_MOUNT_PATH_INVALID",
        error_class=InvalidRequestError,
        default_message="Session repo mount path invalid",
    ),
    "SESSION_RESOURCE_MOUNT_PATH_CONFLICT": CatalogEntry(
        code="SESSION_RESOURCE_MOUNT_PATH_CONFLICT",
        error_class=ResourceConflictError,
        default_message="Session resource mount path conflict",
    ),
    "SESSION_SANDBOX_FILE_RELAY_UNAVAILABLE": CatalogEntry(
        code="SESSION_SANDBOX_FILE_RELAY_UNAVAILABLE",
        error_class=ServiceUnavailableError,
        default_message="Sandbox file service is not available",
    ),
    "SESSION_SANDBOX_NOT_AVAILABLE": CatalogEntry(
        code="SESSION_SANDBOX_NOT_AVAILABLE",
        error_class=ServiceUnavailableError,
        default_message="Session sandbox is not available",
    ),
    "TRIGGER_ENVIRONMENT_NOT_FOUND": CatalogEntry(
        code="TRIGGER_ENVIRONMENT_NOT_FOUND",
        error_class=RequestValidationAppError,
        default_message="Trigger environment not found",
    ),
    "TRIGGER_AGENT_NOT_FOUND": CatalogEntry(
        code="TRIGGER_AGENT_NOT_FOUND",
        error_class=NotFoundError,
        default_message="Trigger agent not found",
    ),
    "SKILL_ACCESS_DENIED": CatalogEntry(
        code="SKILL_ACCESS_DENIED",
        error_class=AccessDeniedError,
        default_message="You don't have permission to access this skill",
    ),
    "SKILL_ADMIN_PERMISSION_DENIED": CatalogEntry(
        code="SKILL_ADMIN_PERMISSION_DENIED",
        error_class=AccessDeniedError,
        default_message="Batch rescan requires admin or owner role",
    ),
    "SKILL_AUTHORING_BASE_URL_INVALID": CatalogEntry(
        code="SKILL_AUTHORING_BASE_URL_INVALID",
        error_class=InvalidRequestError,
        default_message="Invalid OPENAI_BASE_URL.",
    ),
    "SKILL_AUTHORING_BASE_URL_NOT_ALLOWED": CatalogEntry(
        code="SKILL_AUTHORING_BASE_URL_NOT_ALLOWED",
        error_class=InvalidRequestError,
        default_message="OPENAI_BASE_URL host is not allowlisted.",
    ),
    "SKILL_AUTHORING_BASE_URL_REQUIRED": CatalogEntry(
        code="SKILL_AUTHORING_BASE_URL_REQUIRED",
        error_class=InvalidRequestError,
        default_message="Base URL is required for skill authoring.",
        user_action="fix_input",
    ),
    "SKILL_AUTHORING_SECRET_INCOMPATIBLE": CatalogEntry(
        code="SKILL_AUTHORING_SECRET_INCOMPATIBLE",
        error_class=InvalidRequestError,
        default_message="Skill authoring requires an OpenAI Responses compatible model configuration.",
    ),
    "SKILL_AUTHORING_SECRET_MISSING_KEY": CatalogEntry(
        code="SKILL_AUTHORING_SECRET_MISSING_KEY",
        error_class=InvalidRequestError,
        default_message="Secret missing OPENAI_API_KEY.",
    ),
    "SKILL_AUTHORING_SECRET_NOT_FOUND": CatalogEntry(
        code="SKILL_AUTHORING_SECRET_NOT_FOUND", error_class=NotFoundError, default_message="Secret not found."
    ),
    "SKILL_FILE_CONTENT_INVALID": CatalogEntry(
        code="SKILL_FILE_CONTENT_INVALID", error_class=InvalidRequestError, default_message="Skill file content invalid"
    ),
    "SKILL_FILE_NOT_FOUND": CatalogEntry(
        code="SKILL_FILE_NOT_FOUND", error_class=NotFoundError, default_message="Skill file not found"
    ),
    "SKILL_IMPORT_BINARY_FILE": CatalogEntry(
        code="SKILL_IMPORT_BINARY_FILE", error_class=InvalidRequestError, default_message="ZIP contains non-text files"
    ),
    "SKILL_IMPORT_FILES_INVALID": CatalogEntry(
        code="SKILL_IMPORT_FILES_INVALID", error_class=InvalidRequestError, default_message="Skill import files invalid"
    ),
    "SKILL_IMPORT_FILE_TOO_LARGE": CatalogEntry(
        code="SKILL_IMPORT_FILE_TOO_LARGE",
        error_class=InvalidRequestError,
        default_message="ZIP contains a file that is too large",
    ),
    "SKILL_IMPORT_NAME_REQUIRED": CatalogEntry(
        code="SKILL_IMPORT_NAME_REQUIRED",
        error_class=InvalidRequestError,
        default_message="SKILL.md frontmatter must include name",
    ),
    "SKILL_IMPORT_SKILL_MD_REQUIRED": CatalogEntry(
        code="SKILL_IMPORT_SKILL_MD_REQUIRED",
        error_class=InvalidRequestError,
        default_message="ZIP must contain SKILL.md at the root or inside a single top-level folder",
    ),
    "SKILL_IMPORT_TOTAL_TOO_LARGE": CatalogEntry(
        code="SKILL_IMPORT_TOTAL_TOO_LARGE",
        error_class=InvalidRequestError,
        default_message="ZIP uncompressed content is too large",
    ),
    "SKILL_IMPORT_ZIP_EMPTY": CatalogEntry(
        code="SKILL_IMPORT_ZIP_EMPTY",
        error_class=InvalidRequestError,
        default_message="ZIP does not contain any importable files",
    ),
    "SKILL_IMPORT_ZIP_INVALID": CatalogEntry(
        code="SKILL_IMPORT_ZIP_INVALID", error_class=InvalidRequestError, default_message="Invalid ZIP file"
    ),
    "SKILL_IMPORT_ZIP_ONLY": CatalogEntry(
        code="SKILL_IMPORT_ZIP_ONLY", error_class=InvalidRequestError, default_message="Only ZIP files are supported"
    ),
    "SKILL_IMPORT_ZIP_PATH_UNSAFE": CatalogEntry(
        code="SKILL_IMPORT_ZIP_PATH_UNSAFE",
        error_class=InvalidRequestError,
        default_message="ZIP contains an unsafe file path",
    ),
    "SKILL_IMPORT_ZIP_TOO_LARGE": CatalogEntry(
        code="SKILL_IMPORT_ZIP_TOO_LARGE", error_class=InvalidRequestError, default_message="ZIP file is too large"
    ),
    "SKILL_IMPORT_ZIP_TOO_MANY_FILES": CatalogEntry(
        code="SKILL_IMPORT_ZIP_TOO_MANY_FILES",
        error_class=InvalidRequestError,
        default_message="ZIP contains too many files",
    ),
    "SKILL_LIFECYCLE_INVALID_TRANSITION": CatalogEntry(
        code="SKILL_LIFECYCLE_INVALID_TRANSITION",
        error_class=InvalidRequestError,
        default_message="Skill lifecycle invalid transition",
    ),
    "SKILL_ARCHIVED": CatalogEntry(
        code="SKILL_ARCHIVED",
        error_class=ResourceConflictError,
        default_message="Skill is archived",
    ),
    "SKILL_NAME_ALREADY_EXISTS": CatalogEntry(
        code="SKILL_NAME_ALREADY_EXISTS", error_class=ResourceConflictError, default_message="Skill name already exists"
    ),
    "SKILL_NAME_INVALID": CatalogEntry(
        code="SKILL_NAME_INVALID", error_class=InvalidRequestError, default_message="Skill name invalid"
    ),
    "SKILL_NOT_FOUND": CatalogEntry(
        code="SKILL_NOT_FOUND", error_class=NotFoundError, default_message="Skill not found"
    ),
    "SKILL_OWNERSHIP_OWNER_ONLY": CatalogEntry(
        code="SKILL_OWNERSHIP_OWNER_ONLY",
        error_class=AccessDeniedError,
        default_message="Only the skill owner can transfer ownership.",
    ),
    "SKILL_PROMOTION_ALREADY_PENDING": CatalogEntry(
        code="SKILL_PROMOTION_ALREADY_PENDING",
        error_class=ResourceConflictError,
        default_message="This version is already pending review for a different tier.",
    ),
    "SKILL_PROMOTION_FOUR_EYES": CatalogEntry(
        code="SKILL_PROMOTION_FOUR_EYES",
        error_class=AccessDeniedError,
        default_message="The submitter cannot approve their own promotion.",
    ),
    "SKILL_PROMOTION_NOT_PENDING": CatalogEntry(
        code="SKILL_PROMOTION_NOT_PENDING",
        error_class=ResourceConflictError,
        default_message="This version is not pending review.",
    ),
    "SKILL_PROMOTION_OWNER_ONLY": CatalogEntry(
        code="SKILL_PROMOTION_OWNER_ONLY",
        error_class=AccessDeniedError,
        default_message="Only the organization owner can review skill promotions.",
    ),
    "SKILL_PROMOTION_SCAN_NOT_PASSED": CatalogEntry(
        code="SKILL_PROMOTION_SCAN_NOT_PASSED",
        error_class=ResourceConflictError,
        default_message="The skill's security scan has not passed; cannot promote.",
    ),
    "SKILL_PROMOTION_TARGET_MISSING": CatalogEntry(
        code="SKILL_PROMOTION_TARGET_MISSING",
        error_class=InvalidRequestError,
        default_message="A promotion target version or skill is required.",
    ),
    "SKILL_PROMOTION_TIER_INVALID": CatalogEntry(
        code="SKILL_PROMOTION_TIER_INVALID",
        error_class=InvalidRequestError,
        default_message="Invalid promotion tier.",
    ),
    "SKILL_SECURITY_BLOCKED": CatalogEntry(
        code="SKILL_SECURITY_BLOCKED",
        error_class=InvalidRequestError,
        default_message="技能存在高安全风险，已被安全扫描拦截，无法发布版本。请修复后重新扫描。",
    ),
    "SKILL_SECURITY_SCAN_ACCESS_DENIED": CatalogEntry(
        code="SKILL_SECURITY_SCAN_ACCESS_DENIED",
        error_class=AccessDeniedError,
        default_message="You don't have permission to access this scan",
    ),
    "SKILL_SECURITY_SCAN_FAILED": CatalogEntry(
        code="SKILL_SECURITY_SCAN_FAILED", error_class=InvalidRequestError, default_message="Skill security scan failed"
    ),
    "SKILL_SECURITY_SCAN_NOT_FOUND": CatalogEntry(
        code="SKILL_SECURITY_SCAN_NOT_FOUND", error_class=NotFoundError, default_message="Skill security scan not found"
    ),
    "SKILL_SECURITY_SCAN_REJECTED": CatalogEntry(
        code="SKILL_SECURITY_SCAN_REJECTED",
        error_class=InvalidRequestError,
        default_message="Skill security scan rejected this skill",
    ),
    "SKILL_SYSTEM_FILE_IMPORT_FORBIDDEN": CatalogEntry(
        code="SKILL_SYSTEM_FILE_IMPORT_FORBIDDEN",
        error_class=InvalidRequestError,
        default_message="Skill system file import forbidden",
    ),
    "SKILL_VERSION_FORMAT_INVALID": CatalogEntry(
        code="SKILL_VERSION_FORMAT_INVALID",
        error_class=InvalidRequestError,
        default_message="Skill version format invalid",
    ),
    "SKILL_VERSION_IN_USE": CatalogEntry(
        code="SKILL_VERSION_IN_USE", error_class=ResourceConflictError, default_message="Skill version is in use"
    ),
    "SKILL_VERSION_NOT_FOUND": CatalogEntry(
        code="SKILL_VERSION_NOT_FOUND", error_class=NotFoundError, default_message="Skill version not found"
    ),
    "SKILL_VERSION_NOT_GREATER_THAN_LATEST": CatalogEntry(
        code="SKILL_VERSION_NOT_GREATER_THAN_LATEST",
        error_class=InvalidRequestError,
        default_message="Skill version not greater than latest",
    ),
    "SKILL_VERSION_PRERELEASE_UNSUPPORTED": CatalogEntry(
        code="SKILL_VERSION_PRERELEASE_UNSUPPORTED",
        error_class=InvalidRequestError,
        default_message="Pre-release and build metadata are not supported",
    ),
    "SKILL_VERSION_STORED_INVALID": CatalogEntry(
        code="SKILL_VERSION_STORED_INVALID",
        error_class=InvalidRequestError,
        default_message="A stored skill version is not valid semver; cannot compute the next version.",
    ),
    "SKILL_DELETE_HAS_REFERENCES": CatalogEntry(
        code="SKILL_DELETE_HAS_REFERENCES",
        error_class=ResourceConflictError,
        default_message="Skill is still referenced by agents, cron triggers, or active tasks. Remove references before deleting.",
    ),
    "SKILL_LIFECYCLE_NOT_RUNTIME_READY": CatalogEntry(
        code="SKILL_LIFECYCLE_NOT_RUNTIME_READY",
        error_class=InvalidRequestError,
        default_message="Skill must pass security scan before entering approved state.",
    ),
    "SKILL_USAGE_FILTER_REQUIRED": CatalogEntry(
        code="SKILL_USAGE_FILTER_REQUIRED",
        error_class=InvalidRequestError,
        default_message="At least one usage filter is required.",
    ),
    "SKILL_USAGE_HASH_INVALID": CatalogEntry(
        code="SKILL_USAGE_HASH_INVALID",
        error_class=InvalidRequestError,
        default_message="Skill usage hash invalid",
    ),
    "SKILL_VERSION_NOT_RUNTIME_READY": CatalogEntry(
        code="SKILL_VERSION_NOT_RUNTIME_READY",
        error_class=InvalidRequestError,
        default_message="Skill is not runtime-ready and cannot be published.",
    ),
    "TASK_AGENT_NOT_FOUND": CatalogEntry(
        code="TASK_AGENT_NOT_FOUND", error_class=NotFoundError, default_message="Agent not found"
    ),
    "TASK_ALREADY_TERMINAL": CatalogEntry(
        code="TASK_ALREADY_TERMINAL", error_class=ResourceConflictError, default_message="Task already terminal"
    ),
    "TASK_CANCEL_CONFLICT": CatalogEntry(
        code="TASK_CANCEL_CONFLICT", error_class=ResourceConflictError, default_message="Task cancel conflict"
    ),
    "TASK_CANCEL_REDIS_RELAY_FAILED": CatalogEntry(
        code="TASK_CANCEL_REDIS_RELAY_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Failed to cancel task in sandbox runtime.",
    ),
    "TASK_CANCEL_STATE_SYNC_FAILED": CatalogEntry(
        code="TASK_CANCEL_STATE_SYNC_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Task cancel could not be finalized because task ownership changed.",
    ),
    "TASK_CANCEL_SESSION_SYNC_FAILED": CatalogEntry(
        code="TASK_CANCEL_SESSION_SYNC_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Task was cancelled, but failed to mark the linked session idle.",
    ),
    "TASK_ENQUEUE_FAILED": CatalogEntry(
        code="TASK_ENQUEUE_FAILED", error_class=ServiceUnavailableError, default_message="Failed to enqueue task"
    ),
    "TASK_ENVIRONMENT_NOT_FOUND": CatalogEntry(
        code="TASK_ENVIRONMENT_NOT_FOUND",
        error_class=RequestValidationAppError,
        default_message="Task environment not found",
    ),
    "TASK_IDEMPOTENCY_KEY_MISMATCH": CatalogEntry(
        code="TASK_IDEMPOTENCY_KEY_MISMATCH",
        error_class=ResourceConflictError,
        default_message="Task idempotency key mismatch",
    ),
    "TASK_NOT_FOUND": CatalogEntry(code="TASK_NOT_FOUND", error_class=NotFoundError, default_message="Task not found"),
    "TASK_SESSION_AGENT_MISMATCH": CatalogEntry(
        code="TASK_SESSION_AGENT_MISMATCH",
        error_class=InvalidRequestError,
        default_message="Session does not belong to the selected agent",
    ),
    "TASK_SESSION_ENVIRONMENT_MISMATCH": CatalogEntry(
        code="TASK_SESSION_ENVIRONMENT_MISMATCH",
        error_class=ResourceConflictError,
        default_message="Task environment_ref does not match the existing session environment",
    ),
    "TASK_SESSION_NOT_FOUND": CatalogEntry(
        code="TASK_SESSION_NOT_FOUND", error_class=NotFoundError, default_message="Session not found"
    ),
    "TOKEN_INVALID": CatalogEntry(
        code="TOKEN_INVALID", error_class=AuthenticationError, default_message="Invalid or expired token"
    ),
    "TOKEN_REFRESH_FAILED": CatalogEntry(
        code="TOKEN_REFRESH_FAILED",
        error_class=InternalServiceError,
        default_message="Token refresh failed. Please login again.",
    ),
    "TRIGGER_AUTH_METHODS_INVALID": CatalogEntry(
        code="TRIGGER_AUTH_METHODS_INVALID",
        error_class=RequestValidationAppError,
        default_message="Webhook auth_methods contains unsupported values",
    ),
    "TRIGGER_AUTH_METHODS_REQUIRED": CatalogEntry(
        code="TRIGGER_AUTH_METHODS_REQUIRED",
        error_class=RequestValidationAppError,
        default_message="Webhook auth_methods is required and must not be empty",
    ),
    "TRIGGER_CONCURRENCY_POLICY_INVALID": CatalogEntry(
        code="TRIGGER_CONCURRENCY_POLICY_INVALID",
        error_class=RequestValidationAppError,
        default_message="Invalid trigger concurrency policy",
    ),
    "TRIGGER_CRON_SCHEDULE_REQUIRED": CatalogEntry(
        code="TRIGGER_CRON_SCHEDULE_REQUIRED",
        error_class=RequestValidationAppError,
        default_message="Cron trigger requires exactly one of cron_expr or run_at",
    ),
    "TRIGGER_INVALID_CRON_EXPR": CatalogEntry(
        code="TRIGGER_INVALID_CRON_EXPR",
        error_class=RequestValidationAppError,
        default_message="Invalid cron expression",
    ),
    "TRIGGER_INVALID_TIMEZONE": CatalogEntry(
        code="TRIGGER_INVALID_TIMEZONE",
        error_class=RequestValidationAppError,
        default_message="Invalid trigger timezone",
    ),
    "TRIGGER_NAME_EXISTS": CatalogEntry(
        code="TRIGGER_NAME_EXISTS",
        error_class=ResourceConflictError,
        default_message="Trigger name exists",
    ),
    "TRIGGER_NOT_FOUND": CatalogEntry(
        code="TRIGGER_NOT_FOUND",
        error_class=NotFoundError,
        default_message="Trigger not found",
    ),
    "TRIGGER_NOT_WEBHOOK": CatalogEntry(
        code="TRIGGER_NOT_WEBHOOK",
        error_class=RequestValidationAppError,
        default_message="Operation is only available for webhook triggers",
    ),
    "TRIGGER_PINNED_SESSION_AGENT_MISMATCH": CatalogEntry(
        code="TRIGGER_PINNED_SESSION_AGENT_MISMATCH",
        error_class=RequestValidationAppError,
        default_message="Pinned session belongs to a different agent",
    ),
    "TRIGGER_PINNED_SESSION_NOT_FOUND": CatalogEntry(
        code="TRIGGER_PINNED_SESSION_NOT_FOUND",
        error_class=RequestValidationAppError,
        default_message="Pinned session not found",
    ),
    "TRIGGER_PINNED_SESSION_REQUIRED": CatalogEntry(
        code="TRIGGER_PINNED_SESSION_REQUIRED",
        error_class=RequestValidationAppError,
        default_message="pinned session mode requires pinned_session_id",
    ),
    "TRIGGER_RUN_AT_IN_PAST": CatalogEntry(
        code="TRIGGER_RUN_AT_IN_PAST",
        error_class=RequestValidationAppError,
        default_message="run_at must be in the future",
    ),
    "TRIGGER_RUN_AT_NOT_ALLOWED": CatalogEntry(
        code="TRIGGER_RUN_AT_NOT_ALLOWED",
        error_class=RequestValidationAppError,
        default_message="run_at is only valid for cron triggers",
    ),
    "TRIGGER_SECRET_KEY_REQUIRED": CatalogEntry(
        code="TRIGGER_SECRET_KEY_REQUIRED",
        error_class=RequestValidationAppError,
        default_message="Webhook trigger requires secret_key",
    ),
    "TRIGGER_SECRET_KEY_NOT_FOUND": CatalogEntry(
        code="TRIGGER_SECRET_KEY_NOT_FOUND",
        error_class=RequestValidationAppError,
        default_message="Trigger secret key not found",
    ),
    "TRIGGER_SECRET_NOT_FOUND": CatalogEntry(
        code="TRIGGER_SECRET_NOT_FOUND",
        error_class=NotFoundError,
        default_message="Trigger secret not found",
    ),
    "TRIGGER_SECRET_REF_REQUIRED": CatalogEntry(
        code="TRIGGER_SECRET_REF_REQUIRED",
        error_class=RequestValidationAppError,
        default_message="Webhook trigger requires secret_ref",
    ),
    "TRIGGER_SECRET_REQUIRED": CatalogEntry(
        code="TRIGGER_SECRET_REQUIRED",
        error_class=RequestValidationAppError,
        default_message="Webhook trigger requires secret_ref",
    ),
    "TRIGGER_SECRET_VALUE_BLANK": CatalogEntry(
        code="TRIGGER_SECRET_VALUE_BLANK",
        error_class=RequestValidationAppError,
        default_message="Webhook credential field must not be blank",
    ),
    "TRIGGER_SESSION_KEY_REQUIRED": CatalogEntry(
        code="TRIGGER_SESSION_KEY_REQUIRED",
        error_class=RequestValidationAppError,
        default_message="keyed session mode requires session_key",
    ),
    "TRIGGER_SESSION_MODE_INVALID": CatalogEntry(
        code="TRIGGER_SESSION_MODE_INVALID",
        error_class=RequestValidationAppError,
        default_message="Invalid trigger session mode",
    ),
    "TRIGGER_SCHEDULE_FIELD_NOT_ALLOWED": CatalogEntry(
        code="TRIGGER_SCHEDULE_FIELD_NOT_ALLOWED",
        error_class=RequestValidationAppError,
        default_message="Schedule fields are only valid for cron triggers",
    ),
    "TRIGGER_TYPE_UNSUPPORTED": CatalogEntry(
        code="TRIGGER_TYPE_UNSUPPORTED",
        error_class=RequestValidationAppError,
        default_message="Unsupported trigger type",
    ),
    "TRIGGER_WEBHOOK_UNAUTHORIZED": CatalogEntry(
        code="TRIGGER_WEBHOOK_UNAUTHORIZED",
        error_class=RequestValidationAppError,
        default_message="Invalid webhook signature or token",
    ),
    "UNAUTHORIZED": CatalogEntry(code="UNAUTHORIZED", error_class=AuthenticationError, default_message="未认证"),
    "USER_ALREADY_EXISTS": CatalogEntry(
        code="USER_ALREADY_EXISTS", error_class=InvalidRequestError, default_message="Email already registered"
    ),
    "USER_INACTIVE": CatalogEntry(
        code="USER_INACTIVE", error_class=AuthenticationError, default_message="Inactive user"
    ),
    "USER_INVALID": CatalogEntry(
        code="USER_INVALID", error_class=AuthenticationError, default_message="User not found or inactive"
    ),
    "USER_NOT_FOUND": CatalogEntry(
        code="USER_NOT_FOUND", error_class=AuthenticationError, default_message="User not found"
    ),
    "USER_TASK_LIMIT_EXCEEDED": CatalogEntry(
        code="USER_TASK_LIMIT_EXCEEDED",
        error_class=RateLimitExceededError,
        default_message="User has reached their concurrent task limit.",
        retryable=True,
        user_action="retry",
    ),
    "VERIFICATION_TOKEN_EXPIRED": CatalogEntry(
        code="VERIFICATION_TOKEN_EXPIRED",
        error_class=InvalidRequestError,
        default_message="Verification token has expired",
    ),
    "VERIFICATION_TOKEN_INVALID": CatalogEntry(
        code="VERIFICATION_TOKEN_INVALID",
        error_class=InvalidRequestError,
        default_message="Invalid or expired verification token",
    ),
    # --- Platform administration / auth ---
    "JOYSAFETER_PLATFORM_ADMIN_REQUIRED": CatalogEntry(
        code="JOYSAFETER_PLATFORM_ADMIN_REQUIRED",
        error_class=AccessDeniedError,
        default_message="Platform admin access required",
    ),
    "PLATFORM_ADMIN_SELF_REVOKE_DENIED": CatalogEntry(
        code="PLATFORM_ADMIN_SELF_REVOKE_DENIED",
        error_class=InvalidRequestError,
        default_message="You cannot revoke your own platform admin role",
    ),
    "PLATFORM_USER_NOT_FOUND": CatalogEntry(
        code="PLATFORM_USER_NOT_FOUND",
        error_class=NotFoundError,
        default_message="User not found",
    ),
    # --- Storage volumes / grants / mounts ---
    "PROJECT_SCOPE_REQUIRED": CatalogEntry(
        code="PROJECT_SCOPE_REQUIRED",
        error_class=InvalidRequestError,
        default_message="Project scope is required for storage volume access",
    ),
    "SESSION_STORAGE_MOUNT_LIMIT_EXCEEDED": CatalogEntry(
        code="SESSION_STORAGE_MOUNT_LIMIT_EXCEEDED",
        error_class=InvalidRequestError,
        default_message="Session storage mount limit exceeded",
    ),
    "STORAGE_ACCESS_DENIED": CatalogEntry(
        code="STORAGE_ACCESS_DENIED",
        error_class=InvalidRequestError,
        default_message="Grant access exceeds volume maximum access",
    ),
    "STORAGE_GRANT_NOT_FOUND": CatalogEntry(
        code="STORAGE_GRANT_NOT_FOUND",
        error_class=NotFoundError,
        default_message="Storage grant not found",
    ),
    "STORAGE_ORGANIZATION_GRANT_NOT_FOUND": CatalogEntry(
        code="STORAGE_ORGANIZATION_GRANT_NOT_FOUND",
        error_class=NotFoundError,
        default_message="Storage organization grant not found",
    ),
    "STORAGE_ORG_GRANT_REQUIRED": CatalogEntry(
        code="STORAGE_ORG_GRANT_REQUIRED",
        error_class=InvalidRequestError,
        default_message="Storage volume must be granted to the organization before granting it to a project",
    ),
    "STORAGE_PREFIX_DENIED": CatalogEntry(
        code="STORAGE_PREFIX_DENIED",
        error_class=InvalidRequestError,
        default_message="Grant allowed_prefixes exceed volume allowed prefixes",
    ),
    "STORAGE_QUOTA_DENIED": CatalogEntry(
        code="STORAGE_QUOTA_DENIED",
        error_class=InvalidRequestError,
        default_message="Grant quota exceeds volume quota",
    ),
    "STORAGE_SUB_PATH_DENIED": CatalogEntry(
        code="STORAGE_SUB_PATH_DENIED",
        error_class=InvalidRequestError,
        default_message="sub_path is outside allowed prefixes",
    ),
    "STORAGE_VOLUME_IN_USE": CatalogEntry(
        code="STORAGE_VOLUME_IN_USE",
        error_class=ResourceConflictError,
        default_message="Storage volume has active session mounts",
    ),
    "STORAGE_VOLUME_NOT_ALLOWED": CatalogEntry(
        code="STORAGE_VOLUME_NOT_ALLOWED",
        error_class=InvalidRequestError,
        default_message="Storage volume is not allowed for current project",
    ),
    "STORAGE_VOLUME_NOT_FOUND": CatalogEntry(
        code="STORAGE_VOLUME_NOT_FOUND",
        error_class=NotFoundError,
        default_message="Storage volume not found",
    ),
    "STORAGE_VOLUME_REF_EXISTS": CatalogEntry(
        code="STORAGE_VOLUME_REF_EXISTS",
        error_class=ResourceConflictError,
        default_message="Storage volume ref exists",
    ),
    # --- Triggers ---
    "TRIGGER_FIRE_IN_PROGRESS": CatalogEntry(
        code="TRIGGER_FIRE_IN_PROGRESS",
        error_class=ResourceConflictError,
        default_message="Trigger is currently being fired by the scheduler. Wait for it to finish before deleting.",
    ),
    "TRIGGER_HAS_ACTIVE_RUNS": CatalogEntry(
        code="TRIGGER_HAS_ACTIVE_RUNS",
        error_class=ResourceConflictError,
        default_message="Trigger has active runs. Cancel or wait for them before deleting the trigger.",
    ),
}


def is_registered(code: str) -> bool:
    return code in CATALOG


def entry_for(code: str) -> CatalogEntry | None:
    return CATALOG.get(code)


def all_codes() -> frozenset[str]:
    return frozenset(CATALOG)
