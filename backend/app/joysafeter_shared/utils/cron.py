"""Cron helpers for the scheduler.

Uses ``croniter`` for expression parsing and stdlib ``zoneinfo`` for timezone
handling (Python 3.12) — no pytz dependency. All returned instants are
timezone-aware UTC datetimes so they compare cleanly against ``next_run_at``
columns declared ``DateTime(timezone=True)``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter  # type: ignore[import-untyped]


def validate_cron(cron_expr: str) -> bool:
    """True if *cron_expr* is a valid 5-field cron expression."""
    return bool(croniter.is_valid(cron_expr))


def validate_timezone(tz_name: str) -> bool:
    """True if *tz_name* is a resolvable IANA timezone."""
    try:
        ZoneInfo(tz_name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def compute_next_run(
    cron_expr: str,
    tz_name: str = "UTC",
    after: datetime | None = None,
) -> datetime:
    """Return the next cron instant strictly after *after* as UTC.

    The cron schedule is evaluated in *tz_name* (so "0 9 * * *" means 9am local,
    DST-correct), then converted to UTC. A monotonicity guard ensures the result
    is at least one second in the future, so a schedule can never be computed
    into the past and re-fire immediately.
    """
    tz = ZoneInfo(tz_name)
    now_utc = datetime.now(timezone.utc)
    base = after if after is not None else now_utc
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    base_local = base.astimezone(tz)

    itr = croniter(cron_expr, base_local)
    next_local: datetime = itr.get_next(datetime)
    next_utc = next_local.astimezone(timezone.utc)

    minimum = now_utc + timedelta(seconds=1)
    return max(next_utc, minimum)
