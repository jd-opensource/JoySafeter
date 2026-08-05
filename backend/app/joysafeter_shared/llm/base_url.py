"""Shared validation for backend-originated LLM base URLs."""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse

from app.joysafeter_shared.security.ssrf_guard import SSRFError, validate_url


class LLMBaseUrlError(ValueError):
    def __init__(self, *, reason: str, key: str, base_url: str, host: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.key = key
        self.base_url = base_url
        self.host = host


def allowed_llm_hosts() -> list[str]:
    raw = os.getenv("JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS", "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def normalize_llm_host(raw: str, *, allow_wildcard: bool = False) -> str | None:
    value = raw.strip().lower()
    if not value:
        return None
    if "://" in value:
        hostname = urlparse(value).hostname
        return hostname.strip(".").lower() if hostname else None
    if "/" in value:
        value = value.split("/", 1)[0]
    if value.startswith("["):
        end = value.find("]")
        if end < 0:
            return None
        value = value[1:end]
    elif ":" in value:
        host, port = value.rsplit(":", 1)
        if ":" not in host and port.isdigit():
            value = host
    value = value.strip(".")
    if not value:
        return None
    if value.startswith("*."):
        suffix = value[2:]
        if not allow_wildcard or not suffix or "*" in suffix:
            return None
        return f"*.{suffix}"
    if "*" in value:
        return None
    return value


def is_blocked_llm_host(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host in {"metadata.google.internal", "metadata.goog"}
    return ip.is_link_local or ip.is_multicast or str(ip) in {"169.254.169.254", "169.254.170.2", "100.100.100.200"}


def llm_host_matches(host: str, pattern: str) -> bool:
    if pattern.startswith("*."):
        suffix = pattern[2:]
        return host.endswith(f".{suffix}") and host != suffix
    return host == pattern


def validate_llm_base_url(base_url: str, *, key: str) -> str:
    try:
        validate_url(base_url, allow_http=True, allow_private=True, context=key)
    except SSRFError as exc:
        raise LLMBaseUrlError(reason="invalid", key=key, base_url=base_url) from exc

    parsed_host = urlparse(base_url).hostname
    host = normalize_llm_host(parsed_host or "")
    if not host or is_blocked_llm_host(host):
        raise LLMBaseUrlError(reason="invalid", key=key, base_url=base_url)

    allowed_patterns = [
        pattern for entry in allowed_llm_hosts() if (pattern := normalize_llm_host(entry, allow_wildcard=True))
    ]
    if not any(llm_host_matches(host, pattern) for pattern in allowed_patterns):
        raise LLMBaseUrlError(reason="not_allowed", key=key, base_url=base_url, host=host)

    return base_url
