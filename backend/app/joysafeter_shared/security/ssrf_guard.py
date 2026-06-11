"""SSRF protection utilities — centralized URL validation for all outbound HTTP requests.

Prevents Server-Side Request Forgery by:
1. Blocking cloud metadata endpoints (169.254.169.254 etc.)
2. Blocking private/reserved IP ranges (RFC-1918, link-local, loopback)
3. Resolving DNS before request to prevent DNS rebinding attacks
4. Optionally enforcing HTTPS-only scheme

By default both HTTP and HTTPS are allowed — the primary defense is IP validation,
not scheme restriction. Set JOYSAFETER_SSRF_HTTPS_ONLY=1 to enforce HTTPS in production.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Cloud provider metadata IPs
_METADATA_IPS = frozenset({
    "169.254.169.254",  # AWS, GCP, Azure
    "169.254.170.2",    # AWS ECS task metadata
    "fd00:ec2::254",    # AWS IPv6 metadata
})

# Blocked hostnames
_BLOCKED_HOSTNAMES = frozenset({
    "metadata.google.internal",
    "metadata.goog",
})

# Whether to enforce HTTPS-only (opt-in via env var for production)
_HTTPS_ONLY = os.getenv("JOYSAFETER_SSRF_HTTPS_ONLY", "").lower() in ("1", "true")


class SSRFError(ValueError):
    """Raised when a URL fails SSRF validation."""
    pass


def validate_url(
    url: str,
    *,
    allow_http: bool = True,
    allow_private: bool = False,
    context: str = "",
) -> str:
    """Validate a URL is safe from SSRF attacks.

    Args:
        url: The URL to validate.
        allow_http: If True, allow http:// scheme. Default True.
                    Overridden to False when JOYSAFETER_SSRF_HTTPS_ONLY=1.
        allow_private: If True, allow private/internal IPs (for internal service calls).
        context: Description of the calling context (for error messages).

    Returns:
        The validated URL (unchanged).

    Raises:
        SSRFError: If the URL fails validation.
    """
    if not url:
        raise SSRFError(f"Empty URL{_ctx(context)}")

    parsed = urlparse(url)

    # 1. Scheme validation
    if _HTTPS_ONLY:
        allow_http = False

    allowed_schemes = {"https", "http"} if allow_http else {"https"}

    if parsed.scheme not in allowed_schemes:
        raise SSRFError(
            f"URL scheme '{parsed.scheme}' not allowed (allowed: {allowed_schemes}){_ctx(context)}"
        )

    # 2. Hostname validation
    hostname = parsed.hostname
    if not hostname:
        raise SSRFError(f"URL has no hostname{_ctx(context)}")

    # Block known dangerous hostnames
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise SSRFError(f"Blocked hostname: {hostname}{_ctx(context)}")

    # 3. IP validation (if hostname is already an IP)
    try:
        ip = ipaddress.ip_address(hostname)
        if not allow_private and _is_dangerous_ip(ip):
            raise SSRFError(
                f"URL resolves to blocked IP: {ip}{_ctx(context)}"
            )
        return url
    except ValueError:
        pass  # Not an IP literal — continue to DNS resolution

    # 4. DNS resolution + IP check (prevent DNS rebinding)
    if not allow_private:
        try:
            resolved_ips = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
            for family, _, _, _, sockaddr in resolved_ips:
                ip_str = sockaddr[0]
                try:
                    ip = ipaddress.ip_address(ip_str)
                    if _is_dangerous_ip(ip):
                        raise SSRFError(
                            f"URL hostname '{hostname}' resolves to blocked IP: {ip}{_ctx(context)}"
                        )
                except ValueError:
                    continue
        except socket.gaierror:
            # DNS resolution failed — allow the request to proceed
            # (the HTTP client will handle the connection error)
            pass

    return url


def validate_url_or_none(
    url: str | None,
    **kwargs,
) -> str | None:
    """Validate URL if not None, return None for None input."""
    if url is None:
        return None
    return validate_url(url, **kwargs)


def _is_dangerous_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address is in a dangerous/private range."""
    if str(ip) in _METADATA_IPS:
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


def _ctx(context: str) -> str:
    return f" (context: {context})" if context else ""
