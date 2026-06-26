"""SSRF protection utilities — centralized URL validation for all outbound HTTP requests.

Prevents Server-Side Request Forgery by blocking truly dangerous endpoints:
1. Cloud metadata endpoints (169.254.169.254, fd00:ec2::254, etc.)
2. Known dangerous hostnames (metadata.google.internal, etc.)

Private/internal IPs (10.x, 172.16.x, 192.168.x, 127.0.0.1) are ALLOWED by default
because many legitimate services run on the internal network (LLM APIs, MCP servers,
internal tooling). Only cloud metadata and link-local addresses are blocked.

Set JOYSAFETER_SSRF_BLOCK_PRIVATE=1 to also block RFC-1918 private IPs when the
deployment does not need internal network access from the backend.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Cloud provider metadata IPs — these are ALWAYS blocked
_METADATA_IPS = frozenset({
    "169.254.169.254",  # AWS, GCP, Azure instance metadata
    "169.254.170.2",    # AWS ECS task metadata
    "100.100.100.200",  # Alibaba Cloud metadata
    "fd00:ec2::254",    # AWS IPv6 metadata
})

# Blocked hostnames — these are ALWAYS blocked
_BLOCKED_HOSTNAMES = frozenset({
    "metadata.google.internal",
    "metadata.goog",
})

# Blocked scheme — file://, ftp://, gopher:// etc.
_ALLOWED_SCHEMES = {"http", "https"}

# Opt-in: also block RFC-1918 private IPs (for deployments that don't need internal access)
_BLOCK_PRIVATE = os.getenv("JOYSAFETER_SSRF_BLOCK_PRIVATE", "").lower() in ("1", "true")

# Opt-in: enforce HTTPS only
_HTTPS_ONLY = os.getenv("JOYSAFETER_SSRF_HTTPS_ONLY", "").lower() in ("1", "true")


class SSRFError(ValueError):
    """Raised when a URL fails SSRF validation."""
    pass


def validate_url(
    url: str,
    *,
    allow_http: bool = True,
    allow_private: bool = True,
    context: str = "",
) -> str:
    """Validate a URL is safe from SSRF attacks.

    By default this allows HTTP, HTTPS, and private/internal IPs.
    Only truly dangerous destinations (cloud metadata, link-local) are blocked.

    Args:
        url: The URL to validate.
        allow_http: If True (default), allow http:// scheme.
                    Overridden to False by JOYSAFETER_SSRF_HTTPS_ONLY=1.
        allow_private: If True (default), allow private/internal IPs (10.x, 172.x, 192.168.x).
                       Overridden to False by JOYSAFETER_SSRF_BLOCK_PRIVATE=1.
                       Cloud metadata IPs are ALWAYS blocked regardless of this flag.
        context: Description for error messages.

    Returns:
        The validated URL (unchanged).

    Raises:
        SSRFError: If the URL fails validation.
    """
    url = url.strip()
    if not url:
        raise SSRFError(f"Empty URL{_ctx(context)}")

    parsed = urlparse(url)

    # 1. Scheme validation
    if _HTTPS_ONLY:
        allow_http = False
    if _BLOCK_PRIVATE:
        allow_private = False

    allowed = {"https", "http"} if allow_http else {"https"}
    if parsed.scheme not in allowed:
        raise SSRFError(
            f"URL scheme '{parsed.scheme}' not allowed{_ctx(context)}"
        )

    # 2. Hostname validation
    hostname = parsed.hostname
    if not hostname:
        raise SSRFError(f"URL has no hostname{_ctx(context)}")

    # Block known dangerous hostnames
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise SSRFError(f"Blocked hostname: {hostname}{_ctx(context)}")

    # 3. IP validation (if hostname is already an IP literal)
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None  # Not an IP literal — will resolve via DNS below

    if ip is not None:
        if _is_metadata_ip(ip):
            raise SSRFError(f"URL points to blocked metadata IP: {ip}{_ctx(context)}")
        if not allow_private and ip.is_private:
            raise SSRFError(f"URL points to private IP: {ip}{_ctx(context)}")
        return url

    # 4. DNS resolution + IP check (prevent DNS rebinding to metadata endpoints)
    try:
        resolved_ips = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
        for family, _, _, _, sockaddr in resolved_ips:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
                if _is_metadata_ip(ip):
                    raise SSRFError(
                        f"URL hostname '{hostname}' resolves to metadata IP: {ip}{_ctx(context)}"
                    )
                if not allow_private and ip.is_private:
                    raise SSRFError(
                        f"URL hostname '{hostname}' resolves to private IP: {ip}{_ctx(context)}"
                    )
            except ValueError:
                continue
    except socket.gaierror:
        pass  # DNS resolution failed — allow for internal network services

    return url


def validate_url_or_none(
    url: str | None,
    **kwargs,
) -> str | None:
    """Validate URL if not None, return None for None input."""
    if url is None:
        return None
    return validate_url(url, **kwargs)


def _is_metadata_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP is a cloud metadata or link-local address (always dangerous)."""
    if str(ip) in _METADATA_IPS:
        return True
    # Link-local (169.254.x.x) — metadata range, always block
    if ip.is_link_local:
        return True
    # Multicast — no reason to allow outbound requests to multicast
    if ip.is_multicast:
        return True
    return False


def _ctx(context: str) -> str:
    return f" (context: {context})" if context else ""


# ---------------------------------------------------------------------------
# Pydantic field validators — lightweight URL format checks for input schemas
# (no DNS resolution, just scheme + basic structure validation)
# ---------------------------------------------------------------------------


def validate_url_scheme(url: str | None) -> str | None:
    """Pydantic field validator: ensure URL uses http:// or https:// scheme.

    Use as a Pydantic @field_validator for URL fields in request schemas.
    This is a fast, input-time check — the full SSRF guard (with DNS resolution
    and IP checks) runs at request-time in the service layer.
    """
    if url is None:
        return None
    url = url.strip()
    if not url:
        return url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"URL must use http:// or https:// scheme, got '{parsed.scheme}://'"
        )
    if not parsed.hostname:
        raise ValueError("URL must have a valid hostname")
    return url
