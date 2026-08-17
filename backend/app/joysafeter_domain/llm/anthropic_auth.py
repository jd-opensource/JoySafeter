"""Single authoritative resolver for the anthropic auth scheme.

Anthropic-family credentials can authenticate two ways, which the sandbox
egress (Envoy) injects from two different env keys:
  - ANTHROPIC_API_KEY   -> x-api-key header            (official api.anthropic.com)
  - ANTHROPIC_AUTH_TOKEN -> Authorization: Bearer header (compatible gateways)
The UI collects one key + an intent (auto/xapikey/bearer). This module resolves
the intent to a concrete scheme and rewrites the stored env map so the key lands
in exactly the right field. All credential write/test paths call this so the
tested header always matches the runtime-injected header.
"""

from __future__ import annotations

from urllib.parse import urlparse

OFFICIAL_ANTHROPIC_HOST = "api.anthropic.com"

ANTHROPIC_API_KEY = "ANTHROPIC_API_KEY"
ANTHROPIC_AUTH_TOKEN = "ANTHROPIC_AUTH_TOKEN"
ANTHROPIC_BASE_URL = "ANTHROPIC_BASE_URL"

AUTH_SCHEME_AUTO = "auto"
AUTH_SCHEME_XAPIKEY = "xapikey"
AUTH_SCHEME_BEARER = "bearer"


def _host_of(base_url: str) -> str:
    raw = (base_url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    return (urlparse(raw).hostname or "").lower()


def is_official_anthropic(base_url: str) -> bool:
    host = _host_of(base_url)
    return host == "" or host == OFFICIAL_ANTHROPIC_HOST


def resolve_auth_scheme(base_url: str, requested: str) -> str:
    if requested in (AUTH_SCHEME_XAPIKEY, AUTH_SCHEME_BEARER):
        return requested
    return AUTH_SCHEME_XAPIKEY if is_official_anthropic(base_url) else AUTH_SCHEME_BEARER


def normalize_anthropic_auth(data: dict[str, str], requested_scheme: str) -> dict[str, str]:
    result = dict(data)
    key = (result.get(ANTHROPIC_API_KEY) or result.get(ANTHROPIC_AUTH_TOKEN) or "").strip()
    scheme = resolve_auth_scheme(result.get(ANTHROPIC_BASE_URL, ""), requested_scheme)
    result.pop(ANTHROPIC_API_KEY, None)
    result.pop(ANTHROPIC_AUTH_TOKEN, None)
    if key:
        if scheme == AUTH_SCHEME_BEARER:
            result[ANTHROPIC_AUTH_TOKEN] = key
        else:
            result[ANTHROPIC_API_KEY] = key
    return result
