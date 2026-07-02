from collections.abc import Iterable as _Iterable
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar
from typing import Optional as _Optional
from typing import Union as _Union

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers

DESCRIPTOR: _descriptor.FileDescriptor

class RunnerMessage(_message.Message):
    __slots__ = ("ready", "event", "result", "heartbeat", "idle", "memory_sync")
    READY_FIELD_NUMBER: _ClassVar[int]
    EVENT_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    HEARTBEAT_FIELD_NUMBER: _ClassVar[int]
    IDLE_FIELD_NUMBER: _ClassVar[int]
    MEMORY_SYNC_FIELD_NUMBER: _ClassVar[int]
    ready: RunnerReady
    event: RunnerHarnessEvent
    result: RunnerHarnessResult
    heartbeat: RunnerHeartbeat
    idle: RunnerIdle
    memory_sync: MemoryFileSync
    def __init__(
        self,
        ready: _Optional[_Union[RunnerReady, _Mapping]] = ...,
        event: _Optional[_Union[RunnerHarnessEvent, _Mapping]] = ...,
        result: _Optional[_Union[RunnerHarnessResult, _Mapping]] = ...,
        heartbeat: _Optional[_Union[RunnerHeartbeat, _Mapping]] = ...,
        idle: _Optional[_Union[RunnerIdle, _Mapping]] = ...,
        memory_sync: _Optional[_Union[MemoryFileSync, _Mapping]] = ...,
    ) -> None: ...

class RunnerReady(_message.Message):
    __slots__ = (
        "runner_version",
        "available_providers",
        "sandbox_id",
        "is_reconnect",
        "active_task_id",
        "capabilities",
        "runner_token",
    )
    RUNNER_VERSION_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_PROVIDERS_FIELD_NUMBER: _ClassVar[int]
    SANDBOX_ID_FIELD_NUMBER: _ClassVar[int]
    IS_RECONNECT_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_TASK_ID_FIELD_NUMBER: _ClassVar[int]
    CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    RUNNER_TOKEN_FIELD_NUMBER: _ClassVar[int]
    runner_version: str
    available_providers: _containers.RepeatedScalarFieldContainer[str]
    sandbox_id: str
    is_reconnect: bool
    active_task_id: str
    capabilities: _containers.RepeatedScalarFieldContainer[str]
    runner_token: str
    def __init__(
        self,
        runner_version: _Optional[str] = ...,
        available_providers: _Optional[_Iterable[str]] = ...,
        sandbox_id: _Optional[str] = ...,
        is_reconnect: bool = ...,
        active_task_id: _Optional[str] = ...,
        capabilities: _Optional[_Iterable[str]] = ...,
        runner_token: _Optional[str] = ...,
    ) -> None: ...

class RunnerIdle(_message.Message):
    __slots__ = ("sandbox_id", "work_dir", "session_id")
    SANDBOX_ID_FIELD_NUMBER: _ClassVar[int]
    WORK_DIR_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    sandbox_id: str
    work_dir: str
    session_id: str
    def __init__(
        self, sandbox_id: _Optional[str] = ..., work_dir: _Optional[str] = ..., session_id: _Optional[str] = ...
    ) -> None: ...

