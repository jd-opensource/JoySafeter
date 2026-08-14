"""Single canonical normal form for MCP server URLs.

This is the authoritative normalization contract shared with the Rust
``mcp_url::normalize`` (see ``kernel/mcp_url.rs``). Both languages must produce
byte-identical output for the same input so that the DB uniqueness constraint
``(group_id, normalized_mcp_server_url)`` and the runtime credential match agree
on ONE normal form (replacing the old multi-candidate-key matching).

Contract:
  1. Trim surrounding whitespace.
  2. Parse as a URL; lowercase the scheme and host.
  3. Remove a default port (``:443`` for https, ``:80`` for http); keep others.
  4. Strip a single trailing ``/`` from the path; the empty/``"/"`` path
     normalizes to empty (so ``https://h.com/`` == ``https://h.com``).
  5. Keep the query string (query is part of MCP endpoint identity).
  6. Drop the fragment.
  7. Return the reassembled URL string.
If the input does not parse as a URL, return the trimmed input unchanged.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

_DEFAULT_PORTS = {"https": 443, "http": 80}


def normalize_mcp_url(raw: str) -> str:
    trimmed = raw.strip()

    parts = urlsplit(trimmed)
    # A valid URL for our purposes has both a scheme and a network location.
    # Anything else (bare strings, relative paths) is returned unchanged.
    if not parts.scheme or not parts.netloc:
        return trimmed

    scheme = parts.scheme.lower()

    host = (parts.hostname or "").lower()
    if not host:
        return trimmed

    port = parts.port
    if port is not None and _DEFAULT_PORTS.get(scheme) == port:
        port = None

    netloc = host
    if parts.username is not None or parts.password is not None:
        userinfo = parts.username or ""
        if parts.password is not None:
            userinfo = f"{userinfo}:{parts.password}"
        netloc = f"{userinfo}@{netloc}"
    if port is not None:
        netloc = f"{netloc}:{port}"

    # Strip a single trailing slash; the empty/"/" path becomes "".
    path = parts.path
    if path == "/":
        path = ""
    elif path.endswith("/"):
        path = path[:-1]

    # Keep query, drop fragment.
    return urlunsplit((scheme, netloc, path, parts.query, ""))
