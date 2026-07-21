"""Unit tests for ``SkillLifecycleService`` state machine.

Covers the transition table (allowed / forbidden edges) end-to-end through
``SkillLifecycleService`` rather than just the ``_ALLOWED_EDGES`` dict, so
the test catches a future change that forgets to mirror the table into a
new transition method.

Strategy
--------

The service has three dependencies:

  - a ``SkillRepository.get(skill_id)``  (DB lookup)
  - ``check_skill_access`` (permission check)
  - ``self.db.commit() / refresh()`` (persistence)

We replace each with a fake to keep the tests in-process. The fakes
preserve the contract the service relies on; nothing observable changes
between this harness and a real DB run apart from the absence of SQL.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.services.joysafeter_skill_service import (
    _ALLOWED_EDGES,
    LifecycleTransition,
    SkillLifecycleService,
)
from app.joysafeter_shared.common.app_errors import (
    InvalidRequestError,
    NotFoundError,
)


pytestmark = pytest.mark.no_db


class _FakeDB:
    """No-op stand-in for ``AsyncSession``. The service only calls
    ``commit`` and ``refresh`` (and ``execute`` through the repo, which
    we stub out)."""

    async def commit(self):
        pass

    async def refresh(self, _):
        pass


class _FakeSkillRepo:
    """Returns a single pre-seeded skill (or ``None``) — enough for the
    transition flow, which only calls ``get(skill_id)`` once per call."""

    def __init__(self, skill):
        self.skill = skill

    async def get(self, _skill_id):
        return self.skill


def _make_service(skill, *, monkeypatch):
    svc = SkillLifecycleService.__new__(SkillLifecycleService)
    svc.db = _FakeDB()
    svc.skill_repo = _FakeSkillRepo(skill)
    # P2.9 added strict org-isolation context. ``None`` keeps the
    # pre-P2.9 cross-org-friendly behavior — the right default for
    # tests that don't exercise that gate (those live in
    # ``test_skill_permissions``).
    svc._active_org_id = None

    # Bypass the per-skill auth check: every transition test calls it,
    # and we cover access denial separately in
    # ``test_skill_permissions``.
    async def _allow(*_args, **_kw):
        return None

    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_service.check_skill_access",
        _allow,
    )
    return svc


def _skill(lifecycle):
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id="user-1",
        lifecycle_status=lifecycle,
    )


# ── happy path: every allowed edge ─────────────────────────────


@pytest.mark.parametrize(
    "from_status,to_status,method_name",
    [
        ("draft", "pending_review", "submit_for_review"),
        ("pending_review", "approved", "approve"),
        ("pending_review", "rejected", "reject"),
        ("rejected", "draft", "reopen"),
        ("approved", "archived", "archive"),
        ("archived", "approved", "unarchive"),
    ],
)
async def test_allowed_transitions(from_status, to_status, method_name, monkeypatch):
    skill = _skill(from_status)
    svc = _make_service(skill, monkeypatch=monkeypatch)
    if to_status == "approved":
        monkeypatch.setattr(
            "app.joysafeter_domain.services.joysafeter_skill_security.scan_ok",
            lambda _skill: (True, None),
        )
    transition = await getattr(svc, method_name)(skill.id, current_user_id="user-1")
    assert isinstance(transition, LifecycleTransition)
    assert transition.from_status == from_status
    assert transition.to_status == to_status
    assert skill.lifecycle_status == to_status, "state machine must write back"


# ── forbidden transitions ──────────────────────────────────────


@pytest.mark.parametrize(
    "from_status,method_name",
    [
        # skipping review
        ("draft", "approve"),
        ("draft", "reject"),
        ("draft", "archive"),
        # editing approved without going back through review
        ("approved", "approve"),
        ("approved", "reject"),
        ("approved", "submit_for_review"),
        # archived stays terminal until un-archived
        ("archived", "submit_for_review"),
        ("archived", "reject"),
        ("archived", "archive"),
        # rejected must go via reopen, not direct approve
        ("rejected", "approve"),
        ("rejected", "reject"),
        # pending_review's own escape edges only — no archive
        ("pending_review", "archive"),
        ("pending_review", "submit_for_review"),
    ],
)
async def test_forbidden_transitions_raise(from_status, method_name, monkeypatch):
    skill = _skill(from_status)
    svc = _make_service(skill, monkeypatch=monkeypatch)
    with pytest.raises(InvalidRequestError) as ei:
        await getattr(svc, method_name)(skill.id, current_user_id="user-1")
    assert ei.value.code == "SKILL_LIFECYCLE_INVALID_TRANSITION"
    # State machine must NOT have written a partial transition
    assert skill.lifecycle_status == from_status


# ── error surface ──────────────────────────────────────────────


async def test_missing_skill_raises_not_found(monkeypatch):
    svc = _make_service(None, monkeypatch=monkeypatch)
    with pytest.raises(NotFoundError) as ei:
        await svc.submit_for_review(uuid.uuid4(), current_user_id="user-1")
    assert ei.value.code == "SKILL_NOT_FOUND"


@pytest.mark.parametrize("from_status,method_name", [("pending_review", "approve"), ("archived", "unarchive")])
async def test_approved_state_requires_scan_ready(from_status, method_name, monkeypatch):
    skill = _skill(from_status)
    svc = _make_service(skill, monkeypatch=monkeypatch)
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_skill_security.scan_ok",
        lambda _skill: (False, "security_not_scanned"),
    )

    with pytest.raises(InvalidRequestError) as ei:
        await getattr(svc, method_name)(skill.id, current_user_id="user-1")

    assert ei.value.code == "SKILL_LIFECYCLE_NOT_RUNTIME_READY"
    assert ei.value.data["reason"] == "security_not_scanned"
    assert skill.lifecycle_status == from_status


# ── transition table invariants ────────────────────────────────


def test_allowed_edges_table_matches_design():
    """The ``_ALLOWED_EDGES`` dict is the single source of truth for the
    transition contract; pin it explicitly so a stray refactor that
    drops an edge fails this test rather than silently changing behavior."""
    expected = {
        ("draft", "pending_review"),
        ("pending_review", "approved"),
        ("pending_review", "rejected"),
        ("rejected", "draft"),
        ("approved", "archived"),
        ("archived", "approved"),
    }
    actual = {(f, t) for f, tos in _ALLOWED_EDGES.items() for t in tos}
    assert actual == expected
