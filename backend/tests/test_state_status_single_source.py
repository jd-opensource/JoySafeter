"""Single-source / cross-language guardrails for status vocabularies.

These are DEFENSIVE tests — they assert no runtime behavior, only that the
several places a status vocabulary is (re-)declared stay in agreement. The
state machines are hand-duplicated across Python (enums), the Rust
orchestrator (SQL string literals + `match` arms) and, for skills, scattered
service literals. Nothing but discipline keeps them aligned; these tests turn
a silent drift into a failing check.

Two families:
  #1  Skill ``security_status`` is now single-sourced by the
      ``JoySafeterSkillSecurityStatus`` enum; the runtime/auto-demote policy
      sets must derive from it.
  #2  The task terminal-status set and its active-task complement are
      re-typed as SQL literals in the Rust orchestrator; they must match the
      Python ``JoySafeterTaskStatus`` enum. The sandbox status vocabulary must
      appear on both the Python and Rust sides.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkillSecurityStatus
from app.joysafeter_domain.models.joysafeter_task import (
    JOYSAFETER_TERMINAL_STATUSES,
    JoySafeterTaskStatus,
)
from app.joysafeter_domain.services import joysafeter_skill_security as skill_security
from app.joysafeter_domain.services.joysafeter_sandbox_service import SANDBOX_STATUSES

pytestmark = pytest.mark.no_db


def _repo_root() -> Path:
    # tests/ -> backend/ ; the rust crate lives under backend/app/...
    return Path(__file__).resolve().parents[1]


def _rust_src() -> Path:
    root = _repo_root() / "app" / "joysafeter_orchestrator_rs" / "src"
    assert root.is_dir(), f"Rust orchestrator source not found at {root}"
    return root


def _rust_text() -> str:
    return "\n".join(p.read_text() for p in _rust_src().rglob("*.rs"))


# ── #1  Skill security_status single-source ──────────────────────────────


def test_skill_security_status_enum_is_the_vocabulary():
    assert {s.value for s in JoySafeterSkillSecurityStatus} == {
        "not_scanned",
        "scanning",
        "passed",
        "warning",
        "failed",
        "blocked",
    }


def test_skill_security_policy_sets_derive_from_the_enum():
    # The runtime-admission and auto-demote policy sets are the drift-dangerous
    # consumers of the vocabulary; pin them to the enum so a future rename can't
    # silently desync policy from the status values written to the DB.
    S = JoySafeterSkillSecurityStatus
    assert skill_security._RUNTIME_ALLOWED_SECURITY_STATUSES == frozenset({S.PASSED.value, S.WARNING.value})
    assert skill_security._AUTO_DEMOTE_SCAN_STATUSES == frozenset({S.FAILED.value, S.BLOCKED.value})
    # The two policy sets must partition into the enum (no stray value).
    assert (skill_security._RUNTIME_ALLOWED_SECURITY_STATUSES | skill_security._AUTO_DEMOTE_SCAN_STATUSES) <= {
        s.value for s in S
    }


# ── #2  Task status set: Python enum ↔ Rust SQL literals ─────────────────


def test_python_task_terminal_and_active_sets_partition_the_enum():
    terminal = {s.value for s in JOYSAFETER_TERMINAL_STATUSES}
    active = {s.value for s in JoySafeterTaskStatus} - terminal
    assert terminal == {"completed", "failed", "aborted", "timeout", "cancelled"}
    # The active-task guard is the exact complement of terminal.
    assert active == {"pending", "scheduling", "running"}


def test_rust_orchestrator_terminal_literal_matches_python():
    """The Rust orchestrator re-types the terminal set as a SQL ``IN (...)``
    literal (task.rs, ~10 copies). It must equal the Python terminal set. If
    Python's terminal set changes, this fails to force the Rust update."""
    rust = _rust_text()
    terminal = {s.value for s in JOYSAFETER_TERMINAL_STATUSES}
    expected = "IN (" + ", ".join(f"'{v}'" for v in ["completed", "failed", "aborted", "timeout", "cancelled"]) + ")"
    assert expected in rust, f"Rust orchestrator is missing terminal literal {expected!r}"
    # Guard: the words the Python set names are exactly the ones in the literal.
    assert terminal == {"completed", "failed", "aborted", "timeout", "cancelled"}


def test_rust_orchestrator_active_guard_literal_matches_python_complement():
    rust = _rust_text()
    active = {s.value for s in JoySafeterTaskStatus} - {s.value for s in JOYSAFETER_TERMINAL_STATUSES}
    expected = "IN (" + ", ".join(f"'{v}'" for v in ["pending", "scheduling", "running"]) + ")"
    assert expected in rust, f"Rust orchestrator is missing active-task guard {expected!r}"
    assert active == {"pending", "scheduling", "running"}


# ── #2  Sandbox status vocabulary: Python ↔ Rust co-presence ─────────────


def test_sandbox_status_vocabulary_present_on_both_sides():
    """The sandbox transition map is hand-mirrored Python↔Rust
    (``is_valid_sandbox_transition``). At minimum every sandbox status the
    Python service knows must also appear in the Rust source, so a new status
    can't be added on one side alone."""
    rust = _rust_text()
    assert "fn is_valid_sandbox_transition" in rust
    missing = sorted(status for status in SANDBOX_STATUSES if f'"{status}"' not in rust)
    assert not missing, f"Sandbox statuses defined in Python but absent from Rust source: {missing}"
