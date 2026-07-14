"""
Analytics API router — aggregated metrics, time series, call history,
observation trees, and agent comparison views.

All endpoints are read-only and scoped to the authenticated project.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_domain.services.analytics_service import AnalyticsService
from app.joysafeter_domain.schemas.analytics import (
    AnalyticsSummaryResponse,
    CallsTimePoint,
    TokensTimePoint,
    LatencyTimePoint,
    EngineShareItem,
    CallsListResponse,
    ObservationNodeResponse,
    AgentMetricsResponse,
    HealthCheckResponse,
    ErrorSummaryResponse,
    LatencyStatsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["joysafeter-analytics"])


# --- Summary KPIs ---


@router.get("/summary", response_model=AnalyticsSummaryResponse)
async def get_analytics_summary(
    range: str = Query("7d", alias="range"),
    engine: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> AnalyticsSummaryResponse:
    """Get aggregated KPI summary for the current project."""
    service = AnalyticsService(db)
    data = await service.get_summary(
        project_id=auth_ctx.project_id,
        range_str=range,
        engine=engine,
        model=model,
        agent_id=agent_id,
    )
    return AnalyticsSummaryResponse(**data)


# --- Time Series ---


@router.get("/timeseries", response_model=list)
async def get_analytics_timeseries(
    metric: str = Query("calls"),
    range: str = Query("7d", alias="range"),
    engine: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> list:
    """Get time-bucketed metric series."""
    service = AnalyticsService(db)
    project_id = auth_ctx.project_id

    if metric == "calls":
        data = await service.get_calls_timeseries(project_id, range, engine, agent_id)
        return [CallsTimePoint(**d) for d in data]
    elif metric == "tokens":
        data = await service.get_tokens_timeseries(project_id, range, engine, agent_id)
        return [TokensTimePoint(**d) for d in data]
    elif metric == "latency":
        data = await service.get_latency_timeseries(project_id, range, engine, agent_id)
        return [LatencyTimePoint(**d) for d in data]
    else:
        data = await service.get_calls_timeseries(project_id, range, engine, agent_id)
        return [CallsTimePoint(**d) for d in data]


# --- Engine Share ---


@router.get("/engine-share", response_model=list[EngineShareItem])
async def get_engine_share(
    range: str = Query("7d", alias="range"),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> list[EngineShareItem]:
    """Get distribution of calls by agent engine type."""
    service = AnalyticsService(db)
    data = await service.get_engine_share(auth_ctx.project_id, range)
    return [EngineShareItem(**d) for d in data]


# --- Call Records ---


@router.get("/calls", response_model=CallsListResponse)
async def get_calls_list(
    range: str = Query("7d", alias="range"),
    engine: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> CallsListResponse:
    """Get paginated list of call/trace records."""
    service = AnalyticsService(db)
    data = await service.get_calls_list(
        project_id=auth_ctx.project_id,
        range_str=range,
        engine=engine,
        model=model,
        status=status,
        agent_id=agent_id,
        page=page,
        page_size=page_size,
    )
    return CallsListResponse(**data)


# --- Observations ---


@router.get("/observations/{trace_id}", response_model=list[ObservationNodeResponse])
async def get_observations_tree(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> list[ObservationNodeResponse]:
    """Get the observation tree for a specific trace."""
    service = AnalyticsService(db)
    data = await service.get_observations_tree(auth_ctx.project_id, trace_id)

    def to_response(node: dict) -> ObservationNodeResponse:
        children = [to_response(c) for c in node.get("children", [])]
        return ObservationNodeResponse(**{**node, "children": children})

    return [to_response(n) for n in data]


# --- Agent Comparison ---


@router.get("/agent-comparison", response_model=list[AgentMetricsResponse])
async def get_agent_comparison(
    range: str = Query("7d", alias="range"),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> list[AgentMetricsResponse]:
    """Compare performance metrics across agents in the project."""
    service = AnalyticsService(db)
    data = await service.get_agent_comparison(auth_ctx.project_id, range)
    return [AgentMetricsResponse(**d) for d in data]


# --- Health Check ---


@router.get("/health-check", response_model=HealthCheckResponse)
async def get_health_check(
    range: str = Query("7d", alias="range"),
    consecutive_failures_enabled: bool = Query(True),
    consecutive_failures_threshold: int = Query(3, ge=1, le=10),
    slow_agent_enabled: bool = Query(True),
    slow_agent_threshold_ms: int = Query(10000, ge=1000, le=600000),
    token_spike_enabled: bool = Query(True),
    token_spike_threshold_pct: int = Query(30, ge=5, le=500),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> HealthCheckResponse:
    """Get system health status with alerts and token summary."""
    service = AnalyticsService(db)
    data = await service.get_health_check(
        project_id=auth_ctx.project_id,
        range_str=range,
        consecutive_failures_enabled=consecutive_failures_enabled,
        consecutive_failures_threshold=consecutive_failures_threshold,
        slow_agent_enabled=slow_agent_enabled,
        slow_agent_threshold_ms=slow_agent_threshold_ms,
        token_spike_enabled=token_spike_enabled,
        token_spike_threshold_pct=token_spike_threshold_pct,
    )
    return HealthCheckResponse(**data)


# --- Agent Ranking ---


@router.get("/agent-ranking")
async def get_agent_ranking(
    range: str = Query("7d", alias="range"),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    """Rank agents by composite health score (worst first)."""
    service = AnalyticsService(db)
    return await service.get_agent_ranking(auth_ctx.project_id, range)


# --- Time Heatmap ---


@router.get("/time-heatmap")
async def get_time_heatmap(
    range: str = Query("7d", alias="range"),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    """Get task counts by hour and day-of-week for heatmap visualization."""
    service = AnalyticsService(db)
    return await service.get_time_heatmap(auth_ctx.project_id, range)


# --- Error Summary ---


@router.get("/error-summary", response_model=ErrorSummaryResponse)
async def get_error_summary(
    range: str = Query("7d", alias="range"),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> ErrorSummaryResponse:
    """Get error distribution by status type and top error messages."""
    service = AnalyticsService(db)
    data = await service.get_error_summary(auth_ctx.project_id, range)
    return ErrorSummaryResponse(**data)


# --- Latency Stats ---


@router.get("/latency-stats", response_model=LatencyStatsResponse)
async def get_latency_stats(
    range: str = Query("7d", alias="range"),
    agent_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> LatencyStatsResponse:
    """Get P50/P95/P99 latency percentiles."""
    service = AnalyticsService(db)
    data = await service.get_latency_stats(auth_ctx.project_id, range, agent_id)
    return LatencyStatsResponse(**data)
