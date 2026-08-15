import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from app.joysafeter_identity_federation.domain.errors import FederationConfigurationError
from app.joysafeter_identity_federation.domain.models import (
    CorrelationMethod,
    JDSSOProviderSettings,
    ProtocolId,
)
from app.joysafeter_identity_federation.infrastructure.protocols.base import (
    ProtocolAdapterRegistry,
    ProtocolDefinition,
    ProtocolSchemaRegistry,
)
from app.joysafeter_identity_federation.infrastructure.protocols.schemas import (
    JD_SSO_PROTOCOL_DEFINITION,
    JDSSOConfigSchema,
    OAuth2ConfigSchema,
)

pytestmark = pytest.mark.no_db


class _FakeConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str


class _FakeProtocolDefinition:
    protocol_id = ProtocolId.OAUTH2
    schema_type = _FakeConfigSchema

    @staticmethod
    def to_domain_settings(schema: _FakeConfigSchema) -> JDSSOProviderSettings:
        return JDSSOProviderSettings(
            client_id=schema.client_id,
            client_secret="fake-secret",
            authorize_url="https://id.example.com/authorize",
            userinfo_url="https://id.example.com/userinfo",
            scope="openid",
            user_mapping={"id": "sub"},
        )


class _FakeProtocolAdapter:
    protocol_id = ProtocolId.JD_SSO
    correlation_method = CorrelationMethod.SIGNED_COOKIE


def test_unknown_protocol_never_falls_back() -> None:
    registry = ProtocolSchemaRegistry()

    with pytest.raises(FederationConfigurationError) as exc_info:
        registry.require("saml")

    assert exc_info.value.issues[0].code == "FEDERATION_PROTOCOL_UNKNOWN"


def test_duplicate_protocol_registration_fails() -> None:
    registry = ProtocolSchemaRegistry()
    registry.register(_FakeProtocolDefinition())

    with pytest.raises(RuntimeError, match="already registered"):
        registry.register(_FakeProtocolDefinition())


def test_jd_schema_does_not_require_token_url() -> None:
    parsed = JDSSOConfigSchema.model_validate(
        {
            "client_id": "jd-client",
            "client_secret": "jd-secret",
            "authorize_url": "https://sso.jd.com/login",
            "userinfo_url": "https://sso.jd.com/verifyTicket",
            "scope": "openid email",
            "user_mapping": {"id": "userId", "email": "email", "name": "username", "avatar": ""},
        }
    )

    assert parsed.client_id == "jd-client"


def test_jd_schema_forbids_token_url() -> None:
    with pytest.raises(ValidationError):
        JDSSOConfigSchema.model_validate(
            {
                "client_id": "jd-client",
                "client_secret": "jd-secret",
                "authorize_url": "https://sso.jd.com/login",
                "userinfo_url": "https://sso.jd.com/verifyTicket",
                "scope": "openid email",
                "user_mapping": {"id": "userId"},
                "token_url": "https://sso.jd.com/token",
            }
        )


def test_oauth2_schema_requires_issuer_or_explicit_authorize_and_token_urls() -> None:
    base_configuration = {
        "client_id": "oauth-client",
        "client_secret": "oauth-secret",
        "scope": "openid",
        "user_mapping": {"id": "sub"},
    }

    with pytest.raises(ValidationError):
        OAuth2ConfigSchema.model_validate(base_configuration)

    issuer_configuration = {**base_configuration, "issuer": "https://id.example.com"}
    endpoint_configuration = {
        **base_configuration,
        "authorize_url": "https://id.example.com/authorize",
        "token_url": "https://id.example.com/token",
    }

    assert OAuth2ConfigSchema.model_validate(issuer_configuration).issuer == "https://id.example.com"
    assert OAuth2ConfigSchema.model_validate(endpoint_configuration).token_url == "https://id.example.com/token"


def test_oauth2_schema_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        OAuth2ConfigSchema.model_validate(
            {
                "client_id": "oauth-client",
                "client_secret": "oauth-secret",
                "issuer": "https://id.example.com",
                "scope": "openid",
                "user_mapping": {"id": "sub"},
                "unexpected": "value",
            }
        )


def test_schema_registry_validates_configuration_without_runtime_adapter() -> None:
    schema_registry = ProtocolSchemaRegistry()
    schema_registry.register(JD_SSO_PROTOCOL_DEFINITION)
    adapter_registry = ProtocolAdapterRegistry()

    settings = schema_registry.validate_configuration(
        ProtocolId.JD_SSO,
        {
            "client_id": "jd-client",
            "client_secret": "jd-secret",
            "authorize_url": "https://sso.jd.com/login",
            "userinfo_url": "https://sso.jd.com/verifyTicket",
            "scope": "openid email",
            "user_mapping": {"id": "userId"},
        },
    )

    assert isinstance(settings, JDSSOProviderSettings)
    with pytest.raises(FederationConfigurationError) as exc_info:
        adapter_registry.require(ProtocolId.JD_SSO)
    assert exc_info.value.issues[0].code == "FEDERATION_PROTOCOL_UNKNOWN"


def test_adapter_registry_resolves_only_registered_runtime_adapter() -> None:
    registry = ProtocolAdapterRegistry()
    adapter = _FakeProtocolAdapter()
    registry.register(adapter)

    assert registry.require(ProtocolId.JD_SSO) is adapter
    with pytest.raises(FederationConfigurationError):
        registry.require(ProtocolId.OAUTH2)


def test_protocol_definition_is_explicit_about_schema_and_settings_conversion() -> None:
    definition = ProtocolDefinition(
        protocol_id=ProtocolId.JD_SSO,
        schema_type=JDSSOConfigSchema,
        to_domain_settings=JD_SSO_PROTOCOL_DEFINITION.to_domain_settings,
    )

    assert definition.protocol_id is ProtocolId.JD_SSO
