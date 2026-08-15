from pathlib import Path

import pytest
import yaml

from app.joysafeter_identity_federation.domain.errors import FederationConfigurationError
from app.joysafeter_identity_federation.domain.models import LoginMode, ProviderId
from app.joysafeter_identity_federation.infrastructure.config import compile_federation_configuration
from app.joysafeter_identity_federation.infrastructure.protocols.base import ProtocolSchemaRegistry
from app.joysafeter_identity_federation.infrastructure.protocols.schemas import (
    JD_SSO_PROTOCOL_DEFINITION,
    OAUTH2_PROTOCOL_DEFINITION,
)

pytestmark = pytest.mark.no_db


def _catalog() -> dict[str, object]:
    return {
        "providers": {
            "jd": {
                "display_name": "JD SSO",
                "icon": "building",
                "protocol": "jd_sso",
                "client_id": "${JD_CLIENT_ID}",
                "client_secret": "${JD_CLIENT_SECRET}",
                "authorize_url": "${JD_AUTHORIZE_URL}",
                "userinfo_url": "${JD_USERINFO_URL}",
                "scope": "openid email",
                "user_mapping": {
                    "id": "userId",
                    "email": "email",
                    "name": "username",
                    "avatar": "",
                },
            },
            "github": {
                "display_name": "GitHub",
                "icon": "github",
                "protocol": "oauth2",
                "template": "github",
                "client_id": "${GITHUB_CLIENT_ID}",
                "client_secret": "${GITHUB_CLIENT_SECRET}",
            },
        },
        "settings": {
            "default_redirect_url": "/managed/quickstart",
            "allow_registration": True,
            "auto_link_by_email": True,
        },
    }


def _write_catalog(tmp_path: Path, catalog: dict[str, object] | None = None) -> Path:
    path = tmp_path / "identity_federation_providers.yaml"
    path.write_text(yaml.safe_dump(catalog or _catalog(), sort_keys=False), encoding="utf-8")
    return path


def _schema_registry() -> ProtocolSchemaRegistry:
    registry = ProtocolSchemaRegistry()
    registry.register(OAUTH2_PROTOCOL_DEFINITION)
    registry.register(JD_SSO_PROTOCOL_DEFINITION)
    return registry


def _complete_env() -> dict[str, str]:
    return {
        "JD_CLIENT_ID": "jd-client",
        "JD_CLIENT_SECRET": "jd-secret",
        "JD_AUTHORIZE_URL": "https://sso.jd.com/login",
        "JD_USERINFO_URL": "https://sso.jd.com/verifyTicket",
        "GITHUB_CLIENT_ID": "github-client",
        "GITHUB_CLIENT_SECRET": "github-secret",
    }


def _github_env() -> dict[str, str]:
    return {
        "GITHUB_CLIENT_ID": "github-client",
        "GITHUB_CLIENT_SECRET": "github-secret",
    }


def _compile(
    tmp_path: Path,
    *,
    providers: str,
    login_mode: str,
    environ: dict[str, str],
    catalog: dict[str, object] | None = None,
    application_environment: str = "development",
):
    return compile_federation_configuration(
        config_path=_write_catalog(tmp_path, catalog),
        active_provider_names=providers,
        login_mode=login_mode,
        application_environment=application_environment,
        schema_registry=_schema_registry(),
        environ=environ,
    )


@pytest.mark.parametrize(
    ("providers", "login_mode", "expected_code"),
    [
        ("jd,jd", "chooser", "FEDERATION_PROVIDER_DUPLICATE"),
        ("unknown", "chooser", "FEDERATION_PROVIDER_UNKNOWN"),
        ("", "redirect", "FEDERATION_LOGIN_MODE_INVALID"),
        ("jd,github", "redirect", "FEDERATION_LOGIN_MODE_INVALID"),
        ("jd", "automatic", "FEDERATION_LOGIN_MODE_INVALID"),
    ],
)
def test_invalid_activation_contract_fails(
    providers: str, login_mode: str, expected_code: str, tmp_path: Path
) -> None:
    path = _write_catalog(tmp_path)

    with pytest.raises(FederationConfigurationError) as exc_info:
        compile_federation_configuration(
            config_path=path,
            active_provider_names=providers,
            login_mode=login_mode,
            application_environment="development",
            schema_registry=_schema_registry(),
            environ=_complete_env(),
        )

    assert expected_code in {issue.code for issue in exc_info.value.issues}


def test_empty_activation_builds_empty_registry(tmp_path: Path) -> None:
    compiled = _compile(tmp_path, providers="", login_mode="chooser", environ={})
    assert compiled.registry.list_public() == ()


def test_bundled_catalog_validates_without_activation_or_deployment_secrets() -> None:
    path = Path(__file__).resolve().parents[1] / "config" / "identity_federation_providers.yaml"

    compiled = compile_federation_configuration(
        config_path=path,
        active_provider_names="",
        login_mode="chooser",
        application_environment="development",
        schema_registry=_schema_registry(),
        environ={},
    )

    assert compiled.registry.list_public() == ()


def test_active_provider_reports_every_unresolved_environment_value(tmp_path: Path) -> None:
    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(
            tmp_path,
            providers="jd",
            login_mode="redirect",
            environ={"JD_CLIENT_ID": "client"},
        )

    assert [(issue.field, issue.code) for issue in exc_info.value.issues] == [
        ("client_secret", "FEDERATION_ENV_UNRESOLVED"),
        ("authorize_url", "FEDERATION_ENV_UNRESOLVED"),
        ("userinfo_url", "FEDERATION_ENV_UNRESOLVED"),
    ]


