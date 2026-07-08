"""P2 unit tests — async scan dispatch + scanning state gate.

Covers the four P2 surfaces that don't touch real DB:

  - ``scan_input_bytes`` size estimation
  - ``SkillSecurityService.should_scan_async`` threshold decision
  - ``is_skill_usable`` treats ``scanning`` like ``not_scanned``
  - lifecycle + scanning interactions
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.joysafeter_domain.services.joysafeter_skill_security import scan_input_bytes
from app.joysafeter_domain.services.joysafeter_skill_security import is_skill_usable
from app.joysafeter_domain.services.joysafeter_skill_security import (
    SkillSecurityService,
    build_scan_files,
    target_hash,
)


# ── scan_input_bytes ───────────────────────────────────────────


def test_scan_input_bytes_counts_metadata():
    """Name + description + content all count toward the estimate."""
    n = scan_input_bytes(name="hi", description="ok", content="hello", files=None)
    # "hi"=2, "ok"=2, "hello"=5 -> 9 bytes
    assert n == 9


def test_scan_input_bytes_counts_string_files():
    n = scan_input_bytes(
        name="",
        description="",
        content="",
        files=[{"content": "a" * 100}, {"content": "b" * 200}],
    )
    assert n == 300


def test_scan_input_bytes_counts_bytes_files():
    """Some upload paths leave content as bytes; the estimator should
    handle both string and raw bytes equivalently."""
    n = scan_input_bytes(
        name="",
        description="",
        content="",
        files=[{"content": b"a" * 50}, {"content": bytearray(b"b" * 50)}],
    )
    assert n == 100


def test_scan_input_bytes_handles_missing_content():
    """A file dict without 'content' is allowed (e.g. external storage
    placeholders) — it just contributes zero to the estimate."""
    n = scan_input_bytes(
        name="x",
        description="",
        content="",
        files=[{"file_name": "ref.py"}],
    )
    assert n == 1  # only "x" from name


# ── should_scan_async threshold ────────────────────────────────


def test_should_scan_async_under_threshold_returns_false():
    """A small skill should run inline — no async overhead worth taking."""
    with patch(
        "app.joysafeter_domain.services.joysafeter_skill_security.settings"
    ) as s:
        s.skill_security_async_threshold_bytes = 1024
        # 'a' * 100 is well under 1024
        decision = SkillSecurityService.should_scan_async(
            name="x", description="", content="a" * 100, files=None
        )
        assert decision is False


def test_should_scan_async_over_threshold_returns_true():
    with patch(
        "app.joysafeter_domain.services.joysafeter_skill_security.settings"
    ) as s:
        s.skill_security_async_threshold_bytes = 1024
        decision = SkillSecurityService.should_scan_async(
            name="x", description="", content="a" * 2000, files=None
        )
        assert decision is True


def test_should_scan_async_zero_threshold_forces_async():
    """Setting the threshold to 0 (or negative) makes everything async —
    operators can opt the entire deployment into the async pipeline."""
    with patch(
        "app.joysafeter_domain.services.joysafeter_skill_security.settings"
    ) as s:
        s.skill_security_async_threshold_bytes = 0
        decision = SkillSecurityService.should_scan_async(
            name="", description="", content="", files=None
        )
        assert decision is True


def test_should_scan_async_huge_threshold_keeps_everything_sync():
    """The opposite knob: a huge threshold keeps the pre-P2 behavior."""
    with patch(
        "app.joysafeter_domain.services.joysafeter_skill_security.settings"
    ) as s:
        s.skill_security_async_threshold_bytes = 10 * 1024 * 1024
        # 1MB content is under a 10MB threshold
        decision = SkillSecurityService.should_scan_async(
            name="", description="", content="a" * (1024 * 1024), files=None
        )
        assert decision is False


# ── is_skill_usable + scanning state ───────────────────────────


def _hash_for(*, name="t", description="d", content="c", tags=None, license=None, files=None):
    tags = tags or []
    files = files or []
    canon_files = build_scan_files(
        name=name, description=description, content=content,
        tags=tags, license=license, files=files,
    )
    return target_hash(
        name=name, description=description, content=content,
        tags=tags, license=license, files=canon_files,
    )


def _skill(*, lifecycle="approved", security="passed", sec_hash=None):
    if sec_hash is None:
        sec_hash = _hash_for()
    return SimpleNamespace(
        name="t",
        description="d",
        content="c",
        tags=[],
        license=None,
        files=[],
        lifecycle_status=lifecycle,
        security_status=security,
        security_scan_hash=sec_hash,
    )


def test_scanning_status_blocks_load():
    """A skill mid-async-scan must never load. P2's scanning state is
    deliberately runtime-fatal."""
    ok, reason = is_skill_usable(_skill(security="scanning"))
    assert ok is False
    assert reason == "security_scanning"


def test_scanning_state_takes_precedence_over_valid_hash():
    """Even if the hash matches a previous scan, ``scanning`` must
    still block — the agent might race a verdict that's about to land
    as ``blocked``."""
    matching_hash = _hash_for()
    ok, reason = is_skill_usable(
        _skill(security="scanning", sec_hash=matching_hash)
    )
    assert ok is False
    assert reason == "security_scanning"


def test_lifecycle_check_runs_before_security():
    """Order matters: a draft skill that's also mid-scan reports
    ``skill_not_approved``, not ``security_scanning`` — the lifecycle
    gate is the cheaper check and it pins the reason most useful to
    the UI (the owner knows scanning is in-flight; they need to know
    they haven't approved the skill yet)."""
    ok, reason = is_skill_usable(
        _skill(lifecycle="draft", security="scanning")
    )
    assert ok is False
    assert reason == "skill_not_approved"


# ── mark_scanning idempotence ──────────────────────────────────


@pytest.mark.parametrize("starting_status", ["passed", "warning", "failed", "not_scanned"])
async def test_mark_scanning_flips_status(starting_status):
    """``mark_scanning`` should override any non-scanning state. The
    BG scan path relies on this to take a skill out of the runtime
    allowlist while it re-evaluates."""
    from unittest.mock import AsyncMock, MagicMock

    skill = SimpleNamespace(security_status=starting_status)
    db = MagicMock()
    db.get = AsyncMock(return_value=skill)
    db.flush = AsyncMock()

    svc = SkillSecurityService.__new__(SkillSecurityService)
    svc.db = db
    await svc.mark_scanning(skill_id="anything")
    assert skill.security_status == "scanning"
    db.flush.assert_called_once()


async def test_mark_scanning_is_idempotent():
    """Calling on an already-scanning row is a no-op (no flush)."""
    from unittest.mock import AsyncMock, MagicMock

    skill = SimpleNamespace(security_status="scanning")
    db = MagicMock()
    db.get = AsyncMock(return_value=skill)
    db.flush = AsyncMock()

    svc = SkillSecurityService.__new__(SkillSecurityService)
    svc.db = db
    await svc.mark_scanning(skill_id="anything")
    assert skill.security_status == "scanning"
    db.flush.assert_not_called()


async def test_mark_scanning_missing_skill_is_safe():
    """If the skill row was deleted between dispatch and the BG task
    landing, ``mark_scanning`` should silently return rather than crash."""
    from unittest.mock import AsyncMock, MagicMock

    db = MagicMock()
    db.get = AsyncMock(return_value=None)
    db.flush = AsyncMock()

    svc = SkillSecurityService.__new__(SkillSecurityService)
    svc.db = db
    await svc.mark_scanning(skill_id="ghost")
    db.flush.assert_not_called()
