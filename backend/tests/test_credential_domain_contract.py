import json
from collections import Counter
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


def test_mcp_auth_contract_is_canonical_only(credential_contract: dict):
    assert credential_contract["auth_schemes"] == [
        "static_bearer",
        "header_api_key",
        "custom_header",
    ]
    assert "auth_scheme_aliases" not in credential_contract
    assert credential_contract["disabled_auth_schemes"] == ["oauth", "mcp_oauth"]


def test_runtime_errors_and_versioned_envelopes_are_frozen(credential_contract: dict):
    assert credential_contract["contract_version"] == 3
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
    assert credential_contract["encryption_envelopes"] == {
        "legacy_read": ["enc:", "enc:v1:"],
        "current_write": "enc:v2:<key_id>:",
        "v2_authenticated_associated_data": "enc:v2:<key_id>:",
        "startup_requires_all_referenced_read_keys": True,
    }


def test_reference_contract_freezes_snapshot_versions_and_key_aliases(reference_contract: dict):
    assert reference_contract["contract_version"] == 3
    assert reference_contract["snapshot_schemas"] == {"v2": "joysafeter.agent_execution_snapshot.v2"}
    assert reference_contract["canonical_reference_keys"] == [
        "model_credential_id",
        "environment_credential_ids",
        "credential_ref",
        "credential_field",
    ]
    assert reference_contract["legacy_aliases"] == {}
    assert reference_contract["legacy_decoder_keys"] == []
    assert reference_contract["normalization"] == {"inject_type": "trim_lowercase"}
    paths = reference_contract["reference_paths"]
    assert len(paths) == 13
    assert all(
        set(entry) == {"schemas", "document", "path", "value_kind", "surface", "scanner_fixture"} for entry in paths
    )
    assert Counter(entry["value_kind"] for entry in paths) == {
        "credential_id": 10,
        "credential_field": 3,
    }
    assert len({entry["scanner_fixture"] for entry in paths}) == len(paths)
    assert all(entry["surface"] in reference_contract["consumer_surfaces"] for entry in paths)


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
        "credential_group_member_ownership",
    ]
    assert reference_contract["error_categories"] == {"unknown_explicit_schema": "corrupt_record"}
    assert reference_contract["test_vectors"][-1] == {
        "name": "unknown_explicit_schema_fails_closed",
        "schema": "joysafeter.agent_execution_snapshot.v3",
        "result": "corrupt_record",
    }
    assert reference_contract["parity_vectors"][-1] == {
        "name": "unknown_explicit_schema",
        "category": "unknown_schema",
        "document": "agent_version_snapshot",
        "input": {"schema": "joysafeter.agent_execution_snapshot.v3"},
        "result": "corrupt_record",
    }
