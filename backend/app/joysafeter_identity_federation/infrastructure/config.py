import ipaddress
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..domain.errors import ConfigurationIssue, FederationConfigurationError
from ..domain.models import (
    ActiveProvider,
    FederationSettings,
    LoginMode,
    ProtocolId,
    ProviderId,
    ProviderProtocolSettings,
)
from .protocols.base import ProtocolSchemaRegistry
from .registry import ProviderRegistry
from .templates import PROVIDER_TEMPLATES

_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ENDPOINT_FIELDS = ("authorize_url", "token_url", "userinfo_url", "issuer")


class CatalogProvider(BaseModel):
    model_config = ConfigDict(extra="allow")

    display_name: str = Field(min_length=1)
    icon: str = Field(min_length=1)
    protocol: str = Field(min_length=1)
    template: str | None = None

    def protocol_configuration(self) -> dict[str, object]:
        return dict(self.model_extra or {})


class CatalogSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_redirect_url: str
    allow_registration: bool
    auto_link_by_email: bool


class CatalogDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: dict[str, CatalogProvider]
    settings: CatalogSettings


@dataclass(frozen=True, slots=True)
class CompiledFederationConfiguration:
    registry: ProviderRegistry


def _issue(
    provider_id: str,
    field: str,
    code: str,
    message: str,
) -> ConfigurationIssue:
    return ConfigurationIssue(
        provider_id=provider_id,
        field=field,
        code=code,
        message=message,
    )


def _load_yaml(config_path: Path) -> object:
    try:
        with config_path.open(encoding="utf-8") as file:
            return yaml.safe_load(file)
    except yaml.YAMLError as error:
        raise FederationConfigurationError(
            [
                _issue(
                    "catalog",
                    "yaml",
                    "FEDERATION_CONFIG_YAML_INVALID",
                    str(error),
                )
            ]
        ) from error


def _document_from_raw(raw: object) -> CatalogDocument:
    try:
        return CatalogDocument.model_validate(raw)
    except ValidationError as error:
        issues = []
        for detail in error.errors():
            location = tuple(str(part) for part in detail["loc"])
            provider_id = location[1] if len(location) > 1 and location[0] == "providers" else "catalog"
            field = ".".join(location[2:] if provider_id != "catalog" else location) or "document"
            issues.append(
                _issue(
                    provider_id,
                    field,
                    "FEDERATION_CONFIG_INVALID",
                    str(detail["msg"]),
                )
            )
        raise FederationConfigurationError(issues) from error


def _parse_active_provider_names(active_provider_names: str) -> tuple[tuple[str, ...], list[ConfigurationIssue]]:
    requested = tuple(name.strip() for name in active_provider_names.split(",") if name.strip())
    issues: list[ConfigurationIssue] = []
    seen: set[str] = set()
    for name in requested:
        try:
            ProviderId(name)
        except ValueError as error:
            issues.append(
                _issue(
                    name,
                    "id",
                    "FEDERATION_PROVIDER_ID_INVALID",
                    str(error),
                )
            )
        if name in seen:
            issues.append(
                _issue(
                    name,
                    "provider",
                    "FEDERATION_PROVIDER_DUPLICATE",
                    f"Provider {name!r} is activated more than once",
                )
            )
        seen.add(name)
    return requested, issues


def _parse_login_mode(
    login_mode: str,
    requested: tuple[str, ...],
) -> tuple[LoginMode | None, list[ConfigurationIssue]]:
    try:
        parsed = LoginMode(login_mode)
    except ValueError:
        return None, [
            _issue(
                "settings",
                "login_mode",
                "FEDERATION_LOGIN_MODE_INVALID",
                f"Login mode {login_mode!r} is not supported",
            )
        ]
    if parsed is LoginMode.REDIRECT and not requested:
        return parsed, [
            _issue(
                "settings",
                "login_mode",
                "FEDERATION_LOGIN_MODE_INVALID",
                "Redirect login mode requires at least one active provider",
            )
        ]
    if parsed is LoginMode.REDIRECT and len(requested) != 1:
        return parsed, [
            _issue(
                "settings",
                "login_mode",
                "FEDERATION_LOGIN_MODE_INVALID",
                "Redirect login mode requires exactly one active provider",
            )
        ]
    return parsed, []


