"""Cross-language contract: the Python and Rust sandbox FSM transition tables
must stay identical.

The authoritative sandbox state machine lives in the Rust orchestrator
(``is_valid_sandbox_transition`` guarding ``transition_sandbox_cas``). The Python
``SandboxService`` keeps a parallel copy (``SANDBOX_TRANSITIONS``) that still
backs the API-initiated stop/destroy paths. Two hand-maintained copies of one
invariant drift silently; this test parses the Rust rules and asserts they match
the Python table so any divergence fails in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.joysafeter_domain.services.joysafeter_sandbox_service import SANDBOX_TRANSITIONS

pytestmark = pytest.mark.no_db

BACKEND_ROOT = Path(__file__).resolve().parents[1]
_RUST_SANDBOX_QUERIES = BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/db/queries/sandbox.rs"


def _rust_transitions() -> dict[str, set[str]]:
    source = _RUST_SANDBOX_QUERIES.read_text(encoding="utf-8")
    match = re.search(
        r"fn is_valid_sandbox_transition\([^)]*\)\s*->\s*bool\s*\{(?P<body>.*?)\n\}",
        source,
        re.DOTALL,
    )
    assert match is not None, "could not locate is_valid_sandbox_transition() in the Rust source"
    pairs = re.findall(r'\(\s*"(\w+)"\s*,\s*"(\w+)"\s*\)', match.group("body"))
    assert pairs, "no (from, to) transition tuples parsed from the Rust FSM"
    transitions: dict[str, set[str]] = {}
    for from_status, to_status in pairs:
        transitions.setdefault(from_status, set()).add(to_status)
    return transitions


def _python_transitions() -> dict[str, set[str]]:
    # Both languages treat ``from == to`` as always-valid via a separate early
    # return, not via the transition table, so exclude same-state edges and
    # states with no outgoing transition (Rust omits them entirely).
    result: dict[str, set[str]] = {}
    for from_status, to_statuses in SANDBOX_TRANSITIONS.items():
        outgoing = {to for to in to_statuses if to != from_status}
        if outgoing:
            result[from_status] = outgoing
    return result


def test_python_and_rust_sandbox_fsm_transition_tables_match() -> None:
    rust = _rust_transitions()
    python = _python_transitions()

    python_only = {(f, t) for f, tos in python.items() for t in tos if t not in rust.get(f, set())}
    rust_only = {(f, t) for f, tos in rust.items() for t in tos if t not in python.get(f, set())}

    assert not python_only and not rust_only, (
        "Python SANDBOX_TRANSITIONS and Rust is_valid_sandbox_transition have diverged.\n"
        f"  edges only in Python: {sorted(python_only)}\n"
        f"  edges only in Rust:   {sorted(rust_only)}"
    )
