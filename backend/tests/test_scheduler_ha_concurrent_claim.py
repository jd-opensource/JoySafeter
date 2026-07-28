"""Distributed HA of the cron scheduler control plane (multi-worker safety).

The scheduler runs inside the worker service, which is deployed as N replicas
(see deploy/HA.md). Correctness under >1 worker relies on the Postgres claim
semantics in ``JoySafeterTriggerService.claim_due_cron_triggers``:

- ``FOR UPDATE SKIP LOCKED`` + freshly-set ``locked_by``/``locked_at`` means two
  workers claiming concurrently get DISJOINT trigger sets — no double-claim,
  hence no duplicate fire (the task idempotency key is the final arbiter).
- A crashed worker's lock goes stale after ``lock_grace_sec`` and is reclaimed
  by a survivor — no slot is lost.

These two tests exercise both against a real Postgres (testcontainers), using a
SECOND independent connection to model a second worker.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService


async def _seed_base(db):
    org = Organization(name=f"ha-org-{uuid.uuid4()}", slug=f"ha-org-{uuid.uuid4()}")
    db.add(org)
    await db.flush()
    project = Project(org_id=org.id, name="P", slug=f"ha-p-{uuid.uuid4()}")
    db.add(project)
    await db.flush()
    agent = JoySafeterAgent(name=f"ha-agent-{uuid.uuid4()}", project_id=project.id)
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    await db.refresh(project)
    return org, project, agent


async def _seed_due_cron(db, org, project, agent, name, *, locked_by=None, locked_at=None):
    trigger = JoySafeterTrigger(
        name=name,
        type="cron",
        agent_id=agent.id,
        prompt_template="p",
        cron_expr="* * * * *",
        timezone="UTC",
        enabled=True,
        next_run_at=datetime.now(timezone.utc) - timedelta(seconds=1),  # due now
        locked_by=locked_by,
        locked_at=locked_at,
        project_id=project.id,
        user_id="owner",
        org_id=org.id,
        filter={},
        config={},
        last_payload={},
    )
    db.add(trigger)
    await db.commit()
    await db.refresh(trigger)
    return trigger


@pytest.mark.asyncio
async def test_stale_lock_reclaimed_but_fresh_lock_respected(db_session):
    """A crashed worker's slot is reclaimed (no lost slot); a live lock is not."""
    org, project, agent = await _seed_base(db_session)
    now = datetime.now(timezone.utc)
    stale = await _seed_due_cron(
        db_session, org, project, agent, "stale", locked_by="crashed", locked_at=now - timedelta(seconds=200)
    )
    fresh = await _seed_due_cron(
        db_session, org, project, agent, "fresh", locked_by="alive", locked_at=now
    )

    claimed = await JoySafeterTriggerService(db_session).claim_due_cron_triggers(
        worker_id="survivor", limit=10, lock_grace_sec=120
    )
    ids = {t.id for t in claimed}

    assert stale.id in ids, "a crashed worker's stale-locked slot must be reclaimed (no lost slot)"
    assert fresh.id not in ids, "a live lock (fresh locked_at) must be respected (no double-processing)"


@pytest.mark.asyncio
async def test_skip_locked_prevents_double_claim_across_workers(db_session, postgres_url):
    """Two workers claiming concurrently never both grab the same due trigger."""
    org, project, agent = await _seed_base(db_session)
    trigger = await _seed_due_cron(db_session, org, project, agent, "contended")

    # Worker A (this session) claims it — sets a fresh lock and commits.
    claimed_a = await JoySafeterTriggerService(db_session).claim_due_cron_triggers(worker_id="A", limit=10)
    assert trigger.id in {t.id for t in claimed_a}

    # Worker B is a SEPARATE connection (models a second replica). It must NOT
    # re-claim A's freshly-locked trigger.
    engine_b = create_async_engine(postgres_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine_b, expire_on_commit=False)() as session_b:
            claimed_b = await JoySafeterTriggerService(session_b).claim_due_cron_triggers(worker_id="B", limit=10)
    finally:
        await engine_b.dispose()

    assert trigger.id not in {t.id for t in claimed_b}, "worker B must not double-claim worker A's trigger"
