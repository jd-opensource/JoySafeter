from datetime import datetime, timezone

from app.joysafeter_shared.utils import datetime as datetime_utils


def test_platform_now_uses_canonical_platform_timezone(monkeypatch):
    monkeypatch.setenv("JOYSAFETER_TIMEZONE", "Asia/Shanghai")
    monkeypatch.setenv("TZ", "America/New_York")
    monkeypatch.setattr(
        datetime_utils,
        "utc_now",
        lambda: datetime(2026, 8, 10, 8, 5, tzinfo=timezone.utc),
    )

    assert datetime_utils.platform_now().isoformat() == "2026-08-10T16:05:00+08:00"


def test_platform_now_falls_back_to_utc_for_invalid_timezone(monkeypatch):
    monkeypatch.setenv("JOYSAFETER_TIMEZONE", "Invalid/Timezone")
    monkeypatch.setattr(
        datetime_utils,
        "utc_now",
        lambda: datetime(2026, 8, 10, 8, 5, tzinfo=timezone.utc),
    )

    assert datetime_utils.platform_now().isoformat() == "2026-08-10T08:05:00+00:00"
