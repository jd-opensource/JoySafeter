import pytest
from pydantic import ValidationError

from app.joysafeter_domain.schemas.joysafeter_environment import EnvironmentConfig

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
