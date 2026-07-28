"""P2 schema validation: keyed session_key, cron_expr XOR run_at, run_at rules."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.joysafeter_domain.schemas.joysafeter_trigger import TriggerCreateRequest

pytestmark = pytest.mark.no_db

_FUTURE = datetime.now(timezone.utc) + timedelta(hours=1)
_PAST = datetime.now(timezone.utc) - timedelta(hours=1)


def _cron(**over):
    base = dict(name="s", type="cron", agent_id=uuid.uuid4(), prompt_template="p")
    base.update(over)
    return base


def test_cron_requires_cron_expr_or_run_at():
    with pytest.raises(ValueError):
        TriggerCreateRequest(**_cron())  # neither


def test_cron_rejects_both_cron_expr_and_run_at():
    with pytest.raises(ValueError):
        TriggerCreateRequest(**_cron(cron_expr="* * * * *", run_at=_FUTURE))


def test_cron_accepts_cron_expr_only():
    req = TriggerCreateRequest(**_cron(cron_expr="*/5 * * * *"))
    assert req.cron_expr == "*/5 * * * *" and req.run_at is None


def test_cron_accepts_run_at_only():
    req = TriggerCreateRequest(**_cron(run_at=_FUTURE))
    assert req.run_at is not None and req.cron_expr is None


def test_run_at_must_be_future():
    with pytest.raises(ValueError):
        TriggerCreateRequest(**_cron(run_at=_PAST))


def test_run_at_only_valid_for_cron():
    with pytest.raises(ValueError):
        TriggerCreateRequest(name="s", type="webhook", agent_id=uuid.uuid4(), prompt_template="p", secret_ref="x", run_at=_FUTURE)


def test_keyed_requires_session_key():
    with pytest.raises(ValueError):
        TriggerCreateRequest(name="s", type="webhook", agent_id=uuid.uuid4(), prompt_template="p", secret_ref="x", session_mode="keyed")


def test_keyed_accepts_session_key():
    req = TriggerCreateRequest(
        name="s", type="webhook", agent_id=uuid.uuid4(), prompt_template="p", secret_ref="x",
        session_mode="keyed", session_key="{{ body.chat_id }}",
    )
    assert req.session_mode == "keyed" and req.session_key == "{{ body.chat_id }}"