class RunnerHarnessEvent(_message.Message):
    __slots__ = (
        "seq",
        "timestamp_ms",
        "text",
        "thinking",
        "tool_use",
        "tool_result",
        "error",
        "status",
        "log",
        "model_request_start",
        "model_request_end",
        "task_notification",
    )
    SEQ_FIELD_NUMBER: _ClassVar[int]
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    THINKING_FIELD_NUMBER: _ClassVar[int]
    TOOL_USE_FIELD_NUMBER: _ClassVar[int]
    TOOL_RESULT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    LOG_FIELD_NUMBER: _ClassVar[int]
    MODEL_REQUEST_START_FIELD_NUMBER: _ClassVar[int]
    MODEL_REQUEST_END_FIELD_NUMBER: _ClassVar[int]
    TASK_NOTIFICATION_FIELD_NUMBER: _ClassVar[int]
    seq: int
    timestamp_ms: int
    text: TextEvent
    thinking: ThinkingEvent
    tool_use: ToolUseEvent
    tool_result: ToolResultEvent
    error: ErrorEvent
    status: StatusEvent
    log: LogEvent
    model_request_start: ModelRequestStartEvent
    model_request_end: ModelRequestEndEvent
    task_notification: TaskNotificationEvent
    def __init__(
        self,
        seq: _Optional[int] = ...,
        timestamp_ms: _Optional[int] = ...,
        text: _Optional[_Union[TextEvent, _Mapping]] = ...,
        thinking: _Optional[_Union[ThinkingEvent, _Mapping]] = ...,
        tool_use: _Optional[_Union[ToolUseEvent, _Mapping]] = ...,
        tool_result: _Optional[_Union[ToolResultEvent, _Mapping]] = ...,
        error: _Optional[_Union[ErrorEvent, _Mapping]] = ...,
        status: _Optional[_Union[StatusEvent, _Mapping]] = ...,
        log: _Optional[_Union[LogEvent, _Mapping]] = ...,
        model_request_start: _Optional[_Union[ModelRequestStartEvent, _Mapping]] = ...,
        model_request_end: _Optional[_Union[ModelRequestEndEvent, _Mapping]] = ...,
        task_notification: _Optional[_Union[TaskNotificationEvent, _Mapping]] = ...,
    ) -> None: ...

class TextEvent(_message.Message):
    __slots__ = ("content",)
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    content: str
    def __init__(self, content: _Optional[str] = ...) -> None: ...

class ThinkingEvent(_message.Message):
    __slots__ = ("content",)
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    content: str
    def __init__(self, content: _Optional[str] = ...) -> None: ...

class ToolUseEvent(_message.Message):
    __slots__ = ("tool", "call_id", "input_json", "is_control_request")
    TOOL_FIELD_NUMBER: _ClassVar[int]
    CALL_ID_FIELD_NUMBER: _ClassVar[int]
    INPUT_JSON_FIELD_NUMBER: _ClassVar[int]
    IS_CONTROL_REQUEST_FIELD_NUMBER: _ClassVar[int]
    tool: str
    call_id: str
    input_json: str
    is_control_request: bool
    def __init__(
        self,
        tool: _Optional[str] = ...,
        call_id: _Optional[str] = ...,
        input_json: _Optional[str] = ...,
        is_control_request: bool = ...,
    ) -> None: ...

class ToolResultEvent(_message.Message):
    __slots__ = ("tool", "call_id", "output")
    TOOL_FIELD_NUMBER: _ClassVar[int]
    CALL_ID_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_FIELD_NUMBER: _ClassVar[int]
    tool: str
    call_id: str
    output: str
    def __init__(
        self, tool: _Optional[str] = ..., call_id: _Optional[str] = ..., output: _Optional[str] = ...
    ) -> None: ...

class ErrorEvent(_message.Message):
    __slots__ = ("message",)
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    message: str
    def __init__(self, message: _Optional[str] = ...) -> None: ...

class StatusEvent(_message.Message):
    __slots__ = ("state",)
    STATE_FIELD_NUMBER: _ClassVar[int]
    state: str
    def __init__(self, state: _Optional[str] = ...) -> None: ...

class LogEvent(_message.Message):
    __slots__ = ("level", "message")
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    level: str
    message: str
    def __init__(self, level: _Optional[str] = ..., message: _Optional[str] = ...) -> None: ...

class ModelRequestStartEvent(_message.Message):
    __slots__ = ("model",)
    MODEL_FIELD_NUMBER: _ClassVar[int]
    model: str
    def __init__(self, model: _Optional[str] = ...) -> None: ...

