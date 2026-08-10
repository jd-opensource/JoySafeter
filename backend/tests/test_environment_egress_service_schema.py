import pytest
from pydantic import ValidationError

from app.joysafeter_domain.schemas.joysafeter_environment import (
    CreateEnvironmentRequest,
    EnvironmentConfig,
    EnvironmentSecretReference,
    UpdateEnvironmentRequest,
    extract_environment_secret_references,
)

pytestmark = pytest.mark.no_db


def test_environment_egress_service_accepts_bearer_api_key_and_cookie_shapes():
    config = EnvironmentConfig(
        egress_services=[
            {
                "name": "CRM_Prod",
                "base_url": "https://crm.example.com/api/",
                "credential_ref": "crm-prod",
                "inject": {"type": "bearer", "secret_key": "ACCESS_TOKEN"},
            },
            {
                "name": "erp",
                "base_url": "http://erp.internal/openapi",
                "credential_ref": "erp-prod",
                "inject": {"type": "api_key", "header": "x-api-key", "secret_key": "API_KEY"},
            },
            {
                "name": "legacy-cookie",
                "base_url": "https://legacy.example.com/",
                "credential_ref": "legacy-prod",
                "inject": {"type": "cookie", "secret_key": "COOKIE_HEADER"},
            },
        ]
    )

    assert [service.name for service in config.egress_services] == ["crm_prod", "erp", "legacy-cookie"]
    assert config.egress_services[2].inject.secret_key == "COOKIE_HEADER"


@pytest.mark.parametrize(
    "service",
    [
        {
            "name": "bad host",
            "base_url": "https://crm.example.com/api/",
            "credential_ref": "crm-prod",
        },
        {
            "name": "crm",
            "base_url": "ftp://crm.example.com/api/",
            "credential_ref": "crm-prod",
        },
        {
            "name": "crm",
            "base_url": "https://user:pass@crm.example.com/api/",
            "credential_ref": "crm-prod",
        },
        {
            "name": "crm",
            "base_url": "https://crm.example.com/api/",
            "credential_ref": "",
        },
        {
            "name": "crm",
            "base_url": "https://crm.example.com/api/",
            "credential_ref": "crm-prod",
            "exposure": "transparent",
        },
        {
            "name": "crm",
            "base_url": "https://crm.example.com/api/",
            "credential_ref": "crm-prod",
            "inject": {"type": "cookie", "cookie_name": "SESSION"},
        },
        {
            "name": "crm",
            "base_url": "https://crm.example.com/api/",
            "credential_ref": "crm-prod",
            "inject": {"type": "cookie", "cookies": {"SESSION": "SESSION"}},
        },
    ],
)
def test_environment_egress_service_rejects_invalid_shapes(service):
    with pytest.raises(ValidationError):
        EnvironmentConfig(egress_services=[service])


def test_environment_egress_service_rejects_duplicate_names():
    with pytest.raises(ValidationError):
        EnvironmentConfig(
            egress_services=[
                {
                    "name": "crm",
                    "base_url": "https://crm.example.com/api/",
                    "credential_ref": "crm-prod",
                },
                {
                    "name": "CRM",
                    "base_url": "https://crm2.example.com/api/",
                    "credential_ref": "crm-prod-2",
                },
            ]
        )


def test_extract_environment_secret_references_unifies_direct_and_egress_refs():
    config = EnvironmentConfig(
        secret_refs=["shared", " direct-only ", "shared"],
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com",
                "credential_ref": "egress-only",
            },
            {
                "name": "shared-service",
                "base_url": "https://shared.example.com",
                "credential_ref": "shared",
            },
        ],
    )

    assert extract_environment_secret_references(config) == [
        EnvironmentSecretReference("shared", "secret_refs"),
        EnvironmentSecretReference("direct-only", "secret_refs"),
        EnvironmentSecretReference("egress-only", "egress_services"),
    ]


def test_extract_environment_secret_references_tolerates_legacy_malformed_config():
    assert extract_environment_secret_references(
        {
            "secret_refs": ["", None, " direct "],
            "egress_services": [None, "invalid", {"credential_ref": " egress "}, {}],
        }
    ) == [
        EnvironmentSecretReference("direct", "secret_refs"),
        EnvironmentSecretReference("egress", "egress_services"),
    ]


@pytest.mark.parametrize(
    ("request_model", "request_data"),
    [
        (CreateEnvironmentRequest, {"name": "blank-create-ref"}),
        (UpdateEnvironmentRequest, {}),
    ],
)
def test_environment_requests_reject_blank_direct_secret_refs(request_model, request_data):
    with pytest.raises(ValidationError, match="secret_refs entries must not be blank"):
        request_model(**request_data, config={"secret_refs": ["   "]})
