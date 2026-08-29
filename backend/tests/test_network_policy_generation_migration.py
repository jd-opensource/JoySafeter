from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_shared.ids import SandboxId

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20260828_000001_harden_network_policy_state.py"
)
AUDIT_PATH = Path(__file__).resolve().parents[1] / "scripts/audit_network_policy_generations.py"


def _migration_metadata() -> dict[str, object]:
    tree = ast.parse(MIGRATION_PATH.read_text())
    metadata: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        else:
            continue
        if not isinstance(target, ast.Name) or value is None:
            continue
        if target.id in {
            "revision",
            "down_revision",
            "NETWORKING_STATUS_CONSTRAINT",
            "DESIRED_GENERATION_CONSTRAINT",
            "APPLIED_GENERATION_CONSTRAINT",
            "READY_GENERATION_CONSTRAINT",
        }:
            metadata[target.id] = ast.literal_eval(value)
    return metadata


def _audit_module():
    spec = importlib.util.spec_from_file_location("network_policy_state_audit", AUDIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _create_sandbox(db_session) -> JoySafeterSandbox:
    sandbox = JoySafeterSandbox(
        id=SandboxId.new(),
        external_id="network-policy-constraint",
        provider="docker",
        status="running",
        image="joysafeter/test:latest",
    )
    db_session.add(sandbox)
    await db_session.commit()
    return sandbox


@pytest.mark.no_db
def test_migration_declares_complete_network_policy_constraints() -> None:
    migration = _migration_metadata()

    assert migration["revision"] == "20260828_000001"
    assert migration["down_revision"] == "20260825_000005"
    assert migration["NETWORKING_STATUS_CONSTRAINT"] == "ck_sandbox_networking_status"
    assert migration["DESIRED_GENERATION_CONSTRAINT"] == "ck_sandbox_desired_network_policy_generation"
    assert migration["APPLIED_GENERATION_CONSTRAINT"] == "ck_sandbox_applied_network_policy_generation"
    assert migration["READY_GENERATION_CONSTRAINT"] == "ck_sandbox_ready_network_policy_generation"


@pytest.mark.no_db
def test_audit_classifies_invalid_ready_and_unknown_status() -> None:
    audit = _audit_module()

    assert audit.classify_network_policy_state(
        {
            "networking_status": "ready",
            "networking_policy_hash": None,
            "networking_policy_version": 0,
            "networking_applied_hash": None,
            "networking_applied_version": 0,
        }
    ) == ("invalid_desired_generation", "invalid_applied_generation", "invalid_ready_generation")
    assert audit.classify_network_policy_state(
        {
            "networking_status": "mystery",
            "networking_policy_hash": None,
            "networking_policy_version": 0,
            "networking_applied_hash": None,
            "networking_applied_version": None,
        }
    ) == ("unknown_status",)


@pytest.mark.asyncio
async def test_ready_requires_non_null_positive_exact_generation(db_session) -> None:
    sandbox = await _create_sandbox(db_session)

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "UPDATE joysafeter_sandboxes "
                "SET networking_status = :status, "
                "networking_policy_hash = NULL, networking_policy_version = 0, "
                "networking_applied_hash = NULL, networking_applied_version = 0 "
                "WHERE id = :sandbox_id"
            ),
            {"sandbox_id": sandbox.id.uuid, "status": "ready"},
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_unknown_networking_status_is_rejected(db_session) -> None:
    sandbox = await _create_sandbox(db_session)

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "UPDATE joysafeter_sandboxes "
                "SET networking_status = 'mystery' WHERE id = :sandbox_id"
            ),
            {"sandbox_id": sandbox.id.uuid},
        )
        await db_session.commit()