class ModelRequestEndEvent(_message.Message):
    __slots__ = ("model", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
    MODEL_FIELD_NUMBER: _ClassVar[int]
    INPUT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    CACHE_READ_TOKENS_FIELD_NUMBER: _ClassVar[int]
    CACHE_WRITE_TOKENS_FIELD_NUMBER: _ClassVar[int]
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    def __init__(
        self,
        model: _Optional[str] = ...,
        input_tokens: _Optional[int] = ...,
        output_tokens: _Optional[int] = ...,
        cache_read_tokens: _Optional[int] = ...,
        cache_write_tokens: _Optional[int] = ...,
    ) -> None: ...

class TaskNotificationEvent(_message.Message):
    __slots__ = (
        "phase",
        "task_id",
        "tool_use_id",
        "description",
        "status",
        "summary",
        "result",
        "output_file",
        "last_tool_name",
        "total_tokens",
        "tool_uses",
        "duration_ms",
    )
    PHASE_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    TOOL_USE_ID_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_FILE_FIELD_NUMBER: _ClassVar[int]
    LAST_TOOL_NAME_FIELD_NUMBER: _ClassVar[int]
    TOTAL_TOKENS_FIELD_NUMBER: _ClassVar[int]
    TOOL_USES_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    phase: str
    task_id: str
    tool_use_id: str
    description: str
    status: str
    summary: str
    result: str
    output_file: str
    last_tool_name: str
    total_tokens: int
    tool_uses: int
    duration_ms: int
    def __init__(
        self,
        phase: _Optional[str] = ...,
        task_id: _Optional[str] = ...,
        tool_use_id: _Optional[str] = ...,
        description: _Optional[str] = ...,
        status: _Optional[str] = ...,
        summary: _Optional[str] = ...,
        result: _Optional[str] = ...,
        output_file: _Optional[str] = ...,
        last_tool_name: _Optional[str] = ...,
        total_tokens: _Optional[int] = ...,
        tool_uses: _Optional[int] = ...,
        duration_ms: _Optional[int] = ...,
    ) -> None: ...

class RunnerHarnessResult(_message.Message):
    __slots__ = ("status", "output", "error", "session_id", "usage", "duration_ms", "work_dir")
    STATUS_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    USAGE_FIELD_NUMBER: _ClassVar[int]
    DURATION_MS_FIELD_NUMBER: _ClassVar[int]
    WORK_DIR_FIELD_NUMBER: _ClassVar[int]
    status: str
    output: str
    error: str
    session_id: str
    usage: TokenUsage
    duration_ms: int
    work_dir: str
    def __init__(
        self,
        status: _Optional[str] = ...,
        output: _Optional[str] = ...,
        error: _Optional[str] = ...,
        session_id: _Optional[str] = ...,
        usage: _Optional[_Union[TokenUsage, _Mapping]] = ...,
        duration_ms: _Optional[int] = ...,
        work_dir: _Optional[str] = ...,
    ) -> None: ...

class TokenUsage(_message.Message):
    __slots__ = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "by_model")
    INPUT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    CACHE_READ_TOKENS_FIELD_NUMBER: _ClassVar[int]
    CACHE_WRITE_TOKENS_FIELD_NUMBER: _ClassVar[int]
    BY_MODEL_FIELD_NUMBER: _ClassVar[int]
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    by_model: _containers.RepeatedCompositeFieldContainer[ModelUsageEntry]
    def __init__(
        self,
        input_tokens: _Optional[int] = ...,
        output_tokens: _Optional[int] = ...,
        cache_read_tokens: _Optional[int] = ...,
        cache_write_tokens: _Optional[int] = ...,
        by_model: _Optional[_Iterable[_Union[ModelUsageEntry, _Mapping]]] = ...,
    ) -> None: ...

