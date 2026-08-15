import asyncio
import base64
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast
from urllib.parse import parse_qs, parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

import httpx

from ...domain.errors import FederationError
from ...domain.models import (
    ActiveProvider,
    Authenticated,
    AuthorizationAction,
    CallbackContext,
    CorrelationMethod,
    FederatedPrincipal,
    LoginAttempt,
    OAuth2ProviderSettings,
    ProtocolId,
    RequestContext,
)
from ..endpoint_policy import (
    IPAddress,
    endpoint_addresses,
    parse_http_endpoint,
)
from ..endpoint_policy import (
    resolve_endpoint_addresses as _resolve_endpoint_addresses,
)

ClientFactory = Callable[[], httpx.AsyncClient]

_GITHUB_EMAILS_URL = "https://api.github.com/user/emails"
_AUTHORIZATION_PARAMETERS = frozenset(
    {"client_id", "redirect_uri", "response_type", "scope", "state"}
)
_REQUEST_TIMEOUT = httpx.Timeout(10.0)


@dataclass(frozen=True, slots=True)
class _PinnedEndpoint:
    url: httpx.URL
    host_header: str
    sni_hostname: str | None


@dataclass(frozen=True, slots=True)
class _OIDCDiscovery:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str


class OAuth2Adapter:
    protocol_id = ProtocolId.OAUTH2
    correlation_method = CorrelationMethod.OAUTH_STATE

    def __init__(self, *, client_factory: ClientFactory) -> None:
        self._client_factory = client_factory
        self._discovery_cache: dict[str, _OIDCDiscovery] = {}
        self._discovery_locks: dict[str, asyncio.Lock] = {}

    def extract_attempt_id(self, context: CallbackContext) -> str:
        state = context.query.get("state")
        if state is None or not state.strip():
            raise FederationError(
                code="FEDERATION_ATTEMPT_INVALID",
                message="Federation callback state is missing or invalid",
            )
        return state

    async def begin_login(
        self,
        provider: ActiveProvider,
        attempt: LoginAttempt,
        context: RequestContext,
    ) -> AuthorizationAction:
        del context
        settings = self._settings(provider)
        if settings.authorize_url is None:
            async with self._client_factory() as client:
                if settings.issuer is None:
                    raise FederationError(
                        code="FEDERATION_PROVIDER_CONFIG_INVALID",
                        message="OAuth2 provider endpoint is not configured",
                    )
                discovery = await self._discover(provider, settings.issuer, client)
                authorize_url = self._validate_authorization_endpoint(
                    discovery.authorization_endpoint,
                    provider,
                )
        else:
            authorize_url = self._validate_authorization_endpoint(settings.authorize_url, provider)

        parts = urlsplit(authorize_url)
        query = [
            (name, value)
            for name, value in parse_qsl(parts.query, keep_blank_values=True)
            if name not in _AUTHORIZATION_PARAMETERS
        ]
        query.extend(
            (
                ("client_id", settings.client_id),
                ("redirect_uri", attempt.redirect_uri),
                ("response_type", "code"),
                ("scope", settings.scope),
                ("state", attempt.id),
            )
        )
        authorization_url = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )
        return AuthorizationAction(authorization_url=authorization_url)

    async def complete_login(
        self,
        provider: ActiveProvider,
        attempt: LoginAttempt,
        context: CallbackContext,
    ) -> Authenticated:
        attempt_id = self.extract_attempt_id(context)
        if attempt_id != attempt.id:
            raise FederationError(
                code="FEDERATION_ATTEMPT_INVALID",
                message="Federation callback state does not match the login attempt",
            )
        if context.query.get("error"):
            raise FederationError(
                code="FEDERATION_UPSTREAM_DENIED",
                message="The identity provider denied authorization",
            )
        code = context.query.get("code")
        if code is None or not code.strip():
            raise FederationError(
                code="FEDERATION_CALLBACK_INVALID",
                message="Federation callback is missing an authorization code",
            )

        settings = self._settings(provider)
        async with self._client_factory() as client:
            token_url = await self._resolve_endpoint(
                provider,
                settings,
                configured_url=settings.token_url,
                discovery_field="token_endpoint",
                client=client,
            )
            access_token = await self._exchange_code(
                client,
                settings,
                token_url,
                code,
                attempt.redirect_uri,
            )
            userinfo_url = await self._resolve_endpoint(
                provider,
                settings,
                configured_url=settings.userinfo_url,
                discovery_field="userinfo_endpoint",
                client=client,
            )
            raw_userinfo = await self._fetch_userinfo(
                client,
                userinfo_url,
                access_token,
                settings.userinfo_headers,
            )
            mapped_claims = self._map_claims(raw_userinfo, settings.user_mapping)
            is_oidc = settings.issuer is not None
            if provider.id.value == "github":
                email, email_verified = await self._fetch_verified_github_email(client, access_token)
                if email is None:
                    mapped_claims.pop("email", None)
                else:
                    mapped_claims["email"] = email
            else:
                email = self._optional_string(mapped_claims.get("email"))
                email_verified = (
                    email is not None
                    and settings.user_mapping.get("email") == "email"
                    and raw_userinfo.get("email_verified") is True
                )

        if is_oidc:
            subject = self._required_oidc_subject(raw_userinfo.get("sub"))
            mapped_claims["id"] = subject
        else:
            subject = self._required_subject(mapped_claims.get("id"))
        return Authenticated(
            FederatedPrincipal(
                provider_id=provider.id,
                subject=subject,
                email=email,
                email_verified=email_verified,
                display_name=self._optional_string(mapped_claims.get("name")),
                avatar_url=self._optional_string(mapped_claims.get("avatar")),
                claims=mapped_claims,
            )
        )

    @staticmethod
    def _settings(provider: ActiveProvider) -> OAuth2ProviderSettings:
        if provider.protocol is not ProtocolId.OAUTH2 or not isinstance(
            provider.settings, OAuth2ProviderSettings
        ):
            raise FederationError(
                code="FEDERATION_PROVIDER_CONFIG_INVALID",
                message="Provider does not have valid OAuth2 settings",
            )
        return provider.settings

    async def _resolve_endpoint(
        self,
        provider: ActiveProvider,
        settings: OAuth2ProviderSettings,
        *,
        configured_url: str | None,
        discovery_field: str,
        client: httpx.AsyncClient,
    ) -> _PinnedEndpoint:
        if configured_url is not None:
            return self._pin_endpoint(configured_url, provider)
        if settings.issuer is None:
            raise FederationError(
                code="FEDERATION_PROVIDER_CONFIG_INVALID",
                message="OAuth2 provider endpoint is not configured",
            )
        discovery = await self._discover(provider, settings.issuer, client)
        endpoint = getattr(discovery, discovery_field)
        return self._pin_endpoint(endpoint, provider)

    async def _discover(
        self,
        provider: ActiveProvider,
        issuer: str,
        client: httpx.AsyncClient,
    ) -> _OIDCDiscovery:
        cached = self._discovery_cache.get(issuer)
        if cached is not None:
            return cached
        lock = self._discovery_locks.setdefault(issuer, asyncio.Lock())
        async with lock:
            cached = self._discovery_cache.get(issuer)
            if cached is not None:
                return cached
            discovery_url = self._pin_endpoint(
                f"{issuer.rstrip('/')}/.well-known/openid-configuration",
                provider,
            )
            try:
                response = await self._request(client, "GET", discovery_url)
                if not response.is_success:
                    raise self._upstream_unavailable()
                payload = response.json()
            except FederationError:
                raise
            except (httpx.HTTPError, ValueError, TypeError):
                raise self._upstream_unavailable() from None
            discovery = self._validated_discovery(payload, issuer)
            self._discovery_cache[issuer] = discovery
            return discovery

    @staticmethod
    def _validated_discovery(payload: object, issuer: str) -> _OIDCDiscovery:
        if not isinstance(payload, dict) or payload.get("issuer") != issuer:
            raise OAuth2Adapter._upstream_unavailable()
        endpoints: dict[str, str] = {}
        for field in ("authorization_endpoint", "token_endpoint", "userinfo_endpoint"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip() or parse_http_endpoint(value) is None:
                raise OAuth2Adapter._upstream_unavailable()
            endpoints[field] = value
        return _OIDCDiscovery(
            issuer=issuer,
            authorization_endpoint=endpoints["authorization_endpoint"],
            token_endpoint=endpoints["token_endpoint"],
            userinfo_endpoint=endpoints["userinfo_endpoint"],
        )

    async def _exchange_code(
        self,
        client: httpx.AsyncClient,
        settings: OAuth2ProviderSettings,
        token_url: _PinnedEndpoint,
        code: str,
        redirect_uri: str,
    ) -> str:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        headers = {"Accept": "application/json"}
        if settings.token_endpoint_auth_method == "client_secret_post":
            data["client_id"] = settings.client_id
            data["client_secret"] = settings.client_secret
        elif settings.token_endpoint_auth_method == "client_secret_basic":
            client_id = quote_plus(settings.client_id, safe="")
            client_secret = quote_plus(settings.client_secret, safe="")
            credentials = base64.b64encode(
                f"{client_id}:{client_secret}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {credentials}"
        else:
            raise FederationError(
                code="FEDERATION_PROVIDER_CONFIG_INVALID",
                message="OAuth2 token endpoint authentication method is invalid",
            )

        try:
            response = await self._request(
                client,
                "POST",
                token_url,
                data=data,
                headers=headers,
            )
            if not response.is_success:
                raise self._upstream_unavailable()
            payload = self._token_payload(response)
        except FederationError:
            raise
        except (httpx.HTTPError, ValueError, TypeError):
            raise self._upstream_unavailable() from None
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise self._upstream_unavailable()
        token_type = payload.get("token_type")
        if not isinstance(token_type, str) or token_type.strip().lower() != "bearer":
            raise self._upstream_unavailable()
        return access_token.strip()

    @staticmethod
    def _token_payload(response: httpx.Response) -> Mapping[str, object]:
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Token response must be an object")
            return cast(dict[str, object], payload)
        return {key: values[0] for key, values in parse_qs(response.text).items() if values}

    async def _fetch_userinfo(
        self,
        client: httpx.AsyncClient,
        userinfo_url: _PinnedEndpoint,
        access_token: str,
        configured_headers: Mapping[str, str],
    ) -> Mapping[str, object]:
        headers = {**configured_headers, "Authorization": f"Bearer {access_token}"}
        try:
            response = await self._request(client, "GET", userinfo_url, headers=headers)
            if not response.is_success:
                raise self._upstream_unavailable()
            payload = response.json()
        except FederationError:
            raise
        except (httpx.HTTPError, ValueError, TypeError):
            raise self._upstream_unavailable() from None
        if not isinstance(payload, dict):
            raise self._upstream_unavailable()
        return cast(dict[str, object], payload)

    async def _fetch_verified_github_email(
        self,
        client: httpx.AsyncClient,
        access_token: str,
    ) -> tuple[str | None, bool]:
        endpoint = self._pin_endpoint(_GITHUB_EMAILS_URL, None)
        try:
            response = await self._request(
                client,
                "GET",
                endpoint,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            if not response.is_success:
                return None, False
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            return None, False
        if not isinstance(payload, list):
            return None, False
        for item in payload:
            if not isinstance(item, dict):
                continue
            email = item.get("email")
            if item.get("primary") is True and item.get("verified") is True and isinstance(email, str):
                normalized = email.strip()
                if normalized:
                    return normalized, True
        return None, False

    @staticmethod
    def _map_claims(
        raw_userinfo: Mapping[str, object],
        user_mapping: Mapping[str, str],
    ) -> dict[str, object]:
        claims: dict[str, object] = {}
        for claim_name in ("id", "email", "name", "avatar"):
            source_name = user_mapping.get(claim_name)
            if not source_name or source_name not in raw_userinfo:
                continue
            value = raw_userinfo[source_name]
            if claim_name == "id":
                if isinstance(value, (str, int)) and not isinstance(value, bool):
                    claims[claim_name] = value
            elif isinstance(value, str):
                claims[claim_name] = value
        return claims

    @staticmethod
    def _required_subject(value: object) -> str:
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            subject = str(value).strip()
            if subject:
                return subject
        raise FederationError(
            code="FEDERATION_PRINCIPAL_INVALID",
            message="Identity provider did not return a stable subject",
        )

    @staticmethod
    def _required_oidc_subject(value: object) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise FederationError(
            code="FEDERATION_PRINCIPAL_INVALID",
            message="OIDC provider did not return a stable subject",
        )

    @staticmethod
    def _optional_string(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _validate_authorization_endpoint(
        endpoint: str,
        provider: ActiveProvider,
    ) -> str:
        parsed = parse_http_endpoint(endpoint)
        if parsed is None:
            raise FederationError(
                code="FEDERATION_PROVIDER_CONFIG_INVALID",
                message="OAuth2 provider endpoint failed security validation",
            )
        scheme, hostname, port = parsed
        addresses = endpoint_addresses(
            hostname,
            port,
            resolver=_resolve_endpoint_addresses,
        )
        if not OAuth2Adapter._addresses_are_safe(addresses, provider, scheme):
            raise FederationError(
                code="FEDERATION_PROVIDER_CONFIG_INVALID",
                message="OAuth2 provider endpoint failed security validation",
            )
        return endpoint

    @staticmethod
    def _pin_endpoint(
        endpoint: str,
        provider: ActiveProvider | None,
    ) -> _PinnedEndpoint:
        parsed_endpoint = parse_http_endpoint(endpoint)
        if parsed_endpoint is None:
            raise FederationError(
                code="FEDERATION_PROVIDER_CONFIG_INVALID",
                message="OAuth2 provider endpoint failed security validation",
            )
        scheme, hostname, port = parsed_endpoint
        addresses = endpoint_addresses(
            hostname,
            port,
            resolver=_resolve_endpoint_addresses,
        )
        if not OAuth2Adapter._addresses_are_safe(addresses, provider, scheme):
            raise FederationError(
                code="FEDERATION_PROVIDER_CONFIG_INVALID",
                message="OAuth2 provider endpoint failed security validation",
            )
        assert addresses is not None
        original_url = httpx.URL(endpoint)
        original_hostname = urlsplit(endpoint).hostname
        assert original_hostname is not None
        host = f"[{original_hostname}]" if ":" in original_hostname else original_hostname
        explicit_port = urlsplit(endpoint).port
        host_header = f"{host}:{explicit_port}" if explicit_port is not None else host
        return _PinnedEndpoint(
            url=original_url.copy_with(host=addresses[0].compressed),
            host_header=host_header,
            sni_hostname=hostname if scheme == "https" else None,
        )

    @staticmethod
    def _addresses_are_safe(
        addresses: tuple[IPAddress, ...] | None,
        provider: ActiveProvider | None,
        scheme: str,
    ) -> bool:
        if not addresses:
            return False
        if all(address.is_global for address in addresses):
            return True
        return (
            provider is not None
            and provider.id.value == "local"
            and scheme == "http"
            and all(address.is_loopback for address in addresses)
        )

    @staticmethod
    async def _request(
        client: httpx.AsyncClient,
        method: str,
        endpoint: _PinnedEndpoint,
        *,
        data: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        request_headers = dict(headers or {})
        request_headers["Host"] = endpoint.host_header
        extensions = (
            {"sni_hostname": endpoint.sni_hostname}
            if endpoint.sni_hostname is not None
            else None
        )
        return await client.request(
            method,
            endpoint.url,
            data=data,
            headers=request_headers,
            follow_redirects=False,
            timeout=_REQUEST_TIMEOUT,
            extensions=extensions,
        )

    @staticmethod
    def _upstream_unavailable() -> FederationError:
        return FederationError(
            code="FEDERATION_UPSTREAM_UNAVAILABLE",
            message="The identity provider is temporarily unavailable",
            retryable=True,
        )
