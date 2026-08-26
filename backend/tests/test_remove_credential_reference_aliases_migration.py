from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic/versions/20260825_000001_remove_credential_reference_aliases.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location("remove_credential_reference_aliases", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CREDENTIAL_A = "cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f010"
CREDENTIAL_B = "cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f011"
GROUP_A = "credgrp_018f6f42-0a51-7cc4-98c8-4f6f0ca5f012"


def test_environment_aliases_rewrite_to_canonical_keys():
    migration = _migration_module()
    assert migration.canonicalize_environment_config(
        {
            "secret_refs": [CREDENTIAL_A, CREDENTIAL_A],
            "service_credential_id": CREDENTIAL_B,
            "egress_services": [
                {
                    "base_url": "https://example.com",
                    "service_credential_id": CREDENTIAL_A,
                    "inject": {"type": "bearer", "secret_key": "TOKEN"},
                }
            ],
        },
        location="env",
    ) == {
        "environment_credential_ids": [CREDENTIAL_A, CREDENTIAL_B],
        "egress_services": [
            {
                "base_url": "https://example.com",
                "credential_ref": CREDENTIAL_A,
                "inject": {"type": "bearer", "credential_field": "TOKEN"},
            }
        ],
    }


def test_snapshot_aliases_rewrite_and_nested_environment_is_canonical():
    migration = _migration_module()
    assert migration.canonicalize_snapshot(
        {
            "secret_ref": CREDENTIAL_A,
            "secret_refs": [CREDENTIAL_B],
            "vault_ids": [GROUP_A, GROUP_A],
            "environment": {"config": {"secret_refs": [CREDENTIAL_A]}},
        },
        location="snapshot",
    ) == {
        "schema": "joysafeter.agent_execution_snapshot.v2",
        "model_credential_id": CREDENTIAL_A,
        "environment_credential_ids": [CREDENTIAL_B],
        "credential_group_ids": [GROUP_A],
        "environment": {"config": {"environment_credential_ids": [CREDENTIAL_A]}},
    }


@pytest.mark.parametrize(
    "kind,value",
    [
        ("snapshot", None),
        ("snapshot", []),
        ("snapshot", {"secret_ref": 7}),
        ("snapshot", {"secret_refs": ["not-an-id"]}),
        ("snapshot", {"vault_ids": [CREDENTIAL_A]}),
        ("snapshot", {"model_credential_id": CREDENTIAL_A, "secret_ref": CREDENTIAL_B}),
        ("environment", {"egress_services": [{"credential_ref": CREDENTIAL_A, "service_credential_id": CREDENTIAL_B}]}),
    ],
)
def test_migration_fails_closed_for_malformed_or_conflicting_values(kind, value):
    migration = _migration_module()
    with pytest.raises(RuntimeError):
        if kind == "environment":
            migration.canonicalize_environment_config(value, location="env")
        else:
            migration.canonicalize_snapshot(value, location="snapshot")
