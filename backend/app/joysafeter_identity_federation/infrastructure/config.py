import ipaddress
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..domain.errors import ConfigurationIssue, FederationConfigurationError
from ..domain.models import (
    ActiveProvider,
    FederationSettings,
    LoginMode,
    ProtocolId,
    ProviderId,
    ProviderProtocolSettings,
)
from .endpoint_policy import (
    endpoint_addresses as _strict_endpoint_addresses,
)
from .endpoint_policy import (
    is_trusted_private_address as _is_trusted_private_address,
)
from .endpoint_policy import (
    parse_http_endpoint as _parse_http_endpoint,
)
from .endpoint_policy import (
    resolve_endpoint_addresses as _default_resolve_endpoint_addresses,
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
    allow_private_network: bool = False

    def protocol_configuration(self) -> dict[str, object]:
        return dict(self.model_extra or {})


class CatalogSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_redirect_url: str
    allow_registration: bool
    auto_link_by_email: bool


class CatalogDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    providers: dict[str, CatalogProvider]
    settings: CatalogSettings

    @field_validator("version", mode="before")
    @classmethod
    def require_exact_integer_version_one(cls, value: object) -> object:
        if not isinstance(value, int) or isinstance(value, bool) or value != 1:
            raise ValueError("Catalog version must be the integer 1")
        return value


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
    except FileNotFoundError:
        raise FederationConfigurationError(
            [
                _issue(
                    "catalog",
                    "file",
                    "FEDERATION_CONFIG_NOT_FOUND",
                    "Federation configuration file was not found",
                )
            ]
        ) from None
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        if mark is None:
            message = "YAML syntax is invalid"
        else:
            message = f"YAML syntax is invalid at line {mark.line + 1}, column {mark.column + 1}"
        raise FederationConfigurationError(
            [
                _issue(
                    "catalog",
                    "yaml",
                    "FEDERATION_CONFIG_YAML_INVALID",
                    message,
                )
            ]
        ) from None


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
        raise FederationConfigurationError(issues) from None


def _parse_active_provider_names(active_provider_names: str) -> tuple[tuple[str, ...], list[ConfigurationIssue]]:
    if not active_provider_names.strip():
        return (), []
    requested = tuple(name.strip() for name in active_provider_names.split(","))
    issues: list[ConfigurationIssue] = []
    seen: set[str] = set()
    for index, name in enumerate(requested):
        if not name:
            issues.append(
                _issue(
                    "settings",
                    f"providers[{index}]",
                    "FEDERATION_PROVIDER_EMPTY",
                    "Active provider entries must not be empty",
                )
            )
            continue
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
    if parsed is LoginMode.REDIRECT and not any(requested):
        return parsed, [
            _issue(
                "settings",
                "login_mode",
                "FEDERATION_LOGIN_MODE_INVALID",
                "Redirect login mode requires at least one active provider",
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


def _catalog_endpoint_is_valid(value: str) -> bool:
    if _ENV_REFERENCE.fullmatch(value) is not None:
        return True
    candidate = _ENV_REFERENCE.sub("placeholder", value)
    if "${" in candidate:
        return False
    return _parse_http_endpoint(candidate) is not None


def _catalog_endpoint_issues(
    provider_id: str,
    configuration: Mapping[str, object],
) -> list[ConfigurationIssue]:
    issues: list[ConfigurationIssue] = []
    for field in _ENDPOINT_FIELDS:
        value = configuration.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or not _catalog_endpoint_is_valid(value):
            issues.append(
                _issue(
                    provider_id,
                    field,
                    "FEDERATION_ENDPOINT_INVALID",
                    "Endpoint must be a valid HTTP(S) URL or environment reference",
                )
            )
    return issues


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
        issues.extend(_issue(provider_name, issue.field, issue.code, issue.message) for issue in template_issues)
        issues.extend(_catalog_endpoint_issues(provider_name, configuration))
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
) -> tuple[dict[str, object], list[ConfigurationIssue], frozenset[str]]:
    issues: list[ConfigurationIssue] = []
    unresolved_fields: set[str] = set()

    def mark_unresolved(field: str) -> None:
        if field in unresolved_fields:
            return
        unresolved_fields.add(field)
        issues.append(
            _issue(
                provider_id,
                field,
                "FEDERATION_ENV_UNRESOLVED",
                "Field contains a missing, blank, or unresolved environment value",
            )
        )

    def expand(field: str, value: object) -> object:
        if isinstance(value, Mapping):
            return {key: expand(f"{field}.{key}", item) for key, item in value.items()}
        if not isinstance(value, str):
            return value

        def replace(match: re.Match[str]) -> str:
            variable = match.group(1)
            if variable not in environ:
                mark_unresolved(field)
                return match.group(0)
            replacement = environ[variable]
            if not replacement.strip() or "${" in replacement:
                mark_unresolved(field)
                return match.group(0)
            return replacement

        expanded_value = _ENV_REFERENCE.sub(replace, value)
        if "${" in expanded_value:
            mark_unresolved(field)
        return expanded_value

    expanded = {field: expand(field, value) for field, value in configuration.items()}
    return expanded, issues, frozenset(unresolved_fields)


def _resolve_endpoint_addresses(hostname: str, port: int) -> tuple[str, ...]:
    return _default_resolve_endpoint_addresses(hostname, port)


def _endpoint_addresses(
    hostname: str,
    port: int,
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...] | None:
    return _strict_endpoint_addresses(hostname, port, resolver=_resolve_endpoint_addresses)


def _endpoint_issues(
    provider_id: str,
    settings: ProviderProtocolSettings,
    application_environment: str,
    unresolved_fields: frozenset[str],
    allow_private_network: bool,
) -> list[ConfigurationIssue]:
    issues: list[ConfigurationIssue] = []
    for field in _ENDPOINT_FIELDS:
        if field in unresolved_fields:
            continue
        value = getattr(settings, field, None)
        if value is None:
            continue
        if not isinstance(value, str):
            continue
        parsed = _parse_http_endpoint(value)
        if parsed is None:
            issues.append(
                _issue(
                    provider_id,
                    field,
                    "FEDERATION_ENDPOINT_INVALID",
                    "Endpoint must be a concrete valid HTTP(S) URL",
                )
            )
            continue
        scheme, hostname, port = parsed
        addresses = _endpoint_addresses(hostname, port)
        if addresses is None:
            issues.append(
                _issue(
                    provider_id,
                    field,
                    "FEDERATION_ENDPOINT_UNSAFE",
                    "Endpoint destination could not be safely resolved",
                )
            )
            continue
        allow_loopback = (
            provider_id == "local"
            and application_environment == "development"
            and scheme == "http"
            and all(address.is_loopback for address in addresses)
        )
        allow_private = allow_private_network and all(_is_trusted_private_address(address) for address in addresses)
        if not allow_loopback and not allow_private and any(not address.is_global for address in addresses):
            issue_code = (
                "FEDERATION_PROVIDER_CONFIG_INVALID"
                if provider_id == "local" and application_environment != "development"
                else "FEDERATION_ENDPOINT_UNSAFE"
            )
            issues.append(
                _issue(
                    provider_id,
                    field,
                    issue_code,
                    "Endpoint destination must be globally routable",
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
        configuration, environment_issues, unresolved_fields = _expand_environment(
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
        endpoint_issues = _endpoint_issues(
            provider_name,
            settings,
            application_environment,
            unresolved_fields,
            provider.allow_private_network,
        )
        issues.extend(endpoint_issues)
        if environment_issues or endpoint_issues:
            continue
        providers.append(
            ActiveProvider(
                id=provider_id,
                display_name=provider.display_name,
                icon=provider.icon,
                protocol=ProtocolId(definition.protocol_id),
                settings=settings,
                allow_http_loopback=(provider_name == "local" and application_environment == "development"),
                allow_private_network=provider.allow_private_network,
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