def test_inactive_provider_does_not_require_deployment_secrets(tmp_path: Path) -> None:
    compiled = _compile(
        tmp_path,
        providers="github",
        login_mode="chooser",
        environ=_github_env(),
    )
    assert [item.id.value for item in compiled.registry.list_public()] == ["github"]


def test_provider_order_and_registry_immutability(tmp_path: Path) -> None:
    compiled = _compile(
        tmp_path,
        providers="jd,github",
        login_mode="chooser",
        environ=_complete_env(),
    )
    assert [item.id.value for item in compiled.registry.list_public()] == ["jd", "github"]
    with pytest.raises(TypeError):
        compiled.registry.providers[ProviderId("google")] = compiled.registry.require(ProviderId("github"))


@pytest.mark.parametrize("active_providers", ["", "mystery"])
def test_unknown_protocol_is_rejected_even_when_provider_is_inactive(
    active_providers: str, tmp_path: Path
) -> None:
    catalog = _catalog()
    providers = catalog["providers"]
    assert isinstance(providers, dict)
    providers["mystery"] = {
        "display_name": "Mystery",
        "icon": "question",
        "protocol": "saml",
        "client_id": "unused",
        "client_secret": "unused",
    }

    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(
            tmp_path,
            providers=active_providers,
            login_mode="chooser",
            environ={},
            catalog=catalog,
        )

    assert [issue.code for issue in exc_info.value.issues] == ["FEDERATION_PROTOCOL_UNKNOWN"]


@pytest.mark.parametrize("active_providers", ["", "Invalid Provider"])
def test_invalid_provider_name_is_rejected_even_when_active(
    active_providers: str, tmp_path: Path
) -> None:
    catalog = _catalog()
    providers = catalog["providers"]
    assert isinstance(providers, dict)
    providers["Invalid Provider"] = {
        "display_name": "Invalid",
        "icon": "question",
        "protocol": "oauth2",
        "template": "github",
        "client_id": "unused",
        "client_secret": "unused",
    }

    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(
            tmp_path,
            providers=active_providers,
            login_mode="chooser",
            environ={},
            catalog=catalog,
        )

    assert [issue.code for issue in exc_info.value.issues] == ["FEDERATION_PROVIDER_ID_INVALID"]


def test_malformed_yaml_is_not_ignored(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("providers: [", encoding="utf-8")

    with pytest.raises(FederationConfigurationError) as exc_info:
        compile_federation_configuration(
            config_path=path,
            active_provider_names="",
            login_mode="chooser",
            application_environment="development",
            schema_registry=_schema_registry(),
            environ={},
        )

    assert [issue.code for issue in exc_info.value.issues] == ["FEDERATION_CONFIG_YAML_INVALID"]


@pytest.mark.parametrize("field", ["authorize_url", "userinfo_url"])
def test_active_provider_rejects_private_endpoints(field: str, tmp_path: Path) -> None:
    environ = _complete_env()
    environ[f"JD_{field.removesuffix('_url').upper()}_URL"] = "http://127.0.0.1/path"

    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(tmp_path, providers="jd", login_mode="chooser", environ=environ)

    assert (field, "FEDERATION_ENDPOINT_UNSAFE") in {
        (issue.field, issue.code) for issue in exc_info.value.issues
    }


def test_local_provider_allows_private_endpoints_only_in_development(tmp_path: Path) -> None:
    catalog = _catalog()
    providers = catalog["providers"]
    assert isinstance(providers, dict)
    providers["local"] = {
        "display_name": "Local",
        "icon": "key",
        "protocol": "oauth2",
        "client_id": "local-client",
        "client_secret": "local-secret",
        "authorize_url": "http://127.0.0.1:9090/authorize",
        "token_url": "http://localhost:9090/token",
        "userinfo_url": "http://[::1]:9090/userinfo",
        "scope": "openid",
        "user_mapping": {"id": "sub"},
    }

    compiled = _compile(
        tmp_path,
        providers="local",
        login_mode="redirect",
        environ={},
        catalog=catalog,
    )
    assert compiled.registry.require(ProviderId("local")).id == ProviderId("local")

    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(
            tmp_path,
            providers="local",
            login_mode="redirect",
            environ={},
            catalog=catalog,
            application_environment="production",
        )

    assert {issue.field for issue in exc_info.value.issues} == {
        "authorize_url",
        "token_url",
        "userinfo_url",
    }


def test_compiles_catalog_settings_and_template_values(tmp_path: Path) -> None:
    compiled = _compile(
        tmp_path,
        providers="github",
        login_mode="redirect",
        environ=_github_env(),
    )

    provider = compiled.registry.require(ProviderId("github"))
    assert provider.settings.authorize_url == "https://github.com/login/oauth/authorize"
    assert provider.settings.token_endpoint_auth_method == "client_secret_post"
    assert compiled.registry.settings.login_mode is LoginMode.REDIRECT
    assert compiled.registry.settings.default_redirect_url == "/managed/quickstart"


def test_registry_provider_and_nested_mappings_are_defensively_immutable(tmp_path: Path) -> None:
    catalog = _catalog()
    compiled = _compile(
        tmp_path,
        providers="github",
        login_mode="chooser",
        environ=_github_env(),
        catalog=catalog,
    )
    providers = catalog["providers"]
    assert isinstance(providers, dict)
    providers.clear()

    provider = compiled.registry.require(ProviderId("github"))
    assert provider.display_name == "GitHub"
    with pytest.raises(TypeError):
        provider.settings.user_mapping["id"] = "changed"
