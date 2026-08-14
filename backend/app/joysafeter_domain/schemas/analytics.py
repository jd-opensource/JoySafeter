"""
Pydantic response schemas for the analytics API.
"""

from typing import Optional

from pydantic import BaseModel, field_serializer

from app.joysafeter_shared.ids import AgentId, SessionId, TaskId

# --- KPI Summary ---


class AnalyticsDelta(BaseModel):
    total_calls: Optional[float] = None
    success_rate: Optional[float] = None
    avg_duration_ms: Optional[float] = None
    avg_ttft_ms: Optional[float] = None
    total_tokens: Optional[float] = None
    total_cost: Optional[float] = None
    error_count: Optional[float] = None
    active_sessions: Optional[float] = None


class AnalyticsSummaryResponse(BaseModel):
    total_calls: int
    success_rate: float
    avg_duration_ms: float
    avg_ttft_ms: float
    total_tokens: int
    total_cost: float
    error_count: int
    active_sessions: int
    avg_agent_steps: float
    delta: AnalyticsDelta
    cache_read_tokens: int = 0
    cache_hit_rate: float = 0.0
    running_tasks: int = 0


# --- Time Series ---


class CallsTimePoint(BaseModel):
    timestamp: str
    total_calls: int
    error_calls: int
    success_calls: int


class TokensTimePoint(BaseModel):
    timestamp: str
    input_tokens: int
    output_tokens: int


class LatencyTimePoint(BaseModel):
    timestamp: str
    avg_duration_ms: float
    avg_ttft_ms: float


# --- Engine Share ---


class EngineShareItem(BaseModel):
    engine: str
    count: int
    percentage: float


# --- Call Records ---


class CallRecord(BaseModel):
    id: TaskId
    trace_id: TaskId
    session_id: Optional[SessionId] = None
    agent_id: Optional[AgentId] = None
    agent_name: Optional[str] = None
    engine_kind: Optional[str] = None
    model: Optional[str] = None
    status: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    ttft_ms: Optional[float] = None
    duration_ms: int = 0
    cost: float = 0.0
    agent_steps: int = 0
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    retry_count: int = 0
    queue_wait_ms: int = 0

    @field_serializer("id", "trace_id")
    def serialize_task_id(self, value: TaskId) -> str:
        # ``model_dump()`` (Python mode) is part of this schema's contract, but the
        # typed-id core serializer only fires in JSON mode; mirror the sibling id
        # fields so the canonical prefix is emitted in both modes.
        return str(value)

    @field_serializer("session_id")
    def serialize_session_id(self, value: Optional[SessionId]) -> Optional[str]:
        # ``model_dump()`` (Python mode) is part of this schema's contract, but the
        # typed-id core serializer only fires in JSON mode; mirror the sibling id
        # fields so the canonical prefix is emitted in both modes.
        return str(value) if value is not None else None

    @field_serializer("agent_id")
    def serialize_agent_id(self, value: Optional[AgentId]) -> Optional[str]:
        # ``model_dump()`` (Python mode) is part of this schema's contract, but the
        # typed-id core serializer only fires in JSON mode; mirror the sibling id
        # fields so the canonical prefix is emitted in both modes.
        return str(value) if value is not None else None


class CallsListResponse(BaseModel):
    data: list[CallRecord]
    has_more: bool
    total: int


# --- Observations (Waterfall) ---


class ObservationNodeResponse(BaseModel):
    id: str
    parent_id: Optional[str] = None
    type: str
    level: str
    name: Optional[str] = None
    model: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    completion_start_time: Optional[str] = None
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    tool_calls: Optional[list] = None
    children: list["ObservationNodeResponse"] = []


# --- Agent Comparison ---


class AgentMetricsResponse(BaseModel):
    agent_id: AgentId
    agent_name: str
    engine_kind: Optional[str] = None
    total_sessions: int = 0
    total_tasks: int = 0
    success_rate: float = 0.0
    avg_duration_ms: float = 0.0
    avg_ttft_ms: float = 0.0
    avg_cost: float = 0.0
    total_tokens: int = 0
    avg_agent_steps: float = 0.0

    @field_serializer("agent_id")
    def serialize_agent_id(self, value: AgentId) -> str:
        return str(value)


# --- Health Check ---


class AlertItem(BaseModel):
    # Machine-only contract: ``type`` identifies the anomaly and ``params`` carries
    # the numeric values. All human-facing, localized copy lives in the frontend
    # i18n locales (analytics.alerts.detail.*) — never baked into the backend.
    type: str  # consecutive_failures, slow_agent, token_spike, high_retries, zombie_session
    severity: str  # error, warning, info
    agent_name: Optional[str] = None
    agent_id: Optional[AgentId] = None
    params: dict[str, float] = {}

    @field_serializer("agent_id")
    def serialize_agent_id(self, value: Optional[AgentId]) -> Optional[str]:
        return str(value) if value is not None else None


class AgentRankingItem(BaseModel):
    agent_id: AgentId
    agent_name: str
    engine_kind: Optional[str] = None
    total_tasks: int
    success_rate: float
    failed_count: int
    avg_duration_ms: float
    total_tokens: int
    last_task_at: Optional[str] = None
    activity_status: str

    @field_serializer("agent_id")
    def serialize_agent_id(self, value: AgentId) -> str:
        return str(value)


class TokenSummary(BaseModel):
    total: int
    input: int
    output: int
    cache_read: int
    cache_hit_rate: float


class SuggestionItem(BaseModel):
    # Machine-only contract (see AlertItem). Localized copy lives in the frontend
    # i18n locales (analytics.tokenSummary.suggestionMessages.*).
    type: str  # low_cache_hit, high_output_ratio, high_queue_wait
    params: dict[str, float] = {}


class QueueWaitInfo(BaseModel):
    avg_sec: float = 0.0
    max_sec: float = 0.0


class HealthCheckResponse(BaseModel):
    status: str  # healthy, warning, critical
    success_rate: float
    running_tasks: int
    last_error_at: Optional[str] = None
    alerts: list[AlertItem]
    token_summary: TokenSummary
    suggestions: list[SuggestionItem] = []
    queue_wait: QueueWaitInfo = QueueWaitInfo()


# --- Error Summary ---


class ErrorStatusBreakdown(BaseModel):
    status: str
    count: int


class ErrorMessageItem(BaseModel):
    message: str
    count: int


class ErrorSummaryResponse(BaseModel):
    total_errors: int
    status_breakdown: list[ErrorStatusBreakdown]
    top_errors: list[ErrorMessageItem]


# --- Latency Stats ---


class DurationBucket(BaseModel):
    label: str
    count: int
    pct: float
    color: str


class LatencyStatsResponse(BaseModel):
    total_calls: int
    buckets: list[DurationBucket] = []
