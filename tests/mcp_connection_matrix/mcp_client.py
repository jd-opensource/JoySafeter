"""Shared fastmcp client helpers for connecting to matrix servers directly.

Used by the L1 direct self-test (and available for ad-hoc probing). TLS cells
are verified against the generated CA via a custom httpx client factory, because
fastmcp calls the factory with connection kwargs (``follow_redirects`` etc.) that
a fixed-signature factory would reject.
"""

from __future__ import annotations

import ssl

import httpx
from fastmcp import Client
from fastmcp.client.transports import SSETransport, StreamableHttpTransport

import matrix
from matrix import Cell


def reachable_url(cell: Cell) -> str:
    """A URL for the cell reachable from the *host* (where L1 runs).

    ``host.docker.internal`` is a container-only name and does not resolve on the
    host, so the ``domain`` form maps to loopback here; the ``ip`` form uses the
    LAN IP (which also proves the server's 0.0.0.0 bind is reachable off-loopback,
    as containers will require). The generated cert's SAN covers both.
    """
    host = matrix.HOST_IP if cell.host_form == "ip" else "127.0.0.1"
    return f"{cell.server.protocol}://{host}:{cell.server.port}{cell.server.path}"


def httpx_factory(ca_path: str | None):
    """Return an ``McpHttpClientFactory`` that trusts ``ca_path`` for TLS."""

    def factory(**kwargs) -> httpx.AsyncClient:
        kwargs.setdefault("follow_redirects", True)
        if ca_path is not None:
            kwargs["verify"] = ssl.create_default_context(cafile=ca_path)
        return httpx.AsyncClient(**kwargs)

    return factory


def build_transport(
    cell: Cell, ca_path: str | None, *, credentials: bool, url: str | None = None
):
    """Build the fastmcp transport for a cell.

    ``credentials`` controls whether the cell's auth header is presented (used to
    test both the accept and reject paths of auth-required servers). ``url``
    overrides the connection URL (L1 uses a host-reachable address).
    """
    headers: dict[str, str] | None = None
    if credentials and cell.auth is not None:
        headers = {
            cell.auth.header_name: f"{cell.auth.value_prefix}{cell.auth.token_value}"
        }

    kwargs: dict = {}
    if headers:
        kwargs["headers"] = headers
    if cell.server.is_tls:
        kwargs["httpx_client_factory"] = httpx_factory(ca_path)

    cls = SSETransport if cell.transport == "sse" else StreamableHttpTransport
    return cls(url or cell.url, **kwargs)


def make_client(
    cell: Cell,
    ca_path: str | None,
    *,
    credentials: bool,
    url: str | None = None,
    timeout: float = 15.0,
) -> Client:
    return Client(
        build_transport(cell, ca_path, credentials=credentials, url=url),
        timeout=timeout,
    )
