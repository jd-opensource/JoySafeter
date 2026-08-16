from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...domain.models import JDSSOProviderSettings, OAuth2ProviderSettings, ProtocolId, ProviderProtocolSettings
from .base import ProtocolDefinition


def _require_nonblank(value: str | None) -> str | None:
    if value is not None and not value.strip():
        raise ValueError("Value must not be blank")
    return value


class OAuth2ConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str
    client_secret: str
    authorize_url: str | None = None
    token_url: str | None = None
    userinfo_url: str | None = None
    issuer: str | None = None
    scope: str = "openid"
    user_mapping: dict[str, str]
    token_endpoint_auth_method: Literal["client_secret_basic", "client_secret_post"] = "client_secret_basic"
    userinfo_headers: dict[str, str] = Field(default_factory=dict)

    @field_validator(
        "client_id",
        "client_secret",
        "authorize_url",
        "token_url",
        "userinfo_url",
        "issuer",
        "scope",
    )
    @classmethod
    def require_nonblank_strings(cls, value: str | None) -> str | None:
        return _require_nonblank(value)

    @model_validator(mode="after")
    def require_issuer_or_explicit_endpoints(self) -> "OAuth2ConfigSchema":
        if self.issuer is None and (self.authorize_url is None or self.token_url is None):
            raise ValueError("OAuth2 configuration requires issuer or both authorize_url and token_url")
        return self


class JDSSOConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str
    client_secret: str
    authorize_url: str
    userinfo_url: str
    scope: str = "openid"
    user_mapping: dict[str, str]

    @field_validator("client_id", "client_secret", "authorize_url", "userinfo_url", "scope")
    @classmethod
    def require_nonblank_strings(cls, value: str) -> str:
        validated = _require_nonblank(value)
        assert validated is not None
        return validated


def _to_oauth2_settings(schema: BaseModel) -> ProviderProtocolSettings:
    configuration = cast(OAuth2ConfigSchema, schema)
    return OAuth2ProviderSettings(
        client_id=configuration.client_id,
        client_secret=configuration.client_secret,
        authorize_url=configuration.authorize_url,
        token_url=configuration.token_url,
        userinfo_url=configuration.userinfo_url,
        issuer=configuration.issuer,
        scope=configuration.scope,
        user_mapping=configuration.user_mapping,
        token_endpoint_auth_method=configuration.token_endpoint_auth_method,
        userinfo_headers=configuration.userinfo_headers,
    )


def _to_jd_sso_settings(schema: BaseModel) -> ProviderProtocolSettings:
    configuration = cast(JDSSOConfigSchema, schema)
    return JDSSOProviderSettings(
        client_id=configuration.client_id,
        client_secret=configuration.client_secret,
        authorize_url=configuration.authorize_url,
        userinfo_url=configuration.userinfo_url,
        scope=configuration.scope,
        user_mapping=configuration.user_mapping,
    )


OAUTH2_PROTOCOL_DEFINITION = ProtocolDefinition(
    protocol_id=ProtocolId.OAUTH2,
    schema_type=OAuth2ConfigSchema,
    to_domain_settings=_to_oauth2_settings,
)

JD_SSO_PROTOCOL_DEFINITION = ProtocolDefinition(
    protocol_id=ProtocolId.JD_SSO,
    schema_type=JDSSOConfigSchema,
    to_domain_settings=_to_jd_sso_settings,
)
