"""Freeze the quickstart recommendation contract and assert the backend Pydantic
schema stays in lockstep with it. The frontend mirror asserts parity against the
same JSON, so this is the backend half of the FE/BE agreement."""

import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from app.joysafeter_domain.schemas.joysafeter_quickstart import (
    QuickstartEngineReadiness,
    QuickstartExternalToolsReason,
    QuickstartHostReason,
    QuickstartMcpAuthRequirement,
    QuickstartRecommendation,
)

pytestmark = pytest.mark.no_db

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[1] / "contracts" / "quickstart_recommendation_contract.json").read_text()
)
RECOMMENDATION_ADAPTER = TypeAdapter(QuickstartRecommendation)


def test_contract_version_frozen():
    assert CONTRACT["contract_version"] == "quickstart_recommendation.v4"


def test_phase_enum_frozen():
    assert CONTRACT["phases"] == ["understand", "secure"]


def test_pydantic_schema_matches_contract_enums():
    """Every contract enum must equal the corresponding Pydantic Literal, so the
    response model can never drift from the frozen JSON."""
    assert list(get_args(QuickstartEngineReadiness)) == CONTRACT["engine_readiness"]
    assert list(get_args(QuickstartHostReason)) == CONTRACT["host_reasons"]
    assert list(get_args(QuickstartExternalToolsReason)) == CONTRACT["external_tools_reasons"]
    assert list(get_args(QuickstartMcpAuthRequirement)) == CONTRACT["mcp_auth_requirements"]


def test_complete_pydantic_response_schema_matches_contract():
    assert RECOMMENDATION_ADAPTER.json_schema() == CONTRACT["schema"]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "phase": "understand",
            "engine": None,
            "environment": {"allowed_hosts": [], "host_reason": "none"},
        },
        {
            "phase": "secure",
            "engine": {"recommended_engine_id": None, "options": []},
            "environment": {"allowed_hosts": [], "host_reason": "none"},
            "credential_group": None,
        },
        {"phase": "design", "engine": {"recommended_engine_id": None, "options": []}},
        {"phase": "prove", "environment": {"allowed_hosts": [], "host_reason": "none"}},
    ],
)
def test_response_phase_discriminator_rejects_cross_phase_payloads(payload):
    with pytest.raises(ValidationError):
        RECOMMENDATION_ADAPTER.validate_python(payload)


@pytest.mark.parametrize(
    "engine",
    [
        {
            "recommended_engine_id": "missing",
            "options": [{"engine_id": "codex", "readiness": "ready", "compatible_connection_count": 1}],
        },
        {
            "recommended_engine_id": "codex",
            "options": [{"engine_id": "codex", "readiness": "unavailable", "compatible_connection_count": 0}],
        },
        {
            "recommended_engine_id": "codex",
            "options": [{"engine_id": "codex", "readiness": "ready", "compatible_connection_count": -1}],
        },
    ],
)
def test_understand_response_enforces_engine_plan_consistency(engine):
    with pytest.raises(ValidationError):
        RECOMMENDATION_ADAPTER.validate_python({"phase": "understand", "engine": engine})


def test_secure_response_requires_mcp_servers_when_reason_is_mcp_servers():
    with pytest.raises(ValidationError):
        RECOMMENDATION_ADAPTER.validate_python(
            {
                "phase": "secure",
                "environment": {"allowed_hosts": [], "host_reason": "none"},
                "credential_group": {
                    "mcp_servers": [],
                    "external_tools_reason": "mcpServers",
                },
            }
        )


def test_secure_response_requires_explicit_nullable_credential_group():
    with pytest.raises(ValidationError):
        RECOMMENDATION_ADAPTER.validate_python(
            {
                "phase": "secure",
                "environment": {"allowed_hosts": [], "host_reason": "none"},
            }
        )


def test_secure_response_rejects_non_http_mcp_urls():
    with pytest.raises(ValidationError):
        RECOMMENDATION_ADAPTER.validate_python(
            {
                "phase": "secure",
                "environment": {"allowed_hosts": [], "host_reason": "none"},
                "credential_group": {
                    "mcp_servers": [
                        {
                            "name": "unsafe",
                            "url": "ftp://example.com/mcp",
                            "auth_requirement": "required",
                        }
                    ],
                    "external_tools_reason": "mcpServers",
                },
            }
        )


def test_contract_does_not_expose_unwired_or_derived_fields():
    schema_text = json.dumps(CONTRACT["schema"])
    for field in ("source", "confidence", "controls", "networking_type"):
        assert f'"{field}"' not in schema_text
