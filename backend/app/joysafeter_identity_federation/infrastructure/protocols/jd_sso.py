import hashlib
import time
from collections.abc import Callable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from ...domain.errors import FederationError
from ...domain.models import (
    ActiveProvider,
    Authenticated,
    AuthorizationAction,
    CallbackContext,
    CorrelationCookie,
    CorrelationMethod,
    FederatedPrincipal,
    JDSSOProviderSettings,
    LoginAttempt,
    ProtocolId,
    RequestContext,
    RestartAuthorization,
)
from ..correlation import SignedCorrelationCodec
from .oauth2 import ClientFactory, OAuth2Adapter

_VERIFY_TICKET_PARAMETERS = frozenset({"ticket", "url", "ip", "app", "time", "sign"})


class JDSSOAdapter(OAuth2Adapter):
    protocol_id = ProtocolId.JD_SSO
    correlation_method = CorrelationMethod.SIGNED_COOKIE

    def __init__(
        self,
        *,
        correlation_codec: SignedCorrelationCodec,
        client_factory: ClientFactory,
        now: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(client_factory=client_factory)
        self._correlation_codec = correlation_codec
        self._now = now

    @staticmethod
    def compute_signature(
        *,
        client_secret: str,
        timestamp_ms: int,
        ticket: str,
    ) -> str:
        signing_input = f"{client_secret}{timestamp_ms}{ticket}".encode()
        return hashlib.md5(signing_input, usedforsecurity=False).hexdigest()

    def extract_attempt_id(self, context: CallbackContext) -> str:
        signed_attempt = context.cookies.get(self._correlation_codec.cookie_name)
        if signed_attempt is None or not signed_attempt.strip():
            raise FederationError(
                code="FEDERATION_CORRELATION_INVALID",
                message="Federation login correlation is invalid",
            )
        return self._correlation_codec.verify(signed_attempt, now_epoch=int(self._now()))

    async def begin_login(
        self,
        provider: ActiveProvider,
        attempt: LoginAttempt,
        context: RequestContext,
    ) -> AuthorizationAction:
        del context
        settings = self._settings(provider)
        authorize_url = await self._validate_authorization_endpoint(settings.authorize_url, provider)
        authorization_url = self._authorization_url(authorize_url, attempt.redirect_uri)
        expires_at = int(attempt.expires_at.timestamp())
        max_age_seconds = expires_at - int(self._now())
        if max_age_seconds <= 0:
            raise FederationError(
                code="FEDERATION_ATTEMPT_INVALID",
                message="Federation login attempt has expired",
            )
        return AuthorizationAction(
            authorization_url=authorization_url,
            correlation_cookie=CorrelationCookie(
                name=self._correlation_codec.cookie_name,
                value=self._correlation_codec.sign(attempt.id, expires_at=expires_at),
                max_age_seconds=max_age_seconds,
            ),
        )

    async def complete_login(
        self,
        provider: ActiveProvider,
        attempt: LoginAttempt,
        context: CallbackContext,
    ) -> Authenticated | RestartAuthorization:
        attempt_id = self.extract_attempt_id(context)
        if attempt_id != attempt.id:
            raise FederationError(
                code="FEDERATION_ATTEMPT_INVALID",
                message="Federation callback correlation does not match the login attempt",
            )

        ticket = context.cookies.get("sso.jd.com")
        if ticket is None:
            return RestartAuthorization(reason="jd_session_missing")
        if not ticket.strip():
            raise FederationError(
                code="FEDERATION_CALLBACK_INVALID",
                message="JD federation callback contains an invalid session ticket",
            )

        settings = self._settings(provider)
        timestamp_ms = int(round(self._now() * 1000))
        verify_url = self._verify_ticket_url(
            settings.userinfo_url,
            ticket=ticket,
            request_url=context.request_url,
            client_ip=context.client_ip,
            client_id=settings.client_id,
            timestamp_ms=timestamp_ms,
            signature=self.compute_signature(
                client_secret=settings.client_secret,
                timestamp_ms=timestamp_ms,
                ticket=ticket,
            ),
        )
        payload = await self._fetch_ticket_payload(verify_url, provider)
        return self._authenticate(provider, settings, payload)

    @staticmethod
    def _settings(provider: ActiveProvider) -> JDSSOProviderSettings:
        if provider.protocol is not ProtocolId.JD_SSO or not isinstance(provider.settings, JDSSOProviderSettings):
            raise FederationError(
                code="FEDERATION_PROVIDER_CONFIG_INVALID",
                message="Provider does not have valid JD SSO settings",
            )
        return provider.settings

    @staticmethod
    def _authorization_url(
        authorize_url: str,
        redirect_uri: str,
    ) -> str:
        parts = urlsplit(authorize_url)
        query = [(name, value) for name, value in parse_qsl(parts.query, keep_blank_values=True) if name != "ReturnUrl"]
        query.append(("ReturnUrl", redirect_uri))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    @staticmethod
    def _verify_ticket_url(
        userinfo_url: str,
        *,
        ticket: str,
        request_url: str,
        client_ip: str,
        client_id: str,
        timestamp_ms: int,
        signature: str,
    ) -> str:
        parts = urlsplit(userinfo_url)
        query = [
            (name, value)
            for name, value in parse_qsl(parts.query, keep_blank_values=True)
            if name not in _VERIFY_TICKET_PARAMETERS
        ]
        query.extend(
            (
                ("ticket", ticket),
                ("url", request_url),
                ("ip", client_ip),
                ("app", client_id),
                ("time", str(timestamp_ms)),
                ("sign", signature),
            )
        )
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    async def _fetch_ticket_payload(
        self,
        verify_url: str,
        provider: ActiveProvider,
    ) -> Mapping[str, object]:
        try:
            response = await self._request("GET", verify_url, provider)
            if not response.is_success:
                raise self._upstream_unavailable()
            payload = response.json()
        except FederationError:
            raise
        except (httpx.HTTPError, TypeError, ValueError):
            raise self._upstream_unavailable() from None
        if not isinstance(payload, dict):
            raise self._upstream_unavailable()
        request_flag = payload.get("REQ_FLAG")
        if request_flag is False:
            raise FederationError(
                code="FEDERATION_UPSTREAM_DENIED",
                message="The JD identity provider denied authorization",
            )
        if request_flag is not True:
            raise self._upstream_unavailable()
        request_data = payload.get("REQ_DATA")
        if not isinstance(request_data, dict):
            raise self._upstream_unavailable()
        return request_data

    @staticmethod
    def _authenticate(
        provider: ActiveProvider,
        settings: JDSSOProviderSettings,
        raw_userinfo: Mapping[str, object],
    ) -> Authenticated:
        mapped_claims = JDSSOAdapter._map_claims(raw_userinfo, settings.user_mapping)
        subject = OAuth2Adapter._required_subject(mapped_claims.get("id"))
        username = OAuth2Adapter._optional_string(raw_userinfo.get("username"))
        email = OAuth2Adapter._optional_string(mapped_claims.get("email"))
        if email is None and username is not None:
            email = f"{username}@jd.com"
            mapped_claims["email"] = email
        display_name = OAuth2Adapter._optional_string(mapped_claims.get("name")) or username
        if display_name is not None:
            mapped_claims["name"] = display_name
        return Authenticated(
            FederatedPrincipal(
                provider_id=provider.id,
                subject=subject,
                email=email,
                email_verified=False,
                display_name=display_name,
                avatar_url=OAuth2Adapter._optional_string(mapped_claims.get("avatar")),
                claims=mapped_claims,
            )
        )

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