def _materialize_template(provider: CatalogProvider) -> tuple[dict[str, object], list[ConfigurationIssue]]:
    configuration: dict[str, object] = {}
    if provider.template is not None:
        template = PROVIDER_TEMPLATES.get(provider.template)
        if template is None:
            return provider.protocol_configuration(), [
                _issue(
                    "catalog",
                    "template",
                    "FEDERATION_TEMPLATE_UNKNOWN",
                    f"Provider template {provider.template!r} is not registered",
                )
            ]
        configuration.update(template)
    configuration.update(provider.protocol_configuration())
    default_tenant = configuration.pop("default_tenant", None)
    tenant = configuration.pop("tenant", default_tenant)
    if tenant is not None:
        for field in ("authorize_url", "token_url"):
            value = configuration.get(field)
            if isinstance(value, str):
                configuration[field] = value.replace("{tenant}", str(tenant))
    return configuration, []


def _remap_protocol_issue(provider_id: str, issue: ConfigurationIssue) -> ConfigurationIssue:
    return _issue(provider_id, issue.field, issue.code, issue.message)


def _validate_catalog(
    document: CatalogDocument,
    schema_registry: ProtocolSchemaRegistry,
) -> tuple[dict[str, tuple[CatalogProvider, dict[str, object]]], list[ConfigurationIssue]]:
    validated: dict[str, tuple[CatalogProvider, dict[str, object]]] = {}
    issues: list[ConfigurationIssue] = []
    for provider_name, provider in document.providers.items():
        try:
            ProviderId(provider_name)
        except ValueError as error:
            issues.append(
                _issue(
                    provider_name,
                    "id",
                    "FEDERATION_PROVIDER_ID_INVALID",
                    str(error),
                )
            )
        configuration, template_issues = _materialize_template(provider)
        issues.extend(
            _issue(provider_name, issue.field, issue.code, issue.message) for issue in template_issues
        )
        try:
            schema_registry.validate_configuration(provider.protocol, configuration)
        except FederationConfigurationError as error:
            issues.extend(_remap_protocol_issue(provider_name, issue) for issue in error.issues)
        except ValidationError as error:
            for detail in error.errors():
                field = ".".join(str(part) for part in detail["loc"]) or "configuration"
                issues.append(
                    _issue(
                        provider_name,
                        field,
                        "FEDERATION_PROVIDER_CONFIG_INVALID",
                        str(detail["msg"]),
                    )
                )
        validated[provider_name] = (provider, configuration)
    return validated, issues


def _expand_environment(
    provider_id: str,
    configuration: Mapping[str, object],
    environ: Mapping[str, str],
) -> tuple[dict[str, object], list[ConfigurationIssue]]:
    issues: list[ConfigurationIssue] = []

    def expand(field: str, value: object) -> object:
        if isinstance(value, dict):
            return {key: expand(f"{field}.{key}", item) for key, item in value.items()}
        if not isinstance(value, str):
            return value

        def replace(match: re.Match[str]) -> str:
            variable = match.group(1)
            if variable not in environ:
                issues.append(
                    _issue(
                        provider_id,
                        field,
                        "FEDERATION_ENV_UNRESOLVED",
                        f"Environment variable {variable!r} is not set",
                    )
                )
                return match.group(0)
            return environ[variable]

        return _ENV_REFERENCE.sub(replace, value)

    expanded = {field: expand(field, value) for field, value in configuration.items()}
    return expanded, issues


def _is_unsafe_endpoint(value: str) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return True
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return address.is_private or address.is_link_local or address.is_loopback


