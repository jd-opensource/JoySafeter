import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.no_db

_CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "contracts"


@pytest.fixture
def credential_contract() -> dict:
    return json.loads((_CONTRACTS_DIR / "credential_domain_contract.json").read_text())


@pytest.fixture
def reference_contract() -> dict:
    return json.loads((_CONTRACTS_DIR / "credential_reference_contract.json").read_text())


def test_model_is_only_model_credential_kind(credential_contract: dict):
    assert credential_contract["credential_kinds"] == ["model", "service", "mcp"]
    assert "llm" not in credential_contract["credential_kinds"]


def test_only_reviewed_legacy_auth_alias_exists(credential_contract: dict):
    assert credential_contract["auth_schemes"] == ["static_bearer"]
    assert credential_contract["auth_scheme_aliases"] == {"bearer": "static_bearer"}
    assert credential_contract["disabled_auth_schemes"] == ["oauth", "mcp_oauth"]


def test_runtime_errors_and_v1_envelope_are_frozen(credential_contract: dict):
    assert credential_contract["runtime_errors"] == [
        "not_bound",
        "not_found",
        "archived",
        "project_mismatch",
        "kind_mismatch",
        "field_missing",
        "unsupported_scheme",
        "corrupt_record",
        "envelope_invalid",
    ]
    assert credential_contract["encryption_envelope"] == "enc:v1"


def test_reference_contract_freezes_snapshot_versions_and_key_aliases(reference_contract: dict):
    assert reference_contract["snapshot_schemas"] == {
        "legacy_v0": None,
        "v1": "joysafeter.agent_execution_snapshot.v1",
        "v2": "joysafeter.agent_execution_snapshot.v2",
    }
    assert reference_contract["canonical_reference_keys"] == [
        "model_credential_id",
        "environment_credential_ids",
        "service_credential_id",
        "credential_field",
    ]
    assert reference_contract["legacy_aliases"] == {
        "model_credential_id": ["secret_ref"],
        "environment_credential_ids": ["secret_refs"],
        "credential_field": ["secret_key"],
    }
    assert reference_contract["legacy_decoder_keys"] == [
        "secret_ref",
        "secret_refs",
        "service_credential_id",
        "secret_key",
    ]


def test_reference_contract_includes_consumer_surfaces_and_fail_closed_vector(reference_contract: dict):
    assert reference_contract["consumer_surfaces"] == [
        "live_agent_model_binding",
        "agent_version_executable_snapshot",
        "trigger_webhook_auth_binding",
        "live_environment_direct_injection",
        "live_environment_http_egress_binding",
        "active_session_model_environment_snapshot",
        "session_credential_group_association",
        "quickstart_model_inference",
        "skill_ai_authoring_model_inference",
        "legacy_v0_v1_environment_snapshot",
    ]
    assert reference_contract["error_categories"] == {
        "unknown_explicit_schema": "corrupt_record"
    }
    assert reference_contract["test_vectors"][-1] == {
        "name": "unknown_explicit_schema_fails_closed",
        "schema": "joysafeter.agent_execution_snapshot.v3",
        "result": "corrupt_record",
    }