class ModelUsageEntry(_message.Message):
    __slots__ = ("model", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
    MODEL_FIELD_NUMBER: _ClassVar[int]
    INPUT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    CACHE_READ_TOKENS_FIELD_NUMBER: _ClassVar[int]
    CACHE_WRITE_TOKENS_FIELD_NUMBER: _ClassVar[int]
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    def __init__(
        self,
        model: _Optional[str] = ...,
        input_tokens: _Optional[int] = ...,
        output_tokens: _Optional[int] = ...,
        cache_read_tokens: _Optional[int] = ...,
        cache_write_tokens: _Optional[int] = ...,
    ) -> None: ...

class RunnerHeartbeat(_message.Message):
    __slots__ = ("timestamp_ms",)
    TIMESTAMP_MS_FIELD_NUMBER: _ClassVar[int]
    timestamp_ms: int
    def __init__(self, timestamp_ms: _Optional[int] = ...) -> None: ...

class OrchestratorMessage(_message.Message):
    __slots__ = ("start", "cancel", "input", "shutdown", "setup", "memory_update")
    START_FIELD_NUMBER: _ClassVar[int]
    CANCEL_FIELD_NUMBER: _ClassVar[int]
    INPUT_FIELD_NUMBER: _ClassVar[int]
    SHUTDOWN_FIELD_NUMBER: _ClassVar[int]
    SETUP_FIELD_NUMBER: _ClassVar[int]
    MEMORY_UPDATE_FIELD_NUMBER: _ClassVar[int]
    start: StartTask
    cancel: CancelTask
    input: SendInput
    shutdown: Shutdown
    setup: SetupSandbox
    memory_update: MemoryFileUpdate
    def __init__(
        self,
        start: _Optional[_Union[StartTask, _Mapping]] = ...,
        cancel: _Optional[_Union[CancelTask, _Mapping]] = ...,
        input: _Optional[_Union[SendInput, _Mapping]] = ...,
        shutdown: _Optional[_Union[Shutdown, _Mapping]] = ...,
        setup: _Optional[_Union[SetupSandbox, _Mapping]] = ...,
        memory_update: _Optional[_Union[MemoryFileUpdate, _Mapping]] = ...,
    ) -> None: ...

class MemoryFileUpdate(_message.Message):
    __slots__ = ("store_mount_name", "relative_path", "content", "operation")
    STORE_MOUNT_NAME_FIELD_NUMBER: _ClassVar[int]
    RELATIVE_PATH_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    store_mount_name: str
    relative_path: str
    content: bytes
    operation: str
    def __init__(
        self,
        store_mount_name: _Optional[str] = ...,
        relative_path: _Optional[str] = ...,
        content: _Optional[bytes] = ...,
        operation: _Optional[str] = ...,
    ) -> None: ...

class SetupSandbox(_message.Message):
    __slots__ = (
        "skills",
        "mcp_servers",
        "custom_tools",
        "setup_commands",
        "work_dir",
        "env",
        "secrets",
        "permission_mode",
        "provider",
        "model",
        "memory_system_prompt",
        "memory_mounts",
        "files",
        "file_refs",
        "allowed_tools",
        "disallowed_tools",
        "ask_tools",
        "repos",
    )
    class EnvEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...

    class SecretsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...

    SKILLS_FIELD_NUMBER: _ClassVar[int]
    MCP_SERVERS_FIELD_NUMBER: _ClassVar[int]
    CUSTOM_TOOLS_FIELD_NUMBER: _ClassVar[int]
    SETUP_COMMANDS_FIELD_NUMBER: _ClassVar[int]
    WORK_DIR_FIELD_NUMBER: _ClassVar[int]
    ENV_FIELD_NUMBER: _ClassVar[int]
    SECRETS_FIELD_NUMBER: _ClassVar[int]
    PERMISSION_MODE_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    MEMORY_SYSTEM_PROMPT_FIELD_NUMBER: _ClassVar[int]
    MEMORY_MOUNTS_FIELD_NUMBER: _ClassVar[int]
    FILES_FIELD_NUMBER: _ClassVar[int]
    FILE_REFS_FIELD_NUMBER: _ClassVar[int]
    ALLOWED_TOOLS_FIELD_NUMBER: _ClassVar[int]
    DISALLOWED_TOOLS_FIELD_NUMBER: _ClassVar[int]
    ASK_TOOLS_FIELD_NUMBER: _ClassVar[int]
    REPOS_FIELD_NUMBER: _ClassVar[int]
    skills: _containers.RepeatedCompositeFieldContainer[SkillArchive]
    mcp_servers: _containers.RepeatedCompositeFieldContainer[McpConfig]
    custom_tools: _containers.RepeatedCompositeFieldContainer[CustomTool]
    setup_commands: _containers.RepeatedScalarFieldContainer[str]
    work_dir: str
    env: _containers.ScalarMap[str, str]
    secrets: _containers.ScalarMap[str, str]
    permission_mode: str
    provider: str
    model: str
    memory_system_prompt: str
    memory_mounts: _containers.RepeatedCompositeFieldContainer[MemoryStoreMount]
    files: _containers.RepeatedCompositeFieldContainer[FileMount]
    file_refs: _containers.RepeatedCompositeFieldContainer[FileRef]
    allowed_tools: _containers.RepeatedScalarFieldContainer[str]
    disallowed_tools: _containers.RepeatedScalarFieldContainer[str]
    ask_tools: _containers.RepeatedScalarFieldContainer[str]
    repos: _containers.RepeatedCompositeFieldContainer[RepoConfig]
    def __init__(
        self,
        skills: _Optional[_Iterable[_Union[SkillArchive, _Mapping]]] = ...,
        mcp_servers: _Optional[_Iterable[_Union[McpConfig, _Mapping]]] = ...,
        custom_tools: _Optional[_Iterable[_Union[CustomTool, _Mapping]]] = ...,
        setup_commands: _Optional[_Iterable[str]] = ...,
        work_dir: _Optional[str] = ...,
        env: _Optional[_Mapping[str, str]] = ...,
        secrets: _Optional[_Mapping[str, str]] = ...,
        permission_mode: _Optional[str] = ...,
        provider: _Optional[str] = ...,
        model: _Optional[str] = ...,
        memory_system_prompt: _Optional[str] = ...,
        memory_mounts: _Optional[_Iterable[_Union[MemoryStoreMount, _Mapping]]] = ...,
        files: _Optional[_Iterable[_Union[FileMount, _Mapping]]] = ...,
        file_refs: _Optional[_Iterable[_Union[FileRef, _Mapping]]] = ...,
        allowed_tools: _Optional[_Iterable[str]] = ...,
        disallowed_tools: _Optional[_Iterable[str]] = ...,
        ask_tools: _Optional[_Iterable[str]] = ...,
        repos: _Optional[_Iterable[_Union[RepoConfig, _Mapping]]] = ...,
    ) -> None: ...

class MemoryStoreMount(_message.Message):
    __slots__ = ("store_id", "mount_name", "mount_path", "access", "files")
    STORE_ID_FIELD_NUMBER: _ClassVar[int]
    MOUNT_NAME_FIELD_NUMBER: _ClassVar[int]
    MOUNT_PATH_FIELD_NUMBER: _ClassVar[int]
    ACCESS_FIELD_NUMBER: _ClassVar[int]
    FILES_FIELD_NUMBER: _ClassVar[int]
    store_id: str
    mount_name: str
    mount_path: str
    access: str
    files: _containers.RepeatedCompositeFieldContainer[MemoryFile]
    def __init__(
        self,
        store_id: _Optional[str] = ...,
        mount_name: _Optional[str] = ...,
        mount_path: _Optional[str] = ...,
        access: _Optional[str] = ...,
        files: _Optional[_Iterable[_Union[MemoryFile, _Mapping]]] = ...,
    ) -> None: ...

class MemoryFile(_message.Message):
    __slots__ = ("relative_path", "content")
    RELATIVE_PATH_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    relative_path: str
    content: bytes
    def __init__(self, relative_path: _Optional[str] = ..., content: _Optional[bytes] = ...) -> None: ...

class MemoryFileSync(_message.Message):
    __slots__ = ("store_mount_name", "relative_path", "content", "operation")
    STORE_MOUNT_NAME_FIELD_NUMBER: _ClassVar[int]
    RELATIVE_PATH_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    OPERATION_FIELD_NUMBER: _ClassVar[int]
    store_mount_name: str
    relative_path: str
    content: str
    operation: str
    def __init__(
        self,
        store_mount_name: _Optional[str] = ...,
        relative_path: _Optional[str] = ...,
        content: _Optional[str] = ...,
        operation: _Optional[str] = ...,
    ) -> None: ...

class StartTask(_message.Message):
    __slots__ = (
        "task_id",
        "provider",
        "prompt",
        "system_prompt",
        "session_id",
        "model",
        "max_turns",
        "timeout_seconds",
        "env",
        "secrets",
        "mcp_servers",
        "repos",
        "work_dir",
        "skills",
        "allowed_tools",
        "disallowed_tools",
        "permission_mode",
        "setup_commands",
        "custom_tools",
        "ask_tools",
    )
    class EnvEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...

    class SecretsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...

    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    PROVIDER_FIELD_NUMBER: _ClassVar[int]
    PROMPT_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_PROMPT_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    MAX_TURNS_FIELD_NUMBER: _ClassVar[int]
    TIMEOUT_SECONDS_FIELD_NUMBER: _ClassVar[int]
    ENV_FIELD_NUMBER: _ClassVar[int]
    SECRETS_FIELD_NUMBER: _ClassVar[int]
    MCP_SERVERS_FIELD_NUMBER: _ClassVar[int]
    REPOS_FIELD_NUMBER: _ClassVar[int]
    WORK_DIR_FIELD_NUMBER: _ClassVar[int]
    SKILLS_FIELD_NUMBER: _ClassVar[int]
    ALLOWED_TOOLS_FIELD_NUMBER: _ClassVar[int]
    DISALLOWED_TOOLS_FIELD_NUMBER: _ClassVar[int]
    PERMISSION_MODE_FIELD_NUMBER: _ClassVar[int]
    SETUP_COMMANDS_FIELD_NUMBER: _ClassVar[int]
    CUSTOM_TOOLS_FIELD_NUMBER: _ClassVar[int]
    ASK_TOOLS_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    provider: str
    prompt: str
    system_prompt: str
    session_id: str
    model: str
    max_turns: int
    timeout_seconds: int
    env: _containers.ScalarMap[str, str]
    secrets: _containers.ScalarMap[str, str]
    mcp_servers: _containers.RepeatedCompositeFieldContainer[McpConfig]
    repos: _containers.RepeatedCompositeFieldContainer[RepoConfig]
    work_dir: str
    skills: _containers.RepeatedCompositeFieldContainer[SkillArchive]
    allowed_tools: _containers.RepeatedScalarFieldContainer[str]
    disallowed_tools: _containers.RepeatedScalarFieldContainer[str]
    permission_mode: str
    setup_commands: _containers.RepeatedScalarFieldContainer[str]
    custom_tools: _containers.RepeatedCompositeFieldContainer[CustomTool]
    ask_tools: _containers.RepeatedScalarFieldContainer[str]
    def __init__(
        self,
        task_id: _Optional[str] = ...,
        provider: _Optional[str] = ...,
        prompt: _Optional[str] = ...,
        system_prompt: _Optional[str] = ...,
        session_id: _Optional[str] = ...,
        model: _Optional[str] = ...,
        max_turns: _Optional[int] = ...,
        timeout_seconds: _Optional[int] = ...,
        env: _Optional[_Mapping[str, str]] = ...,
        secrets: _Optional[_Mapping[str, str]] = ...,
        mcp_servers: _Optional[_Iterable[_Union[McpConfig, _Mapping]]] = ...,
        repos: _Optional[_Iterable[_Union[RepoConfig, _Mapping]]] = ...,
        work_dir: _Optional[str] = ...,
        skills: _Optional[_Iterable[_Union[SkillArchive, _Mapping]]] = ...,
        allowed_tools: _Optional[_Iterable[str]] = ...,
        disallowed_tools: _Optional[_Iterable[str]] = ...,
        permission_mode: _Optional[str] = ...,
        setup_commands: _Optional[_Iterable[str]] = ...,
        custom_tools: _Optional[_Iterable[_Union[CustomTool, _Mapping]]] = ...,
        ask_tools: _Optional[_Iterable[str]] = ...,
    ) -> None: ...

class CustomTool(_message.Message):
    __slots__ = ("name", "description", "input_schema_json")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    INPUT_SCHEMA_JSON_FIELD_NUMBER: _ClassVar[int]
    name: str
    description: str
    input_schema_json: str
    def __init__(
        self, name: _Optional[str] = ..., description: _Optional[str] = ..., input_schema_json: _Optional[str] = ...
    ) -> None: ...

class SkillArchive(_message.Message):
    __slots__ = ("name", "tar_gz", "target")
    NAME_FIELD_NUMBER: _ClassVar[int]
    TAR_GZ_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    name: str
    tar_gz: bytes
    target: str
    def __init__(
        self, name: _Optional[str] = ..., tar_gz: _Optional[bytes] = ..., target: _Optional[str] = ...
    ) -> None: ...

class FileMount(_message.Message):
    __slots__ = ("path", "content", "filename")
    PATH_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    path: str
    content: bytes
    filename: str
    def __init__(
        self, path: _Optional[str] = ..., content: _Optional[bytes] = ..., filename: _Optional[str] = ...
    ) -> None: ...

class FileRef(_message.Message):
    __slots__ = ("path", "url", "filename", "size_bytes")
    PATH_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    path: str
    url: str
    filename: str
    size_bytes: int
    def __init__(
        self,
        path: _Optional[str] = ...,
        url: _Optional[str] = ...,
        filename: _Optional[str] = ...,
        size_bytes: _Optional[int] = ...,
    ) -> None: ...

class McpConfig(_message.Message):
    __slots__ = ("name", "command", "args", "env", "server_type", "url", "headers")
    class EnvEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...

    class HeadersEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...

    NAME_FIELD_NUMBER: _ClassVar[int]
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    ENV_FIELD_NUMBER: _ClassVar[int]
    SERVER_TYPE_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    HEADERS_FIELD_NUMBER: _ClassVar[int]
    name: str
    command: str
    args: _containers.RepeatedScalarFieldContainer[str]
    env: _containers.ScalarMap[str, str]
    server_type: str
    url: str
    headers: _containers.ScalarMap[str, str]
    def __init__(
        self,
        name: _Optional[str] = ...,
        command: _Optional[str] = ...,
        args: _Optional[_Iterable[str]] = ...,
        env: _Optional[_Mapping[str, str]] = ...,
        server_type: _Optional[str] = ...,
        url: _Optional[str] = ...,
        headers: _Optional[_Mapping[str, str]] = ...,
    ) -> None: ...

class RepoConfig(_message.Message):
    __slots__ = ("url", "branch", "path", "authorization_token", "mount_name")
    URL_FIELD_NUMBER: _ClassVar[int]
    BRANCH_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    AUTHORIZATION_TOKEN_FIELD_NUMBER: _ClassVar[int]
    MOUNT_NAME_FIELD_NUMBER: _ClassVar[int]
    url: str
    branch: str
    path: str
    authorization_token: str
    mount_name: str
    def __init__(
        self,
        url: _Optional[str] = ...,
        branch: _Optional[str] = ...,
        path: _Optional[str] = ...,
        authorization_token: _Optional[str] = ...,
        mount_name: _Optional[str] = ...,
    ) -> None: ...

class CancelTask(_message.Message):
    __slots__ = ("reason",)
    REASON_FIELD_NUMBER: _ClassVar[int]
    reason: str
    def __init__(self, reason: _Optional[str] = ...) -> None: ...

class SendInput(_message.Message):
    __slots__ = ("content",)
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    content: str
    def __init__(self, content: _Optional[str] = ...) -> None: ...

class Shutdown(_message.Message):
    __slots__ = ("reason",)
    REASON_FIELD_NUMBER: _ClassVar[int]
    reason: str
    def __init__(self, reason: _Optional[str] = ...) -> None: ...