def _endpoint_issues(
    provider_id: str,
    settings: ProviderProtocolSettings,
    application_environment: str,
) -> list[ConfigurationIssue]:
    if provider_id == "local" and application_environment == "development":
        return []
    issues = []
    for field in _ENDPOINT_FIELDS:
        value = getattr(settings, field, None)
        if isinstance(value, str) and _ENV_REFERENCE.search(value) is None and _is_unsafe_endpoint(value):
            issues.append(
                _issue(
                    provider_id,
                    field,
                    "FEDERATION_ENDPOINT_UNSAFE",
                    f"Endpoint {value!r} must not target a private, link-local, or loopback address",
                )
            )
    return issues


def _compile_active_providers(
    catalog: Mapping[str, tuple[CatalogProvider, dict[str, object]]],
    requested: tuple[str, ...],
    application_environment: str,
    schema_registry: ProtocolSchemaRegistry,
    environ: Mapping[str, str],
) -> tuple[list[ActiveProvider], list[ConfigurationIssue]]:
    providers: list[ActiveProvider] = []
    issues: list[ConfigurationIssue] = []
    seen: set[str] = set()
    for provider_name in requested:
        try:
            provider_id = ProviderId(provider_name)
        except ValueError:
            continue
        if provider_name in seen:
            continue
        seen.add(provider_name)
        catalog_entry = catalog.get(provider_name)
        if catalog_entry is None:
            issues.append(
                _issue(
                    provider_name,
                    "provider",
                    "FEDERATION_PROVIDER_UNKNOWN",
                    f"Provider {provider_name!r} is not in the catalog",
                )
            )
            continue
        provider, raw_configuration = catalog_entry
        configuration, environment_issues = _expand_environment(
            provider_name,
            raw_configuration,
            environ,
        )
        issues.extend(environment_issues)
        try:
            definition = schema_registry.require(provider.protocol)
            settings = schema_registry.validate_configuration(provider.protocol, configuration)
        except FederationConfigurationError:
            continue
        except ValidationError as error:
            for detail in error.errors():
                field = ".".join(str(part) for part in detail["loc"]) or "configuration"
                issues.append(
                    _issue(
                        provider_name,
                        field,
                        "FEDERATION_PROVIDER_CONFIG_INVALID",
                        str(detail["msg"]),
                    )
                )
            continue
        issues.extend(_endpoint_issues(provider_name, settings, application_environment))
        if environment_issues:
            continue
        providers.append(
            ActiveProvider(
                id=provider_id,
                display_name=provider.display_name,
                icon=provider.icon,
                protocol=ProtocolId(definition.protocol_id),
                settings=settings,
            )
        )
    return providers, issues


def _dedupe_issues(issues: list[ConfigurationIssue]) -> list[ConfigurationIssue]:
    deduped: list[ConfigurationIssue] = []
    seen: set[tuple[str, str, str, str]] = set()
    for issue in issues:
        key = (issue.provider_id, issue.field, issue.code, issue.message)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def _compile_settings(document: CatalogDocument, login_mode: LoginMode) -> FederationSettings:
    return FederationSettings(
        login_mode=login_mode,
        default_redirect_url=document.settings.default_redirect_url,
        allow_registration=document.settings.allow_registration,
        auto_link_by_email=document.settings.auto_link_by_email,
    )


def compile_federation_configuration(
    *,
    config_path: Path,
    active_provider_names: str,
    login_mode: str,
    application_environment: str,
    schema_registry: ProtocolSchemaRegistry,
    environ: Mapping[str, str],
) -> CompiledFederationConfiguration:
    raw = _load_yaml(config_path)
    document = _document_from_raw(raw)
    requested, issues = _parse_active_provider_names(active_provider_names)
    parsed_mode, login_mode_issues = _parse_login_mode(login_mode, requested)
    issues.extend(login_mode_issues)
    catalog, catalog_issues = _validate_catalog(document, schema_registry)
    issues.extend(catalog_issues)
    providers, provider_issues = _compile_active_providers(
        catalog,
        requested,
        application_environment,
        schema_registry,
        environ,
    )
    issues.extend(provider_issues)
    issues = _dedupe_issues(issues)
    if issues:
        raise FederationConfigurationError(issues)
    assert parsed_mode is not None
    return CompiledFederationConfiguration(
        registry=ProviderRegistry(providers, _compile_settings(document, parsed_mode)),
    )
