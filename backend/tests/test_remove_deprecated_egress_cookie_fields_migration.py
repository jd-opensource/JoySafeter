from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic/versions/20260831_000001_remove_deprecated_egress_cookie_fields.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location("remove_deprecated_egress_cookie_fields", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_environment_config_removes_empty_deprecated_cookie_fields():
    migration = _migration_module()
    config = {
        "type": "cloud",
        "egress_services": [
            {
                "name": "crm",
                "base_url": "https://crm.example.com",
                "inject": {
                    "type": "cookie",
                    "credential_field": "COOKIE_HEADER",
                    "cookie_name": None,
                    "cookies": {},
                },
            },
            {
                "name": "erp",
                "base_url": "https://erp.example.com",
                "inject": None,
            },
        ],
    }

    assert migration.normalize_environment_config(config, location="environment") == {
        "type": "cloud",
        "egress_services": [
            {
                "name": "crm",
                "base_url": "https://crm.example.com",
                "inject": {
                    "type": "cookie",
                    "credential_field": "COOKIE_HEADER",
                },
            },
            {
                "name": "erp",
                "base_url": "https://erp.example.com",
                "inject": None,
            },
        ],
    }
    assert config["egress_services"][0]["inject"]["cookies"] == {}


def test_snapshot_nested_environment_config_is_normalized():
    migration = _migration_module()

    assert migration.normalize_snapshot(
        {
            "schema": "joysafeter.agent_execution_snapshot.v2",
            "environment": {
                "config": {
                    "egress_services": [
                        {
                            "name": "crm",
                            "inject": {"cookie_name": None, "cookies": {}},
                        }
                    ]
                }
            },
        },
        location="snapshot",
    ) == {
        "schema": "joysafeter.agent_execution_snapshot.v2",
        "environment": {
            "config": {
                "egress_services": [
                    {
                        "name": "crm",
                        "inject": {},
                    }
                ]
            }
        },
    }


def test_environment_config_restore_adds_deprecated_cookie_defaults():
    migration = _migration_module()

    assert migration.restore_environment_config(
        {
            "egress_services": [
                {
                    "name": "crm",
                    "inject": {
                        "type": "cookie",
                        "credential_field": "COOKIE_HEADER",
                    },
                },
                {"name": "erp", "inject": None},
            ]
        },
        location="environment",
    ) == {
        "egress_services": [
            {
                "name": "crm",
                "inject": {
                    "type": "cookie",
                    "credential_field": "COOKIE_HEADER",
                    "cookie_name": None,
                    "cookies": {},
                },
            },
            {"name": "erp", "inject": None},
        ]
    }


def test_snapshot_nested_environment_config_is_restored():
    migration = _migration_module()

    assert migration.restore_snapshot(
        {
            "environment": {
                "config": {
                    "egress_services": [
                        {
                            "name": "crm",
                            "inject": {"type": "bearer"},
                        }
                    ]
                }
            }
        },
        location="snapshot",
    ) == {
        "environment": {
            "config": {
                "egress_services": [
                    {
                        "name": "crm",
                        "inject": {
                            "type": "bearer",
                            "cookie_name": None,
                            "cookies": {},
                        },
                    }
                ]
            }
        }
    }


@pytest.mark.parametrize(
    "inject,error_path",
    [
        ({"cookie_name": "session", "cookies": {}}, "inject.cookie_name"),
        ({"cookie_name": None, "cookies": {"session": "SESSION"}}, "inject.cookies"),
    ],
)
def test_migration_fails_closed_for_nonempty_deprecated_cookie_fields(inject, error_path):
    migration = _migration_module()

    with pytest.raises(RuntimeError, match=error_path):
        migration.normalize_environment_config(
            {"egress_services": [{"name": "crm", "inject": inject}]},
            location="environment",
        )


@pytest.mark.parametrize(
    "config,error_path",
    [
        ({"egress_services": {}}, "environment.egress_services"),
        ({"egress_services": [None]}, r"environment.egress_services\[0\]"),
        ({"egress_services": [{"inject": []}]}, r"environment.egress_services\[0\].inject"),
    ],
)
def test_migration_fails_closed_for_malformed_egress_shapes(config, error_path):
    migration = _migration_module()

    with pytest.raises(RuntimeError, match=error_path):
        migration.normalize_environment_config(config, location="environment")
