import socket
import traceback
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import yaml

from app.joysafeter_identity_federation.domain.errors import FederationConfigurationError, FederationError
from app.joysafeter_identity_federation.domain.models import LoginMode, ProviderId
from app.joysafeter_identity_federation.infrastructure import config as config_module
from app.joysafeter_identity_federation.infrastructure.config import compile_federation_configuration
from app.joysafeter_identity_federation.infrastructure.protocols.base import ProtocolSchemaRegistry
from app.joysafeter_identity_federation.infrastructure.protocols.schemas import (
    JD_SSO_PROTOCOL_DEFINITION,
    OAUTH2_PROTOCOL_DEFINITION,
)

pytestmark = pytest.mark.no_db


@pytest.fixture(autouse=True)
def _use_deterministic_endpoint_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(hostname: str, _port: int) -> tuple[str, ...]:
        if hostname == "localhost" or hostname.endswith(".localhost"):
            return ("127.0.0.1", "::1")
        return ("93.184.216.34",)

    monkeypatch.setattr(config_module, "_resolve_endpoint_addresses", resolve, raising=False)


def _catalog() -> dict[str, object]:
    return {
        "version": 1,
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


def _compile_local_provider(tmp_path: Path, *, environment: str):
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
    return _compile(
        tmp_path,
        providers="local",
        login_mode="redirect",
        environ={},
        catalog=catalog,
        application_environment=environment,
    )


@pytest.mark.parametrize(
    ("providers", "login_mode", "expected_code"),
    [
        ("jd,jd", "chooser", "FEDERATION_PROVIDER_DUPLICATE"),
        ("unknown", "chooser", "FEDERATION_PROVIDER_UNKNOWN"),
        ("", "redirect", "FEDERATION_LOGIN_MODE_INVALID"),
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


def test_redirect_uses_first_of_multiple_active_providers(tmp_path: Path) -> None:
    compiled = _compile(
        tmp_path,
        providers="jd,github",
        login_mode="redirect",
        environ=_complete_env(),
    )

    public_providers = compiled.registry.list_public()
    assert compiled.registry.settings.login_mode is LoginMode.REDIRECT
    assert [provider.id.value for provider in public_providers] == ["jd", "github"]
    assert public_providers[0].id == ProviderId("jd")


@pytest.mark.parametrize(
    ("providers", "expected_fields"),
    [
        (",jd", ["providers[0]"]),
        ("jd,,github", ["providers[1]"]),
        ("jd,", ["providers[1]"]),
        (",", ["providers[0]", "providers[1]"]),
    ],
)
def test_activation_empty_segments_are_rejected_in_order(
    providers: str,
    expected_fields: list[str],
    tmp_path: Path,
) -> None:
    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(
            tmp_path,
            providers=providers,
            login_mode="chooser",
            environ=_complete_env(),
        )

    assert [(issue.field, issue.code) for issue in exc_info.value.issues] == [
        (field, "FEDERATION_PROVIDER_EMPTY") for field in expected_fields
    ]


def test_empty_activation_builds_empty_registry(tmp_path: Path) -> None:
    compiled = _compile(tmp_path, providers="", login_mode="chooser", environ={})
    assert compiled.registry.list_public() == ()


def test_catalog_accepts_exact_version_one(tmp_path: Path) -> None:
    catalog = _catalog()
    catalog["version"] = 1

    compiled = _compile(
        tmp_path,
        providers="",
        login_mode="chooser",
        environ={},
        catalog=catalog,
    )

    assert compiled.registry.list_public() == ()


def test_catalog_requires_a_version(tmp_path: Path) -> None:
    catalog = _catalog()
    catalog.pop("version")

    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(
            tmp_path,
            providers="",
            login_mode="chooser",
            environ={},
            catalog=catalog,
        )

    assert [(issue.field, issue.code) for issue in exc_info.value.issues] == [
        ("version", "FEDERATION_CONFIG_INVALID")
    ]


@pytest.mark.parametrize("version", [2, "1", True, 1.0])
def test_catalog_rejects_unsupported_or_mistyped_versions(version: object, tmp_path: Path) -> None:
    catalog = _catalog()
    catalog["version"] = version

    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(
            tmp_path,
            providers="",
            login_mode="chooser",
            environ={},
            catalog=catalog,
        )

    assert [(issue.field, issue.code) for issue in exc_info.value.issues] == [
        ("version", "FEDERATION_CONFIG_INVALID")
    ]


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


@pytest.mark.parametrize(
    ("environment_name", "value", "expected_field"),
    [
        ("GITHUB_CLIENT_ID", "", "client_id"),
        ("GITHUB_CLIENT_SECRET", "   ", "client_secret"),
        ("GITHUB_CLIENT_SECRET", "${SECOND_ORDER_SECRET}", "client_secret"),
        ("GITHUB_CLIENT_SECRET", "prefix-${SECOND_ORDER_SECRET}", "client_secret"),
    ],
)
def test_active_environment_values_must_be_concrete_and_nonblank(
    environment_name: str,
    value: str,
    expected_field: str,
    tmp_path: Path,
) -> None:
    environ = _github_env()
    environ[environment_name] = value

    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(
            tmp_path,
            providers="github",
            login_mode="chooser",
            environ=environ,
        )

    assert [(issue.field, issue.code) for issue in exc_info.value.issues] == [
        (expected_field, "FEDERATION_ENV_UNRESOLVED")
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


@pytest.mark.parametrize("attribute", ["settings", "_providers"])
def test_registry_rejects_attribute_reassignment(attribute: str, tmp_path: Path) -> None:
    compiled = _compile(
        tmp_path,
        providers="github",
        login_mode="chooser",
        environ=_github_env(),
    )

    with pytest.raises(FrozenInstanceError):
        setattr(compiled.registry, attribute, getattr(compiled.registry, attribute))


def test_registry_missing_provider_raises_runtime_domain_error(tmp_path: Path) -> None:
    compiled = _compile(
        tmp_path,
        providers="github",
        login_mode="chooser",
        environ=_github_env(),
    )

    with pytest.raises(FederationError) as exc_info:
        compiled.registry.require(ProviderId("google"))

    assert exc_info.value.code == "FEDERATION_PROVIDER_NOT_ACTIVE"


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


def test_missing_catalog_uses_configuration_error_model(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.yaml"

    with pytest.raises(FederationConfigurationError) as exc_info:
        compile_federation_configuration(
            config_path=missing_path,
            active_provider_names="",
            login_mode="chooser",
            application_environment="development",
            schema_registry=_schema_registry(),
            environ={},
        )

    assert [(issue.field, issue.code) for issue in exc_info.value.issues] == [
        ("file", "FEDERATION_CONFIG_NOT_FOUND")
    ]


def test_yaml_diagnostics_do_not_expose_source_values(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("client_secret: [yaml-client-secret", encoding="utf-8")

    with pytest.raises(FederationConfigurationError) as exc_info:
        compile_federation_configuration(
            config_path=path,
            active_provider_names="",
            login_mode="chooser",
            application_environment="development",
            schema_registry=_schema_registry(),
            environ={},
        )

    rendered = str(exc_info.value)
    diagnostic = "".join(traceback.format_exception(exc_info.value))
    assert "yaml-client-secret" not in diagnostic
    assert str(path) not in diagnostic
    assert exc_info.value.__cause__ is None
    assert "line 1" in rendered
    assert "column" in rendered


def test_schema_diagnostics_do_not_expose_catalog_values(tmp_path: Path) -> None:
    catalog = _catalog()
    providers = catalog["providers"]
    assert isinstance(providers, dict)
    github = providers["github"]
    assert isinstance(github, dict)
    github["client_secret"] = "catalog-client-secret"
    catalog.pop("settings")
    path = _write_catalog(tmp_path, catalog)

    with pytest.raises(FederationConfigurationError) as exc_info:
        compile_federation_configuration(
            config_path=path,
            active_provider_names="",
            login_mode="chooser",
            application_environment="development",
            schema_registry=_schema_registry(),
            environ={},
        )

    diagnostic = "".join(traceback.format_exception(exc_info.value))
    assert "catalog-client-secret" not in diagnostic
    assert exc_info.value.__cause__ is None


@pytest.mark.parametrize(
    "value",
    [
        "not-a-url",
        "ftp://identity.example.com/authorize",
        "https://identity.example.com:70000/authorize",
        r"http://127.0.0.1\@example.com/authorize",
        "http://./",
        "http://faß.example/authorize",
        "${INVALID-NAME}",
    ],
)
def test_inactive_catalog_rejects_invalid_endpoint_syntax(value: str, tmp_path: Path) -> None:
    catalog = _catalog()
    providers = catalog["providers"]
    assert isinstance(providers, dict)
    jd = providers["jd"]
    assert isinstance(jd, dict)
    jd["authorize_url"] = value

    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(
            tmp_path,
            providers="",
            login_mode="chooser",
            environ={},
            catalog=catalog,
        )

    assert [(issue.field, issue.code) for issue in exc_info.value.issues] == [
        ("authorize_url", "FEDERATION_ENDPOINT_INVALID")
    ]


@pytest.mark.parametrize(
    "value",
    [
        "file:///tmp/authorize",
        "https://identity.example.com:70000/authorize",
    ],
)
def test_expanded_active_endpoint_requires_valid_http_url(value: str, tmp_path: Path) -> None:
    environ = _complete_env()
    environ["JD_AUTHORIZE_URL"] = value

    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(tmp_path, providers="jd", login_mode="chooser", environ=environ)

    assert ("authorize_url", "FEDERATION_ENDPOINT_INVALID") in {
        (issue.field, issue.code) for issue in exc_info.value.issues
    }


def test_active_unicode_endpoint_authority_is_rejected_before_resolution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    resolved_hostnames: list[str] = []

    def resolve(hostname: str, _port: int) -> tuple[str, ...]:
        resolved_hostnames.append(hostname)
        return ("93.184.216.34",)

    monkeypatch.setattr(config_module, "_resolve_endpoint_addresses", resolve)
    environ = _complete_env()
    environ["JD_AUTHORIZE_URL"] = "http://faß.example/authorize"

    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(tmp_path, providers="jd", login_mode="chooser", environ=environ)

    assert ("authorize_url", "FEDERATION_ENDPOINT_INVALID") in {
        (issue.field, issue.code) for issue in exc_info.value.issues
    }
    assert resolved_hostnames == ["sso.jd.com"]


def test_active_ascii_punycode_endpoint_preserves_configured_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    resolved_hostnames: list[str] = []

    def resolve(hostname: str, _port: int) -> tuple[str, ...]:
        resolved_hostnames.append(hostname)
        return ("93.184.216.34",)

    monkeypatch.setattr(config_module, "_resolve_endpoint_addresses", resolve)
    authorize_url = "http://xn--fa-hia.example./authorize"
    environ = _complete_env()
    environ["JD_AUTHORIZE_URL"] = authorize_url

    compiled = _compile(tmp_path, providers="jd", login_mode="chooser", environ=environ)

    provider = compiled.registry.require(ProviderId("jd"))
    assert provider.settings.authorize_url == authorize_url
    assert resolved_hostnames == ["xn--fa-hia.example", "sso.jd.com"]


def test_active_endpoint_rejects_any_private_dns_answer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def resolve(hostname: str, _port: int) -> tuple[str, ...]:
        if hostname == "mixed.identity.example":
            return ("93.184.216.34", "10.0.0.1")
        return ("93.184.216.34",)

    monkeypatch.setattr(config_module, "_resolve_endpoint_addresses", resolve)
    environ = _complete_env()
    environ["JD_AUTHORIZE_URL"] = "https://mixed.identity.example/authorize"

    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(tmp_path, providers="jd", login_mode="chooser", environ=environ)

    assert ("authorize_url", "FEDERATION_ENDPOINT_UNSAFE") in {
        (issue.field, issue.code) for issue in exc_info.value.issues
    }


def test_numeric_hostname_cannot_bypass_loopback_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def resolve(hostname: str, _port: int) -> tuple[str, ...]:
        if hostname == "2130706433":
            return ("127.0.0.1",)
        return ("93.184.216.34",)

    monkeypatch.setattr(config_module, "_resolve_endpoint_addresses", resolve)
    environ = _complete_env()
    environ["JD_AUTHORIZE_URL"] = "http://2130706433/authorize"

    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(tmp_path, providers="jd", login_mode="chooser", environ=environ)

    assert ("authorize_url", "FEDERATION_ENDPOINT_UNSAFE") in {
        (issue.field, issue.code) for issue in exc_info.value.issues
    }


def test_endpoint_resolution_failure_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def resolve(hostname: str, _port: int) -> tuple[str, ...]:
        if hostname == "unresolvable.identity.example":
            raise socket.gaierror("resolver unavailable")
        return ("93.184.216.34",)

    monkeypatch.setattr(config_module, "_resolve_endpoint_addresses", resolve)
    environ = _complete_env()
    environ["JD_AUTHORIZE_URL"] = "https://unresolvable.identity.example/authorize"

    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(tmp_path, providers="jd", login_mode="chooser", environ=environ)

    assert ("authorize_url", "FEDERATION_ENDPOINT_UNSAFE") in {
        (issue.field, issue.code) for issue in exc_info.value.issues
    }


@pytest.mark.parametrize("field", ["authorize_url", "userinfo_url"])
def test_active_provider_rejects_private_endpoints(field: str, tmp_path: Path) -> None:
    environ = _complete_env()
    environ[f"JD_{field.removesuffix('_url').upper()}_URL"] = "http://127.0.0.1/path"

    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(tmp_path, providers="jd", login_mode="chooser", environ=environ)

    assert (field, "FEDERATION_ENDPOINT_UNSAFE") in {
        (issue.field, issue.code) for issue in exc_info.value.issues
    }


def test_local_provider_allows_loopback_endpoints_only_in_development(tmp_path: Path) -> None:
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

    assert [(issue.field, issue.code) for issue in exc_info.value.issues] == [
        ("authorize_url", "FEDERATION_PROVIDER_CONFIG_INVALID"),
        ("token_url", "FEDERATION_PROVIDER_CONFIG_INVALID"),
        ("userinfo_url", "FEDERATION_PROVIDER_CONFIG_INVALID"),
    ]


def test_local_loopback_provider_is_allowed_only_in_development(tmp_path: Path) -> None:
    compiled = _compile_local_provider(tmp_path, environment="development")
    assert [item.id.value for item in compiled.registry.list_public()] == ["local"]


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_local_loopback_provider_is_rejected_outside_development(
    tmp_path: Path, environment: str
) -> None:
    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile_local_provider(tmp_path, environment=environment)

    assert "FEDERATION_PROVIDER_CONFIG_INVALID" in {issue.code for issue in exc_info.value.issues}


@pytest.mark.parametrize(
    ("value", "expected_code"),
    [
        ("file:///tmp/authorize", "FEDERATION_ENDPOINT_INVALID"),
        (r"http://127.0.0.1\@example.com/authorize", "FEDERATION_ENDPOINT_INVALID"),
        ("http://./", "FEDERATION_ENDPOINT_INVALID"),
        ("https://127.0.0.1:9090/authorize", "FEDERATION_ENDPOINT_UNSAFE"),
        ("http://10.0.0.1/authorize", "FEDERATION_ENDPOINT_UNSAFE"),
        ("http://169.254.169.254/latest/meta-data", "FEDERATION_ENDPOINT_UNSAFE"),
    ],
)
def test_local_development_exception_rejects_non_loopback_or_invalid_endpoints(
    value: str,
    expected_code: str,
    tmp_path: Path,
) -> None:
    catalog = _catalog()
    providers = catalog["providers"]
    assert isinstance(providers, dict)
    providers["local"] = {
        "display_name": "Local",
        "icon": "key",
        "protocol": "oauth2",
        "client_id": "local-client",
        "client_secret": "local-secret",
        "authorize_url": value,
        "token_url": "http://127.0.0.1:9090/token",
        "userinfo_url": "http://[::1]:9090/userinfo",
        "scope": "openid",
        "user_mapping": {"id": "sub"},
    }

    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(
            tmp_path,
            providers="local",
            login_mode="redirect",
            environ={},
            catalog=catalog,
        )

    assert ("authorize_url", expected_code) in {
        (issue.field, issue.code) for issue in exc_info.value.issues
    }


def test_endpoint_diagnostics_redact_credentials_query_and_fragment(tmp_path: Path) -> None:
    environ = _complete_env()
    environ["JD_AUTHORIZE_URL"] = (
        "http://endpoint-user:endpoint-password@127.0.0.1/authorize"
        "?token=query-secret#fragment-secret"
    )

    with pytest.raises(FederationConfigurationError) as exc_info:
        _compile(tmp_path, providers="jd", login_mode="chooser", environ=environ)

    rendered = str(exc_info.value)
    for sensitive_value in (
        "endpoint-user",
        "endpoint-password",
        "/authorize",
        "query-secret",
        "fragment-secret",
    ):
        assert sensitive_value not in rendered


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
