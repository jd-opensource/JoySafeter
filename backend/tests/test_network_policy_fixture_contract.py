from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

TESTS_ROOT = Path(__file__).resolve().parent
CANONICAL_HELPER = TESTS_ROOT / "network_policy_test_helpers.py"
RAW_READY_SQL = re.compile(r"\bSET\s+networking_status\s*=\s*['\"]ready['\"]", re.IGNORECASE)


def _is_ready_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == "ready"


def _raw_ready_writes(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function_name = node.func.id if isinstance(node.func, ast.Name) else None
            attribute_name = node.func.attr if isinstance(node.func, ast.Attribute) else None
            writes_sandbox = function_name == "JoySafeterSandbox" or attribute_name == "JoySafeterSandbox"
            writes_values = attribute_name == "values"
            if writes_sandbox or writes_values:
                violations.update(
                    keyword.value.lineno
                    for keyword in node.keywords
                    if keyword.arg == "networking_status" and _is_ready_literal(keyword.value)
                )
            if writes_values:
                for argument in node.args:
                    if not isinstance(argument, ast.Dict):
                        continue
                    violations.update(
                        value.lineno
                        for key, value in zip(argument.keys, argument.values, strict=True)
                        if isinstance(key, ast.Constant)
                        and key.value == "networking_status"
                        and _is_ready_literal(value)
                    )
            if function_name == "setattr" and len(node.args) >= 3:
                attribute, value = node.args[1:3]
                if (
                    isinstance(attribute, ast.Constant)
                    and attribute.value == "networking_status"
                    and _is_ready_literal(value)
                ):
                    violations.add(node.lineno)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is not None and _is_ready_literal(value):
                violations.update(
                    target.lineno
                    for target in targets
                    if isinstance(target, ast.Attribute) and target.attr == "networking_status"
                )
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and RAW_READY_SQL.search(node.value):
            violations.add(node.lineno)
    return sorted(violations)


def test_persisted_ready_network_policy_state_uses_canonical_helper() -> None:
    violations = {
        path.relative_to(TESTS_ROOT).as_posix(): lines
        for path in TESTS_ROOT.rglob("test_*.py")
        if path != Path(__file__) and path != CANONICAL_HELPER
        if (lines := _raw_ready_writes(path))
    }

    assert violations == {}


@pytest.mark.parametrize(
    "source",
    [
        'statement.values({"networking_status": "ready"})',
        'setattr(sandbox, "networking_status", "ready")',
        "text(\"UPDATE joysafeter_sandboxes SET networking_status = 'ready'\")",
    ],
)
def test_raw_ready_write_detector_covers_indirect_persistence_forms(
    tmp_path: Path,
    source: str,
) -> None:
    source_path = tmp_path / "test_raw_ready_write.py"
    source_path.write_text(source, encoding="utf-8")

    assert _raw_ready_writes(source_path) == [1]


def test_acknowledged_network_policy_fields_are_coherent() -> None:
    helpers = importlib.import_module("tests.network_policy_test_helpers")

    fields = helpers.acknowledged_network_policy_fields(
        policy_hash="fixture-policy",
        policy_version=7,
    )

    assert fields == {
        "networking_status": "ready",
        "networking_policy_hash": "fixture-policy",
        "networking_policy_version": 7,
        "networking_applied_hash": "fixture-policy",
        "networking_applied_version": 7,
    }


@pytest.mark.parametrize(
    ("policy_hash", "policy_version"),
    [("", 1), ("fixture-policy", 0), ("fixture-policy", -1)],
)
def test_acknowledged_network_policy_fields_reject_invalid_generations(
    policy_hash: str,
    policy_version: int,
) -> None:
    helpers = importlib.import_module("tests.network_policy_test_helpers")

    with pytest.raises(ValueError):
        helpers.acknowledged_network_policy_fields(
            policy_hash=policy_hash,
            policy_version=policy_version,
        )


def test_mark_network_policy_ready_updates_the_whole_generation() -> None:
    helpers = importlib.import_module("tests.network_policy_test_helpers")

    class SandboxState:
        networking_status = "pending"
        networking_policy_hash = "old-policy"
        networking_policy_version = 3
        networking_applied_hash = None
        networking_applied_version = None

    sandbox = SandboxState()
    helpers.mark_network_policy_ready(
        sandbox,
        policy_hash="new-policy",
        policy_version=4,
    )

    assert sandbox.networking_status == "ready"
    assert sandbox.networking_policy_hash == "new-policy"
    assert sandbox.networking_policy_version == 4
    assert sandbox.networking_applied_hash == "new-policy"
    assert sandbox.networking_applied_version == 4
