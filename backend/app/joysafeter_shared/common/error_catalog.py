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
    "AGENT_VERSION_CONFLICT": CatalogEntry(
        code="AGENT_VERSION_CONFLICT", error_class=ResourceConflictError, default_message="Agent version conflict"
    ),
    "API_KEY_NOT_FOUND": CatalogEntry(
        code="API_KEY_NOT_FOUND", error_class=NotFoundError, default_message="API key not found"
    ),
    "AUTH_INVALID_ASSIGNABLE_ROLE": CatalogEntry(
        code="AUTH_INVALID_ASSIGNABLE_ROLE",
        error_class=InvalidRequestError,
        default_message="Invalid role. Must be one of: admin, developer, viewer",
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
    "ENVIRONMENT_IMAGE_BUILD_FAILED": CatalogEntry(
        code="ENVIRONMENT_IMAGE_BUILD_FAILED",
        error_class=InternalServiceError,
        default_message="Environment image build failed",
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
    "JOYSAFETER_UNAUTHORIZED": CatalogEntry(
        code="JOYSAFETER_UNAUTHORIZED",
        error_class=AuthenticationError,
        default_message="凭证缺失或无效，请重新登录 / Missing or invalid credentials",
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
    "OAUTH_USERINFO_FETCH_FAILED": CatalogEntry(
        code="OAUTH_USERINFO_FETCH_FAILED",
        error_class=InvalidRequestError,
        default_message="Oauth userinfo fetch failed",
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
    "ORGANIZATION_OWNER_REMOVE_FORBIDDEN": CatalogEntry(
        code="ORGANIZATION_OWNER_REMOVE_FORBIDDEN",
        error_class=InvalidRequestError,
        default_message="Cannot remove the owner",
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
    "PROJECT_ACCESS_DENIED": CatalogEntry(
        code="PROJECT_ACCESS_DENIED", error_class=AccessDeniedError, default_message="No access to project"
    ),
    "PROJECT_ACTIVE_TASKS": CatalogEntry(
        code="PROJECT_ACTIVE_TASKS",
        error_class=ResourceConflictError,
        default_message="Project has active tasks. Stop or wait for them before archiving.",
    ),
    "PROJECT_ARCHIVED": CatalogEntry(
        code="PROJECT_ARCHIVED",
        error_class=AccessDeniedError,
        default_message="项目已归档，仅支持只读操作 / Project is archived and read-only",
    ),
    "PROJECT_DEFAULT_ARCHIVE_FORBIDDEN": CatalogEntry(
        code="PROJECT_DEFAULT_ARCHIVE_FORBIDDEN",
        error_class=InvalidRequestError,
        default_message="Cannot archive the default project",
    ),
    "PROJECT_ID_REQUIRED": CatalogEntry(
        code="PROJECT_ID_REQUIRED", error_class=NotFoundError, default_message="project_id required"
    ),
    "PROJECT_NOT_FOUND": CatalogEntry(
        code="PROJECT_NOT_FOUND", error_class=NotFoundError, default_message="Project not found"
    ),
    "QUICKSTART_BASE_URL_INVALID": CatalogEntry(
        code="QUICKSTART_BASE_URL_INVALID",
        error_class=InvalidRequestError,
        default_message="Invalid ANTHROPIC_BASE_URL",
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
    "SECRET_ACTIVE_TASK_DEPENDENCY": CatalogEntry(
        code="SECRET_ACTIVE_TASK_DEPENDENCY",
        error_class=ResourceConflictError,
        default_message="Secret active task dependency",
    ),
    "SECRET_NOT_FOUND": CatalogEntry(
        code="SECRET_NOT_FOUND", error_class=NotFoundError, default_message="Secret not found"
    ),
    "SECRET_VALIDATION_FAILED": CatalogEntry(
        code="SECRET_VALIDATION_FAILED", error_class=InvalidRequestError, default_message="Secret validation failed"
    ),
    "SECRET_VAULT_CONFIGURATION_REQUIRED": CatalogEntry(
        code="SECRET_VAULT_CONFIGURATION_REQUIRED",
        error_class=ServiceUnavailableError,
        default_message="Managed secrets require JOYSAFETER_VAULT_ENCRYPTION_KEY to be configured.",
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
    "SESSION_CUSTOM_TOOL_RESULT_DELIVERY_FAILED": CatalogEntry(
        code="SESSION_CUSTOM_TOOL_RESULT_DELIVERY_FAILED",
        error_class=ServiceUnavailableError,
        default_message="Failed to deliver custom tool result",
    ),
    "SESSION_EVENTS_EMPTY": CatalogEntry(
        code="SESSION_EVENTS_EMPTY", error_class=InvalidRequestError, default_message="No events provided"
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
    "SESSION_VAULT_ID_INVALID": CatalogEntry(
        code="SESSION_VAULT_ID_INVALID", error_class=InvalidRequestError, default_message="Session vault id invalid"
    ),
    "SESSION_VAULT_NOT_FOUND": CatalogEntry(
        code="SESSION_VAULT_NOT_FOUND", error_class=NotFoundError, default_message="Session vault not found"
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
    "SKILL_AUTHORING_SECRET_MISSING_KEY": CatalogEntry(
        code="SKILL_AUTHORING_SECRET_MISSING_KEY",
        error_class=InvalidRequestError,
        default_message="Secret missing OPENAI_API_KEY.",
    ),
    "SKILL_AUTHORING_SECRET_NOT_FOUND": CatalogEntry(
        code="SKILL_AUTHORING_SECRET_NOT_FOUND", error_class=NotFoundError, default_message="Secret not found."
    ),
    "SKILL_DELETE_FORBIDDEN": CatalogEntry(
        code="SKILL_DELETE_FORBIDDEN",
        error_class=AccessDeniedError,
        default_message="Only the owner can delete a skill",
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
    "SKILL_VISIBILITY_OWNER_ONLY": CatalogEntry(
        code="SKILL_VISIBILITY_OWNER_ONLY",
        error_class=AccessDeniedError,
        default_message="Only the skill owner can change the visibility tier. Admin collaborators may edit content but cannot retier who the skill is shared with.",
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
    "VAULT_CREDENTIAL_NOT_FOUND": CatalogEntry(
        code="VAULT_CREDENTIAL_NOT_FOUND", error_class=NotFoundError, default_message="Credential not found"
    ),
    "VAULT_NOT_FOUND": CatalogEntry(
        code="VAULT_NOT_FOUND", error_class=NotFoundError, default_message="Vault not found"
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
}


def is_registered(code: str) -> bool:
    return code in CATALOG


def entry_for(code: str) -> CatalogEntry | None:
    return CATALOG.get(code)


def all_codes() -> frozenset[str]:
    return frozenset(CATALOG)
