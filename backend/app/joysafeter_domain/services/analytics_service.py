"""
Analytics service — aggregation queries against sessions, tasks, and session_events.
All queries are scoped by project_id for multi-tenancy.

This service queries the durable product tables:
- joysafeter_sessions (usage, duration, status)
- joysafeter_session_events (event_type, payload with token/model info)
- joysafeter_tasks (status, duration_ms, usage, agent_id)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import Integer, and_, case, cast, desc, func, text, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_shared.ids import AgentId, ProjectId

logger = logging.getLogger(__name__)


def _get_time_boundary(range_str: str) -> Optional[datetime]:
    """Convert a range string to a datetime boundary."""
    now = datetime.now(timezone.utc)
    mapping = {
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
    }
    delta = mapping.get(range_str)
    if delta is None:
        return None  # "all" — no time filter
    return now - delta


def _get_bucket_interval(range_str: str) -> str:
    """Get the PostgreSQL date_trunc interval for a given range."""
    if range_str == "24h":
        return "hour"
    return "day"


class AnalyticsService:
    """Provides aggregated analytics data from existing JoySafeter tables."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Summary KPIs (from tasks + sessions)
    # ------------------------------------------------------------------

    async def get_summary(
        self,
        project_id: ProjectId | None,
        range_str: str = "7d",
        engine: Optional[str] = None,
        model: Optional[str] = None,
        agent_id: Optional[AgentId] = None,
    ) -> dict:
        """Aggregate summary KPIs from tasks within the time range."""
        time_boundary = _get_time_boundary(range_str)

        # Task-based metrics
        filters = [JoySafeterTask.project_id == project_id]
        if time_boundary:
            filters.append(JoySafeterTask.created_at >= time_boundary)
        if agent_id:
            filters.append(JoySafeterTask.agent_id == agent_id)

        stmt = select(
            func.count(JoySafeterTask.id).label("total_calls"),
            func.avg(JoySafeterTask.duration_ms).label("avg_duration_ms"),
            func.count(case((JoySafeterTask.status == JoySafeterTaskStatus.FAILED.value, 1))).label("error_count"),
            func.count(case((JoySafeterTask.status == JoySafeterTaskStatus.COMPLETED.value, 1))).label(
                "completed_count"
            ),
        ).where(and_(*filters))

        result = await self.db.execute(stmt)
        row = result.one()

        total_calls = row.total_calls or 0
        error_count = row.error_count or 0
        success_rate = (total_calls - error_count) / total_calls if total_calls > 0 else 0.0
        avg_duration_ms = float(row.avg_duration_ms or 0)

        # Token usage from sessions (JSONB 'usage' field)
        session_filters = [JoySafeterSession.project_id == project_id]
        if time_boundary:
            session_filters.append(JoySafeterSession.created_at >= time_boundary)
        if agent_id:
            session_filters.append(JoySafeterSession.agent_id == agent_id)

        token_stmt = select(
            func.sum(
                func.coalesce(cast(func.jsonb_extract_path_text(JoySafeterSession.usage, "input_tokens"), Integer), 0)
                + func.coalesce(
                    cast(func.jsonb_extract_path_text(JoySafeterSession.usage, "output_tokens"), Integer), 0
                )
            ).label("total_tokens"),
            func.sum(
                func.coalesce(
                    cast(func.jsonb_extract_path_text(JoySafeterSession.usage, "cache_read_input_tokens"), Integer), 0
                )
            ).label("cache_read_tokens"),
            func.sum(
                func.coalesce(cast(func.jsonb_extract_path_text(JoySafeterSession.usage, "input_tokens"), Integer), 0)
            ).label("input_tokens"),
        ).where(and_(*session_filters))

        token_result = await self.db.execute(token_stmt)
        token_row = token_result.one()
        total_tokens = int(token_row.total_tokens or 0)
        cache_read_tokens = int(token_row.cache_read_tokens or 0)
        input_tokens = int(token_row.input_tokens or 0)
        cache_hit_rate = (
            cache_read_tokens / (input_tokens + cache_read_tokens) if (input_tokens + cache_read_tokens) > 0 else 0.0
        )

        # Active sessions
        active_stmt = select(func.count(JoySafeterSession.id)).where(
            and_(
                JoySafeterSession.project_id == project_id,
                JoySafeterSession.status == "running",
            )
        )
        active_sessions = (await self.db.execute(active_stmt)).scalar() or 0

        # Running sessions (sessions stay "running" while tasks execute)
        running_stmt = select(func.count(JoySafeterSession.id)).where(
            and_(
                JoySafeterSession.project_id == project_id,
                JoySafeterSession.status == "running",
            )
        )
        running_tasks = (await self.db.execute(running_stmt)).scalar() or 0

        # Delta computation
        delta = await self._compute_delta(
            project_id,
            range_str,
            total_calls,
            success_rate,
            avg_duration_ms,
            0.0,
            total_tokens,
            0.0,
            error_count,
            active_sessions,
        )

        return {
            "total_calls": total_calls,
            "success_rate": round(success_rate, 3),
            "avg_duration_ms": round(avg_duration_ms, 1),
            "avg_ttft_ms": 0.0,  # TTFT not available without traces table
            "total_tokens": total_tokens,
            "total_cost": 0.0,  # Cost not tracked in tasks table
            "error_count": error_count,
            "active_sessions": active_sessions,
            "avg_agent_steps": 0.0,
            "delta": delta,
            "cache_read_tokens": cache_read_tokens,
            "cache_hit_rate": round(cache_hit_rate, 3),
            "running_tasks": running_tasks,
        }

    async def _compute_delta(
        self,
        project_id: ProjectId | None,
        range_str: str,
        curr_calls: int,
        curr_success_rate: float,
        curr_duration: float,
        curr_ttft: float,
        curr_tokens: int,
        curr_cost: float,
        curr_errors: int,
        curr_active: int,
    ) -> dict:
        """Compute deltas by comparing with the previous equivalent period."""
        time_boundary = _get_time_boundary(range_str)
        if time_boundary is None:
            return {
                "total_calls": None,
                "success_rate": None,
                "avg_duration_ms": None,
                "avg_ttft_ms": None,
                "total_tokens": None,
                "total_cost": None,
                "error_count": None,
                "active_sessions": None,
            }

        now = datetime.now(timezone.utc)
        period_length = now - time_boundary
        prev_end = time_boundary
        prev_start = prev_end - period_length

        filters = [
            JoySafeterTask.project_id == project_id,
            JoySafeterTask.created_at >= prev_start,
            JoySafeterTask.created_at < prev_end,
        ]

        stmt = select(
            func.count(JoySafeterTask.id).label("total_calls"),
            func.avg(JoySafeterTask.duration_ms).label("avg_duration_ms"),
            func.count(case((JoySafeterTask.status == JoySafeterTaskStatus.FAILED.value, 1))).label("error_count"),
        ).where(and_(*filters))

        result = await self.db.execute(stmt)
        row = result.one()

        prev_calls = row.total_calls or 0
        prev_errors = row.error_count or 0
        prev_success = (prev_calls - prev_errors) / prev_calls if prev_calls > 0 else 0

        def pct_change(curr, prev):
            if prev == 0:
                return None
            return round((curr - prev) / prev, 3)

        return {
            "total_calls": pct_change(curr_calls, prev_calls),
            "success_rate": pct_change(curr_success_rate, prev_success) if prev_success else None,
            "avg_duration_ms": pct_change(curr_duration, float(row.avg_duration_ms or 0))
            if row.avg_duration_ms
            else None,
            "avg_ttft_ms": None,
            "total_tokens": None,
            "total_cost": None,
            "error_count": pct_change(curr_errors, prev_errors) if prev_errors else None,
            "active_sessions": None,
        }

    # ------------------------------------------------------------------
    # Time Series (from tasks)
    # ------------------------------------------------------------------

    async def get_calls_timeseries(
        self,
        project_id: ProjectId | None,
        range_str: str = "7d",
        engine: Optional[str] = None,
        agent_id: Optional[AgentId] = None,
    ) -> list[dict]:
        """Task completions over time, bucketed."""
        time_boundary = _get_time_boundary(range_str)
        bucket = _get_bucket_interval(range_str)

        filters = [JoySafeterTask.project_id == project_id]
        if time_boundary:
            filters.append(JoySafeterTask.created_at >= time_boundary)
        if agent_id:
            filters.append(JoySafeterTask.agent_id == agent_id)

        stmt = (
            select(
                func.date_trunc(bucket, JoySafeterTask.created_at).label("ts"),
                func.count(JoySafeterTask.id).label("total_calls"),
                func.count(case((JoySafeterTask.status == JoySafeterTaskStatus.FAILED.value, 1))).label("error_calls"),
            )
            .where(and_(*filters))
            .group_by(text("ts"))
            .order_by(text("ts"))
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            {
                "timestamp": row.ts.isoformat() if row.ts else "",
                "total_calls": row.total_calls,
                "error_calls": row.error_calls,
                "success_calls": row.total_calls - row.error_calls,
            }
            for row in rows
        ]

    async def get_tokens_timeseries(
        self,
        project_id: ProjectId | None,
        range_str: str = "7d",
        engine: Optional[str] = None,
        agent_id: Optional[AgentId] = None,
    ) -> list[dict]:
        """Token usage over time from sessions, bucketed."""
        time_boundary = _get_time_boundary(range_str)
        bucket = _get_bucket_interval(range_str)

        filters = [JoySafeterSession.project_id == project_id]
        if time_boundary:
            filters.append(JoySafeterSession.created_at >= time_boundary)
        if agent_id:
            filters.append(JoySafeterSession.agent_id == agent_id)

        stmt = (
            select(
                func.date_trunc(bucket, JoySafeterSession.created_at).label("ts"),
                func.sum(
                    func.coalesce(
                        cast(func.jsonb_extract_path_text(JoySafeterSession.usage, "input_tokens"), Integer), 0
                    )
                ).label("input_tokens"),
                func.sum(
                    func.coalesce(
                        cast(func.jsonb_extract_path_text(JoySafeterSession.usage, "output_tokens"), Integer), 0
                    )
                ).label("output_tokens"),
            )
            .where(and_(*filters))
            .group_by(text("ts"))
            .order_by(text("ts"))
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            {
                "timestamp": row.ts.isoformat() if row.ts else "",
                "input_tokens": int(row.input_tokens or 0),
                "output_tokens": int(row.output_tokens or 0),
            }
            for row in rows
        ]

    async def get_latency_timeseries(
        self,
        project_id: ProjectId | None,
        range_str: str = "7d",
        engine: Optional[str] = None,
        agent_id: Optional[AgentId] = None,
    ) -> list[dict]:
        """Latency (task duration) over time, bucketed."""
        time_boundary = _get_time_boundary(range_str)
        bucket = _get_bucket_interval(range_str)

        filters = [
            JoySafeterTask.project_id == project_id,
            JoySafeterTask.duration_ms.isnot(None),
        ]
        if time_boundary:
            filters.append(JoySafeterTask.created_at >= time_boundary)
        if agent_id:
            filters.append(JoySafeterTask.agent_id == agent_id)

        stmt = (
            select(
                func.date_trunc(bucket, JoySafeterTask.created_at).label("ts"),
                func.avg(JoySafeterTask.duration_ms).label("avg_duration_ms"),
            )
            .where(and_(*filters))
            .group_by(text("ts"))
            .order_by(text("ts"))
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            {
                "timestamp": row.ts.isoformat() if row.ts else "",
                "avg_duration_ms": round(float(row.avg_duration_ms or 0), 1),
                "avg_ttft_ms": 0.0,  # TTFT not available
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Engine Share (from agents joined with tasks)
    # ------------------------------------------------------------------

    async def get_engine_share(
        self,
        project_id: ProjectId | None,
        range_str: str = "7d",
    ) -> list[dict]:
        """Distribution of tasks by agent engine_kind."""
        time_boundary = _get_time_boundary(range_str)

        filters = [JoySafeterTask.project_id == project_id]
        if time_boundary:
            filters.append(JoySafeterTask.created_at >= time_boundary)

        stmt = (
            select(
                func.coalesce(JoySafeterAgent.engine_kind, "unknown").label("engine"),
                func.count(JoySafeterTask.id).label("count"),
            )
            .select_from(JoySafeterTask)
            .outerjoin(JoySafeterAgent, JoySafeterTask.agent_id == JoySafeterAgent.id)
            .where(and_(*filters))
            .group_by(text("engine"))
            .order_by(desc("count"))
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        total = sum(int(count) for _engine, count in rows) or 1
        return [
            {
                "engine": engine or "unknown",
                "count": count,
                "percentage": round(count / total * 100, 1),
            }
            for engine, count in rows
        ]

    # ------------------------------------------------------------------
    # Call Records (from tasks, paginated)
    # ------------------------------------------------------------------

    async def get_calls_list(
        self,
        project_id: ProjectId | None,
        range_str: str = "7d",
        engine: Optional[str] = None,
        model: Optional[str] = None,
        status: Optional[str] = None,
        agent_id: Optional[AgentId] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> dict:
        """Paginated list of task records."""
        time_boundary = _get_time_boundary(range_str)

        filters = [JoySafeterTask.project_id == project_id]
        if time_boundary:
            filters.append(JoySafeterTask.created_at >= time_boundary)
        if status:
            filters.append(JoySafeterTask.status == status)
        if agent_id:
            filters.append(JoySafeterTask.agent_id == agent_id)
        if engine:
            agent_ids_sq = select(JoySafeterAgent.id).where(JoySafeterAgent.engine_kind == engine)
            filters.append(JoySafeterTask.agent_id.in_(agent_ids_sq))

        # Count
        count_stmt = select(func.count(JoySafeterTask.id)).where(and_(*filters))
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # Data with agent join
        offset = (page - 1) * page_size
        stmt = (
            select(
                JoySafeterTask,
                JoySafeterAgent.name.label("agent_name"),
                JoySafeterAgent.engine_kind,
                func.jsonb_extract_path_text(JoySafeterAgent.model, "id").label("model_id"),
            )
            .select_from(JoySafeterTask)
            .outerjoin(JoySafeterAgent, JoySafeterTask.agent_id == JoySafeterAgent.id)
            .where(and_(*filters))
            .offset(offset)
            .limit(page_size)
        )

        # Apply sorting
        sort_columns = {
            "created_at": JoySafeterTask.created_at,
            "duration_ms": JoySafeterTask.duration_ms,
            "retry_count": JoySafeterTask.retry_count,
        }
        sort_col = sort_columns.get(sort_by, JoySafeterTask.created_at)
        stmt = stmt.order_by(sort_col.desc() if sort_order == "desc" else sort_col.asc())

        result = await self.db.execute(stmt)
        rows = result.all()

        records = []
        for row in rows:
            task = row[0]
            agent_name = row[1] or "Unknown"
            engine_kind = row[2]
            model_id = row[3]
            usage = task.usage or {}

            wait_ms = 0
            if task.started_at and task.created_at:
                wait_ms = int((task.started_at - task.created_at).total_seconds() * 1000)

            records.append(
                {
                    "id": task.id,
                    "trace_id": task.id,
                    "session_id": task.chat_session_id,
                    "agent_id": task.agent_id,
                    "agent_name": agent_name,
                    "engine_kind": engine_kind,
                    "model": model_id,
                    "status": task.status,
                    "input_tokens": usage.get("input_tokens", 0) or 0,
                    "output_tokens": usage.get("output_tokens", 0) or 0,
                    "total_tokens": (usage.get("input_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0),
                    "ttft_ms": None,
                    "duration_ms": task.duration_ms or 0,
                    "cost": 0.0,
                    "agent_steps": 0,
                    "error": task.error,
                    "started_at": task.started_at.isoformat() if task.started_at else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                    "retry_count": task.retry_count or 0,
                    "queue_wait_ms": wait_ms,
                }
            )

        return {
            "data": records,
            "has_more": (offset + page_size) < total,
            "total": total,
        }

    # ------------------------------------------------------------------
    # Agent Comparison
    # ------------------------------------------------------------------

    async def get_agent_comparison(
        self,
        project_id: ProjectId | None,
        range_str: str = "7d",
    ) -> list[dict]:
        """Compare metrics across agents using aggregated queries."""
        time_boundary = _get_time_boundary(range_str)

        # Single query for task metrics per agent
        task_filters = [JoySafeterTask.project_id == project_id]
        if time_boundary:
            task_filters.append(JoySafeterTask.created_at >= time_boundary)

        task_stmt = (
            select(
                JoySafeterTask.agent_id,
                JoySafeterAgent.name.label("agent_name"),
                JoySafeterAgent.engine_kind,
                func.count(JoySafeterTask.id).label("total_tasks"),
                func.count(case((JoySafeterTask.status == JoySafeterTaskStatus.COMPLETED.value, 1))).label("completed"),
                func.avg(JoySafeterTask.duration_ms).label("avg_duration"),
            )
            .select_from(JoySafeterTask)
            .join(JoySafeterAgent, JoySafeterTask.agent_id == JoySafeterAgent.id)
            .where(and_(*task_filters))
            .group_by(JoySafeterTask.agent_id, JoySafeterAgent.name, JoySafeterAgent.engine_kind)
            .order_by(desc("total_tasks"))
        )

        task_result = await self.db.execute(task_stmt)
        task_rows = task_result.all()

        # Single query for session counts per agent
        session_filters = [JoySafeterSession.project_id == project_id]
        if time_boundary:
            session_filters.append(JoySafeterSession.created_at >= time_boundary)

        session_stmt = (
            select(
                JoySafeterSession.agent_id,
                func.count(JoySafeterSession.id).label("total_sessions"),
            )
            .where(and_(*session_filters))
            .group_by(JoySafeterSession.agent_id)
        )

        session_result = await self.db.execute(session_stmt)
        session_map = {row.agent_id: row.total_sessions for row in session_result.all()}

        metrics_list = []
        for row in task_rows:
            total_tasks = row.total_tasks or 0
            success_rate = (row.completed or 0) / total_tasks if total_tasks > 0 else 0.0

            metrics_list.append(
                {
                    "agent_id": row.agent_id,
                    "agent_name": row.agent_name or "Unknown",
                    "engine_kind": row.engine_kind,
                    "total_sessions": session_map.get(row.agent_id, 0),
                    "total_tasks": total_tasks,
                    "success_rate": round(success_rate, 3),
                    "avg_duration_ms": round(float(row.avg_duration or 0), 1),
                    "avg_ttft_ms": 0.0,
                    "avg_cost": 0.0,
                    "total_tokens": 0,
                    "avg_agent_steps": 0.0,
                }
            )

        return metrics_list

    # ------------------------------------------------------------------
    # Health Check
    # ------------------------------------------------------------------

    async def get_health_check(
        self,
        project_id: ProjectId | None,
        range_str: str = "7d",
        consecutive_failures_enabled: bool = True,
        consecutive_failures_threshold: int = 3,
        slow_agent_enabled: bool = True,
        slow_agent_threshold_ms: int = 10000,
        token_spike_enabled: bool = True,
        token_spike_threshold_pct: int = 30,
    ) -> dict:
        """Aggregate health-check data: success rate, running tasks, alerts, token summary."""
        time_boundary = _get_time_boundary(range_str)

        # --- Basic task metrics (success rate) ---
        task_filters = [JoySafeterTask.project_id == project_id]
        if time_boundary:
            task_filters.append(JoySafeterTask.created_at >= time_boundary)

        summary_stmt = select(
            func.count(JoySafeterTask.id).label("total_calls"),
            func.count(case((JoySafeterTask.status == JoySafeterTaskStatus.FAILED.value, 1))).label("error_count"),
        ).where(and_(*task_filters))

        summary_result = await self.db.execute(summary_stmt)
        summary_row = summary_result.one()
        total_calls = summary_row.total_calls or 0
        error_count = summary_row.error_count or 0
        success_rate = (total_calls - error_count) / total_calls if total_calls > 0 else 0.0

        # --- Running sessions ---
        running_stmt = select(func.count(JoySafeterSession.id)).where(
            and_(
                JoySafeterSession.project_id == project_id,
                JoySafeterSession.status == "running",
            )
        )
        running_tasks = (await self.db.execute(running_stmt)).scalar() or 0

        # --- Last error timestamp ---
        last_error_stmt = (
            select(JoySafeterTask.completed_at)
            .where(
                and_(
                    JoySafeterTask.project_id == project_id,
                    JoySafeterTask.status == JoySafeterTaskStatus.FAILED.value,
                )
            )
            .order_by(JoySafeterTask.completed_at.desc())
            .limit(1)
        )
        last_error_row = (await self.db.execute(last_error_stmt)).scalar()
        last_error_at = last_error_row.isoformat() if last_error_row else None

        # --- Queue wait time: started_at - created_at ---
        queue_filters = [
            JoySafeterTask.project_id == project_id,
            JoySafeterTask.started_at.isnot(None),
        ]
        if time_boundary:
            queue_filters.append(JoySafeterTask.created_at >= time_boundary)

        queue_stmt = select(
            func.avg(func.extract("epoch", JoySafeterTask.started_at - JoySafeterTask.created_at)).label("avg_wait"),
            func.max(func.extract("epoch", JoySafeterTask.started_at - JoySafeterTask.created_at)).label("max_wait"),
        ).where(and_(*queue_filters))

        queue_result = await self.db.execute(queue_stmt)
        queue_row = queue_result.one()
        avg_queue_wait_sec = round(float(queue_row.avg_wait or 0), 1)
        max_queue_wait_sec = round(float(queue_row.max_wait or 0), 1)

        # --- Alerts ---
        alerts: list[dict] = []
        if consecutive_failures_enabled:
            alerts.extend(
                await self._detect_consecutive_failures(project_id, time_boundary, consecutive_failures_threshold)
            )
        if slow_agent_enabled:
            alerts.extend(await self._detect_slow_agents(project_id, time_boundary, slow_agent_threshold_ms))
        if token_spike_enabled:
            alerts.extend(await self._detect_token_spike(project_id, range_str, token_spike_threshold_pct))
        # Always-on detections (not gated by configurable toggles)
        alerts.extend(await self._detect_high_retries(project_id, time_boundary))
        alerts.extend(await self._detect_zombie_sessions(project_id))

        # --- Token summary ---
        session_filters = [JoySafeterSession.project_id == project_id]
        if time_boundary:
            session_filters.append(JoySafeterSession.created_at >= time_boundary)

        token_stmt = select(
            func.sum(
                func.coalesce(cast(func.jsonb_extract_path_text(JoySafeterSession.usage, "input_tokens"), Integer), 0)
            ).label("input"),
            func.sum(
                func.coalesce(cast(func.jsonb_extract_path_text(JoySafeterSession.usage, "output_tokens"), Integer), 0)
            ).label("output"),
            func.sum(
                func.coalesce(
                    cast(func.jsonb_extract_path_text(JoySafeterSession.usage, "cache_read_input_tokens"), Integer), 0
                )
            ).label("cache_read"),
        ).where(and_(*session_filters))

        token_result = await self.db.execute(token_stmt)
        token_row = token_result.one()
        input_tokens = int(token_row.input or 0)
        output_tokens = int(token_row.output or 0)
        cache_read = int(token_row.cache_read or 0)
        total_tokens = input_tokens + output_tokens
        cache_hit_rate = cache_read / (input_tokens + cache_read) if (input_tokens + cache_read) > 0 else 0.0

        # --- Overall status ---
        if any(a["severity"] == "error" for a in alerts):
            status = "critical"
        elif any(a["severity"] == "warning" for a in alerts):
            status = "warning"
        else:
            status = "healthy"

        # --- Optimization suggestions ---
        suggestions: list[dict] = []
        total_input = input_tokens
        total_output = output_tokens
        if cache_hit_rate < 0.5 and total_input > 0:
            suggestions.append(
                {
                    "type": "low_cache_hit",
                    "params": {"cacheHitPct": round(cache_hit_rate * 100)},
                }
            )
        if total_output > 0 and total_input > 0 and total_output / total_input > 0.5:
            suggestions.append(
                {
                    "type": "high_output_ratio",
                    "params": {"outputRatioPct": round(total_output / total_input * 100)},
                }
            )
        if avg_queue_wait_sec > 30:
            suggestions.append(
                {
                    "type": "high_queue_wait",
                    "params": {"queueWaitSec": round(avg_queue_wait_sec)},
                }
            )

        return {
            "status": status,
            "success_rate": round(success_rate, 3),
            "running_tasks": running_tasks,
            "last_error_at": last_error_at,
            "alerts": alerts,
            "token_summary": {
                "total": total_tokens,
                "input": input_tokens,
                "output": output_tokens,
                "cache_read": cache_read,
                "cache_hit_rate": round(cache_hit_rate, 3),
            },
            "suggestions": suggestions,
            "queue_wait": {
                "avg_sec": avg_queue_wait_sec,
                "max_sec": max_queue_wait_sec,
            },
        }

    async def _detect_consecutive_failures(
        self,
        project_id: ProjectId | None,
        time_boundary: Optional[datetime],
        threshold: int = 3,
    ) -> list[dict]:
        """Detect agents with consecutive recent failures."""
        alerts: list[dict] = []

        # Get agents that have at least one recent failure
        failed_agents_stmt = (
            select(JoySafeterTask.agent_id, JoySafeterAgent.name)
            .select_from(JoySafeterTask)
            .join(JoySafeterAgent, JoySafeterTask.agent_id == JoySafeterAgent.id)
            .where(
                and_(
                    JoySafeterTask.project_id == project_id,
                    JoySafeterTask.status == JoySafeterTaskStatus.FAILED.value,
                    JoySafeterTask.created_at >= time_boundary if time_boundary else true(),
                )
            )
            .group_by(JoySafeterTask.agent_id, JoySafeterAgent.name)
        )
        result = await self.db.execute(failed_agents_stmt)
        failed_agents = result.all()

        for agent_id, agent_name in failed_agents:
            # Get last 5 tasks for this agent
            recent_stmt = (
                select(JoySafeterTask.status)
                .where(
                    and_(
                        JoySafeterTask.project_id == project_id,
                        JoySafeterTask.agent_id == agent_id,
                    )
                )
                .order_by(JoySafeterTask.created_at.desc())
                .limit(5)
            )
            recent_result = await self.db.execute(recent_stmt)
            recent_statuses = [row[0] for row in recent_result.all()]

            # Count consecutive failures from the start (most recent)
            consecutive = 0
            for s in recent_statuses:
                if s in (JoySafeterTaskStatus.FAILED.value, JoySafeterTaskStatus.TIMEOUT.value):
                    consecutive += 1
                else:
                    break

            if consecutive >= threshold:
                alerts.append(
                    {
                        "type": "consecutive_failures",
                        "severity": "error",
                        "agent_name": agent_name,
                        "agent_id": agent_id,
                        "params": {"count": consecutive, "threshold": threshold},
                    }
                )

        return alerts

    async def _detect_slow_agents(
        self,
        project_id: ProjectId | None,
        time_boundary: Optional[datetime],
        threshold_ms: int = 10000,
    ) -> list[dict]:
        """Detect agents whose average duration exceeds the threshold."""
        filters = [JoySafeterTask.project_id == project_id, JoySafeterTask.duration_ms.isnot(None)]
        if time_boundary:
            filters.append(JoySafeterTask.created_at >= time_boundary)

        stmt = (
            select(
                JoySafeterTask.agent_id,
                JoySafeterAgent.name,
                func.avg(JoySafeterTask.duration_ms).label("avg_duration"),
            )
            .select_from(JoySafeterTask)
            .join(JoySafeterAgent, JoySafeterTask.agent_id == JoySafeterAgent.id)
            .where(and_(*filters))
            .group_by(JoySafeterTask.agent_id, JoySafeterAgent.name)
            .having(func.avg(JoySafeterTask.duration_ms) > threshold_ms)
        )
        result = await self.db.execute(stmt)

        return [
            {
                "type": "slow_agent",
                "severity": "warning",
                "agent_name": row.name,
                "agent_id": row.agent_id,
                "params": {
                    "avgSec": round(row.avg_duration / 1000, 1),
                    "thresholdSec": threshold_ms // 1000,
                },
            }
            for row in result.all()
        ]

    async def _detect_token_spike(
        self,
        project_id: ProjectId | None,
        range_str: str,
        threshold_pct: int = 30,
    ) -> list[dict]:
        """Detect if token usage spiked above threshold compared to the previous period."""
        time_boundary = _get_time_boundary(range_str)
        if not time_boundary:
            return []

        now = datetime.now(timezone.utc)
        period_length = now - time_boundary
        prev_end = time_boundary
        prev_start = prev_end - period_length

        # Current period tokens
        curr_stmt = select(
            func.sum(
                func.coalesce(cast(func.jsonb_extract_path_text(JoySafeterSession.usage, "input_tokens"), Integer), 0)
                + func.coalesce(
                    cast(func.jsonb_extract_path_text(JoySafeterSession.usage, "output_tokens"), Integer), 0
                )
            )
        ).where(
            and_(
                JoySafeterSession.project_id == project_id,
                JoySafeterSession.created_at >= time_boundary,
            )
        )
        curr_tokens = (await self.db.execute(curr_stmt)).scalar() or 0

        # Previous period tokens
        prev_stmt = select(
            func.sum(
                func.coalesce(cast(func.jsonb_extract_path_text(JoySafeterSession.usage, "input_tokens"), Integer), 0)
                + func.coalesce(
                    cast(func.jsonb_extract_path_text(JoySafeterSession.usage, "output_tokens"), Integer), 0
                )
            )
        ).where(
            and_(
                JoySafeterSession.project_id == project_id,
                JoySafeterSession.created_at >= prev_start,
                JoySafeterSession.created_at < prev_end,
            )
        )
        prev_tokens = (await self.db.execute(prev_stmt)).scalar() or 0

        if prev_tokens > 0:
            change_pct = (curr_tokens - prev_tokens) / prev_tokens
            if change_pct > threshold_pct / 100:
                return [
                    {
                        "type": "token_spike",
                        "severity": "warning",
                        "agent_name": None,
                        "agent_id": None,
                        "params": {
                            "changePct": round(change_pct * 100, 1),
                            "thresholdPct": threshold_pct,
                        },
                    }
                ]

        return []

    async def _detect_high_retries(self, project_id: ProjectId | None, time_boundary: Optional[datetime]) -> list[dict]:
        """Detect tasks with excessive retries."""
        filters = [
            JoySafeterTask.project_id == project_id,
            JoySafeterTask.retry_count >= 5,
        ]
        if time_boundary:
            filters.append(JoySafeterTask.created_at >= time_boundary)

        stmt = (
            select(
                JoySafeterTask.agent_id,
                JoySafeterAgent.name,
                func.max(JoySafeterTask.retry_count).label("max_retries"),
                func.count(JoySafeterTask.id).label("task_count"),
            )
            .select_from(JoySafeterTask)
            .join(JoySafeterAgent, JoySafeterTask.agent_id == JoySafeterAgent.id)
            .where(and_(*filters))
            .group_by(JoySafeterTask.agent_id, JoySafeterAgent.name)
            .order_by(desc("max_retries"))
        )

        result = await self.db.execute(stmt)
        return [
            {
                "type": "high_retries",
                "severity": "warning",
                "agent_name": row.name,
                "agent_id": row.agent_id,
                "params": {"maxRetries": row.max_retries, "taskCount": row.task_count},
            }
            for row in result.all()
        ]

    async def _detect_zombie_sessions(self, project_id: ProjectId | None) -> list[dict]:
        """Detect sessions stuck in running state for too long."""
        # Sessions running for > 2 hours
        threshold = datetime.now(timezone.utc) - timedelta(hours=2)

        stmt = (
            select(
                JoySafeterSession.id,
                JoySafeterSession.agent_id,
                JoySafeterAgent.name,
                JoySafeterSession.created_at,
            )
            .select_from(JoySafeterSession)
            .outerjoin(JoySafeterAgent, JoySafeterSession.agent_id == JoySafeterAgent.id)
            .where(
                and_(
                    JoySafeterSession.project_id == project_id,
                    JoySafeterSession.status == "running",
                    JoySafeterSession.created_at < threshold,
                )
            )
            .order_by(JoySafeterSession.created_at.asc())
        )

        result = await self.db.execute(stmt)
        alerts = []
        now = datetime.now(timezone.utc)
        for row in result.all():
            hours = (now - row.created_at).total_seconds() / 3600
            alerts.append(
                {
                    "type": "zombie_session",
                    "severity": "warning",
                    "agent_name": row.name,
                    "agent_id": row.agent_id,
                    "params": {"hours": round(hours, 1)},
                }
            )
        return alerts

    # ------------------------------------------------------------------
    # Agent Ranking
    # ------------------------------------------------------------------

    async def get_agent_ranking(self, project_id: ProjectId | None, range_str: str = "7d") -> list[dict]:
        """Rank agents by a composite health score."""
        time_boundary = _get_time_boundary(range_str)

        filters = [JoySafeterTask.project_id == project_id]
        if time_boundary:
            filters.append(JoySafeterTask.created_at >= time_boundary)

        stmt = (
            select(
                JoySafeterTask.agent_id,
                JoySafeterAgent.name.label("agent_name"),
                JoySafeterAgent.engine_kind,
                func.count(JoySafeterTask.id).label("total_tasks"),
                func.count(case((JoySafeterTask.status == JoySafeterTaskStatus.COMPLETED.value, 1))).label("completed"),
                func.count(case((JoySafeterTask.status == JoySafeterTaskStatus.FAILED.value, 1))).label("failed"),
                func.avg(JoySafeterTask.duration_ms).label("avg_duration_ms"),
            )
            .select_from(JoySafeterTask)
            .join(JoySafeterAgent, JoySafeterTask.agent_id == JoySafeterAgent.id)
            .where(and_(*filters))
            .group_by(JoySafeterTask.agent_id, JoySafeterAgent.name, JoySafeterAgent.engine_kind)
            .having(func.count(JoySafeterTask.id) >= 1)
            .order_by(desc("total_tasks"))
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        # Get token usage per agent from sessions
        session_filters = [JoySafeterSession.project_id == project_id]
        if time_boundary:
            session_filters.append(JoySafeterSession.created_at >= time_boundary)

        token_stmt = (
            select(
                JoySafeterSession.agent_id,
                func.sum(
                    func.coalesce(
                        cast(func.jsonb_extract_path_text(JoySafeterSession.usage, "input_tokens"), Integer), 0
                    )
                    + func.coalesce(
                        cast(func.jsonb_extract_path_text(JoySafeterSession.usage, "output_tokens"), Integer), 0
                    )
                ).label("total_tokens"),
            )
            .where(and_(*session_filters))
            .group_by(JoySafeterSession.agent_id)
        )
        token_result = await self.db.execute(token_stmt)
        token_map = {r.agent_id: int(r.total_tokens or 0) for r in token_result.all()}

        # Get last task time per agent (across all time, not filtered by range)
        last_task_stmt = (
            select(
                JoySafeterTask.agent_id,
                func.max(JoySafeterTask.created_at).label("last_task_at"),
            )
            .where(JoySafeterTask.project_id == project_id)
            .group_by(JoySafeterTask.agent_id)
        )
        last_task_result = await self.db.execute(last_task_stmt)
        last_task_map = {r.agent_id: r.last_task_at for r in last_task_result.all()}

        now = datetime.now(timezone.utc)

        ranking = []
        for row in rows:
            total = row.total_tasks or 1
            success_rate = (row.completed or 0) / total
            failed = row.failed or 0
            avg_dur = float(row.avg_duration_ms or 0)
            tokens = token_map.get(row.agent_id, 0)

            last_task = last_task_map.get(row.agent_id)
            if not last_task:
                activity_status = "unused"
            elif (now - last_task).total_seconds() < 86400:
                activity_status = "active"
            else:
                activity_status = "idle"

            ranking.append(
                {
                    "agent_id": row.agent_id,
                    "agent_name": row.agent_name,
                    "engine_kind": row.engine_kind,
                    "total_tasks": total,
                    "success_rate": round(success_rate, 3),
                    "failed_count": failed,
                    "avg_duration_ms": round(avg_dur, 1),
                    "total_tokens": tokens,
                    "last_task_at": last_task.isoformat() if last_task else None,
                    "activity_status": activity_status,
                }
            )

        # Include agents with zero tasks (not in the main query results)
        existing_agent_ids = {r["agent_id"] for r in ranking}

        all_agents_stmt = select(JoySafeterAgent).where(
            and_(
                JoySafeterAgent.project_id == project_id,
                JoySafeterAgent.deleted_at.is_(None),
            )
        )
        all_agents_result = await self.db.execute(all_agents_stmt)
        for agent in all_agents_result.scalars().all():
            if agent.id not in existing_agent_ids:
                last_task = last_task_map.get(agent.id)
                ranking.append(
                    {
                        "agent_id": agent.id,
                        "agent_name": agent.name,
                        "engine_kind": agent.engine_kind,
                        "total_tasks": 0,
                        "success_rate": 0.0,
                        "failed_count": 0,
                        "avg_duration_ms": 0.0,
                        "total_tokens": 0,
                        "last_task_at": last_task.isoformat() if last_task else None,
                        "activity_status": "unused",
                    }
                )

        # Sort by: failed_count desc, then success_rate asc (worst first)
        ranking.sort(key=lambda x: (-x["failed_count"], x["success_rate"]))
        return ranking

    # ------------------------------------------------------------------
    # Time Heatmap
    # ------------------------------------------------------------------

    async def get_time_heatmap(self, project_id: ProjectId | None, range_str: str = "7d") -> list[dict]:
        """Get task counts by hour and day-of-week for heatmap."""
        time_boundary = _get_time_boundary(range_str)

        filters = [JoySafeterTask.project_id == project_id]
        if time_boundary:
            filters.append(JoySafeterTask.created_at >= time_boundary)

        stmt = (
            select(
                func.extract("dow", JoySafeterTask.created_at).label("day_of_week"),  # 0=Sunday
                func.extract("hour", JoySafeterTask.created_at).label("hour"),
                func.count(JoySafeterTask.id).label("count"),
                func.count(case((JoySafeterTask.status == JoySafeterTaskStatus.FAILED.value, 1))).label("error_count"),
            )
            .where(and_(*filters))
            .group_by(text("day_of_week"), text("hour"))
            .order_by(text("day_of_week"), text("hour"))
        )

        result = await self.db.execute(stmt)
        return [
            {
                "day": int(row.day_of_week),
                "hour": int(row.hour),
                "count": row.count,
                "error_count": row.error_count or 0,
            }
            for row in result.all()
        ]

    # ------------------------------------------------------------------
    # Error Summary
    # ------------------------------------------------------------------

    async def get_error_summary(
        self,
        project_id: ProjectId | None,
        range_str: str = "7d",
        engine: Optional[str] = None,
        agent_id: Optional[AgentId] = None,
    ) -> dict:
        """Aggregate errors by status type and show top error messages."""
        time_boundary = _get_time_boundary(range_str)

        filters = [
            JoySafeterTask.project_id == project_id,
            JoySafeterTask.status.in_(
                [
                    JoySafeterTaskStatus.FAILED.value,
                    JoySafeterTaskStatus.TIMEOUT.value,
                    JoySafeterTaskStatus.CANCELLED.value,
                ]
            ),
        ]
        if time_boundary:
            filters.append(JoySafeterTask.created_at >= time_boundary)
        if agent_id:
            filters.append(JoySafeterTask.agent_id == agent_id)
        if engine:
            agent_ids_sq = select(JoySafeterAgent.id).where(JoySafeterAgent.engine_kind == engine)
            filters.append(JoySafeterTask.agent_id.in_(agent_ids_sq))

        # Count by status
        status_stmt = (
            select(
                JoySafeterTask.status.label("status"),
                func.count(JoySafeterTask.id).label("count"),
            )
            .where(and_(*filters))
            .group_by(JoySafeterTask.status)
            .order_by(desc("count"))
        )
        status_result = await self.db.execute(status_stmt)
        status_breakdown = [{"status": r.status, "count": r.count} for r in status_result.all()]

        # Top error messages (truncated)
        error_filters = filters + [JoySafeterTask.error.isnot(None)]
        msg_stmt = (
            select(
                func.substring(JoySafeterTask.error, 1, 100).label("message"),
                func.count(JoySafeterTask.id).label("count"),
            )
            .where(and_(*error_filters))
            .group_by(text("message"))
            .order_by(desc("count"))
            .limit(5)
        )
        msg_result = await self.db.execute(msg_stmt)
        top_errors = [{"message": r.message, "count": r.count} for r in msg_result.all()]

        total_errors = sum(s["count"] for s in status_breakdown)

        return {
            "total_errors": total_errors,
            "status_breakdown": status_breakdown,
            "top_errors": top_errors,
        }

    # ------------------------------------------------------------------
    # Latency Stats (P50/P95/P99)
    # ------------------------------------------------------------------

    async def get_latency_stats(
        self,
        project_id: ProjectId | None,
        range_str: str = "7d",
        engine: Optional[str] = None,
        agent_id: Optional[AgentId] = None,
    ) -> dict:
        """Compute duration distribution by time buckets."""
        time_boundary = _get_time_boundary(range_str)
        filters = [JoySafeterTask.project_id == project_id, JoySafeterTask.duration_ms.isnot(None)]
        if time_boundary:
            filters.append(JoySafeterTask.created_at >= time_boundary)
        if agent_id:
            filters.append(JoySafeterTask.agent_id == agent_id)
        if engine:
            agent_ids_sq = select(JoySafeterAgent.id).where(JoySafeterAgent.engine_kind == engine)
            filters.append(JoySafeterTask.agent_id.in_(agent_ids_sq))

        stmt = select(
            func.count(JoySafeterTask.id).label("total"),
            func.count(case((JoySafeterTask.duration_ms < 10000, 1))).label("under_10s"),
            func.count(case((and_(JoySafeterTask.duration_ms >= 10000, JoySafeterTask.duration_ms < 60000), 1))).label(
                "_10s_1m"
            ),
            func.count(case((and_(JoySafeterTask.duration_ms >= 60000, JoySafeterTask.duration_ms < 600000), 1))).label(
                "_1m_10m"
            ),
            func.count(
                case((and_(JoySafeterTask.duration_ms >= 600000, JoySafeterTask.duration_ms < 3600000), 1))
            ).label("_10m_1h"),
            func.count(case((JoySafeterTask.duration_ms >= 3600000, 1))).label("over_1h"),
        ).where(and_(*filters))

        result = await self.db.execute(stmt)
        row = result.one()
        total = row.total or 1

        buckets: list[dict[str, Any]] = [
            {
                "label": "< 10s",
                "count": row.under_10s or 0,
                "pct": round((row.under_10s or 0) / total * 100, 1),
                "color": "emerald",
            },
            {
                "label": "10s–1m",
                "count": row._10s_1m or 0,
                "pct": round((row._10s_1m or 0) / total * 100, 1),
                "color": "emerald",
            },
            {
                "label": "1m–10m",
                "count": row._1m_10m or 0,
                "pct": round((row._1m_10m or 0) / total * 100, 1),
                "color": "amber",
            },
            {
                "label": "10m–1h",
                "count": row._10m_1h or 0,
                "pct": round((row._10m_1h or 0) / total * 100, 1),
                "color": "amber",
            },
            {
                "label": "> 1h",
                "count": row.over_1h or 0,
                "pct": round((row.over_1h or 0) / total * 100, 1),
                "color": "red",
            },
        ]

        return {
            "total_calls": row.total or 0,
            "buckets": [b for b in buckets if b["count"] > 0],
        }
