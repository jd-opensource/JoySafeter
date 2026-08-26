import pytest
from pydantic import ValidationError

from app.joysafeter_domain.schemas.joysafeter_environment import (
    CreateEnvironmentRequest,
    EnvironmentConfig,
    EnvironmentCredentialReference,
    UpdateEnvironmentRequest,
    extract_environment_credential_references,
)
from app.joysafeter_shared.ids import CredentialId

pytestmark = pytest.mark.no_db

# Stable service-credential ids used across the schema-level tests. Egress refs
# and env-var environment_credential_ids are id-based (kind='service' credentials) after the
# Unified Credential P0 cutover.
_CRM_CRED = CredentialId.new()
_ERP_CRED = CredentialId.new()
_LEGACY_CRED = CredentialId.new()


def test_environment_egress_service_accepts_bearer_api_key_and_cookie_shapes():
    config = EnvironmentConfig(
        egress_services=[
            {
                "name": "CRM_Prod",
                "base_url": "https://crm.example.com/api/",
                "credential_ref": str(_CRM_CRED),
                "inject": {"type": "bearer", "credential_field": "ACCESS_TOKEN"},
            },
            {
                "name": "erp",
                "base_url": "http://erp.internal/openapi",
                "credential_ref": str(_ERP_CRED),
                "inject": {"type": "api_key", "header": "x-api-key", "credential_field": "API_KEY"},
            },
            {
                "name": "legacy-cookie",
                "base_url": "https://legacy.example.com/",
                "credential_ref": str(_LEGACY_CRED),
                "inject": {"type": "cookie", "credential_field": "COOKIE_HEADER"},
            },
        ]
    )

    assert [service.name for service in config.egress_services] == ["crm_prod", "erp", "legacy-cookie"]
    assert config.egress_services[2].inject.credential_field == "COOKIE_HEADER"
    assert config.egress_services[0].credential_ref == _CRM_CRED


@pytest.mark.parametrize(
    "service",
    [
        {
            "name": "bad host",
            "base_url": "https://crm.example.com/api/",
            "credential_ref": str(_CRM_CRED),
        },
        {
            "name": "crm",
            "base_url": "ftp://crm.example.com/api/",
            "credential_ref": str(_CRM_CRED),
        },
        {
            "name": "crm",
            "base_url": "https://user:pass@crm.example.com/api/",
            "credential_ref": str(_CRM_CRED),
        },
        {
            "name": "crm",
            "base_url": "https://crm.example.com/api/",
            "credential_ref": "",
        },
        {
            "name": "crm",
            "base_url": "https://crm.example.com/api/",
            "credential_ref": "not-a-credential-id",
        },
        {
            "name": "crm",
            "base_url": "https://crm.example.com/api/",
            "credential_ref": str(_CRM_CRED),
            "exposure": "transparent",
        },
        {
            "name": "crm",
            "base_url": "https://crm.example.com/api/",
            "credential_ref": str(_CRM_CRED),
            "inject": {"type": "cookie", "cookie_name": "SESSION"},
        },
        {
            "name": "crm",
            "base_url": "https://crm.example.com/api/",
            "credential_ref": str(_CRM_CRED),
            "inject": {"type": "cookie", "cookies": {"SESSION": "SESSION"}},
        },
    ],
)
def test_environment_egress_service_rejects_invalid_shapes(service):
    with pytest.raises(ValidationError):
        EnvironmentConfig(egress_services=[service])


def test_environment_egress_service_requires_credential_id():
    with pytest.raises(ValidationError):
        EnvironmentConfig(
            egress_services=[
                {
                    "name": "crm",
                    "base_url": "https://crm.example.com/api/",
                }
            ]
        )


def test_environment_egress_service_rejects_duplicate_names():
    with pytest.raises(ValidationError):
        EnvironmentConfig(
            egress_services=[
                {
                    "name": "crm",
                    "base_url": "https://crm.example.com/api/",
                    "credential_ref": str(_CRM_CRED),
                },
                {
                    "name": "CRM",
                    "base_url": "https://crm2.example.com/api/",
                    "credential_ref": str(_ERP_CRED),
                },
            ]
        )


def test_extract_environment_credential_references_unifies_direct_and_egress_refs():
    direct_id = CredentialId.new()
    egress_id = CredentialId.new()
    config = EnvironmentConfig(
        environment_credential_ids=[str(direct_id), str(direct_id)],
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com",
                "credential_ref": str(egress_id),
            },
            {
                "name": "shared-service",
                "base_url": "https://shared.example.com",
                "credential_ref": str(direct_id),
            },
        ],
    )

    assert extract_environment_credential_references(config) == [
        EnvironmentCredentialReference(
            direct_id,
            "environment_credential_ids",
            0,
            "environment_credential_ids[0]",
        ),
        EnvironmentCredentialReference(egress_id, "egress_services", 0, "egress_services[0]"),
        EnvironmentCredentialReference(direct_id, "egress_services", 1, "egress_services[1]"),
    ]


def test_extract_environment_credential_references_rejects_legacy_malformed_config():
    with pytest.raises(ValueError, match="corrupt_record"):
        extract_environment_credential_references(
            {
                "environment_credential_ids": ["", None, str(CredentialId.new()), "not-an-id"],
                "egress_services": [
                    None,
                    "invalid",
                    {"credential_ref": str(CredentialId.new())},
                    {},
                ],
            }
        )


@pytest.mark.parametrize(
    ("request_model", "request_data"),
    [
        (CreateEnvironmentRequest, {"name": "blank-create-ref"}),
        (UpdateEnvironmentRequest, {}),
    ],
)
def test_environment_requests_reject_blank_direct_environment_credential_ids(request_model, request_data):
    with pytest.raises(ValidationError):
        request_model(**request_data, config={"environment_credential_ids": ["   "]})
