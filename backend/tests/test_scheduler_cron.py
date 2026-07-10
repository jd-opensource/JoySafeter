"""Unit tests for the scheduler cron utilities and concurrency-policy enum.

No database required (marked ``no_db``): these cover the pure cron math that
underpins next_run scheduling and the "catch up once and advance" behaviour.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.joysafeter_domain.models.joysafeter_schedule import ScheduleConcurrencyPolicy
from app.joysafeter_shared.utils.cron import compute_next_run, validate_cron, validate_timezone

pytestmark = pytest.mark.no_db


def test_validate_cron() -> None:
    assert validate_cron("*/5 * * * *")
    assert validate_cron("0 9 * * 1-5")
    assert not validate_cron("not-a-cron")
    assert not validate_cron("* * * *")


def test_validate_timezone() -> None:
    assert validate_timezone("UTC")
    assert validate_timezone("America/New_York")
    assert validate_timezone("Asia/Shanghai")
    assert not validate_timezone("Nowhere/Nope")


def test_compute_next_run_is_future_and_utc() -> None:
    n = compute_next_run("* * * * *", "UTC")
    assert n.tzinfo is not None
    assert n > datetime.now(timezone.utc)


def test_compute_next_run_monotonicity_guard() -> None:
    # Base far in the past must still yield a future instant (never re-fire past).
    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    n = compute_next_run("* * * * *", "UTC", after=past)
    assert n >= datetime.now(timezone.utc) + timedelta(seconds=0)


def test_compute_next_run_respects_timezone() -> None:
    # 9am daily in New York must land on 09:00 New-York local, DST-correct.
    n = compute_next_run("0 9 * * *", "America/New_York")
    local = n.astimezone(ZoneInfo("America/New_York"))
    assert (local.hour, local.minute) == (9, 0)


def test_compute_next_run_advances_from_given_slot() -> None:
    # After firing a slot, the next run computed from "now" must be strictly later.
    first = compute_next_run("*/5 * * * *", "UTC")
    second = compute_next_run("*/5 * * * *", "UTC", after=first)
    assert second > first


def test_concurrency_policy_values() -> None:
    assert {p.value for p in ScheduleConcurrencyPolicy} == {"allow", "forbid", "replace"}
