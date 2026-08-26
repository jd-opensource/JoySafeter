"""Connection-matrix definitions for the fastmcp <-> JoySafeter E2E suite.

The Cartesian product under test:

    transport ∈ {sse, streamable_http}
    auth      ∈ {none, required}          # required rotates all 3 schemes
    protocol  ∈ {http, https}
    host      ∈ {domain, ip}

= 16 logical cells, realized as 8 fastmcp server processes
(transport × protocol × auth_kind), each addressed two ways (domain / ip).

The three JoySafeter MCP auth schemes are rotated across the four ``required``
servers so all of ``static_bearer`` / ``header_api_key`` / ``custom_header`` are
exercised (index % 3 over the auth servers gives [bearer, api_key, custom,
bearer] — all three present).
"""

from __future__ import annotations

import os
import secrets
import socket
from dataclasses import dataclass

# --- addressing ------------------------------------------------------------------

HOST_DOMAIN = os.getenv("JOYSAFETER_TEST_HOST_DOMAIN", "host.docker.internal")


def _detect_host_ip() -> str:
    """Best-effort host LAN IP that Docker containers can route to.

    On Docker Desktop for macOS containers reach the host via
    ``host.docker.internal`` (an internal gateway) but the host's LAN IP is also
    routable. Overridable via ``JOYSAFETER_TEST_HOST_IP``.
    """
    override = os.getenv("JOYSAFETER_TEST_HOST_IP")
    if override:
        return override
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # No packet is sent; this just selects the default egress interface.
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


HOST_IP = _detect_host_ip()

# Bind address for the fastmcp servers (must be reachable from containers).
BIND_HOST = os.getenv("JOYSAFETER_TEST_BIND_HOST", "0.0.0.0")

# Extra names/addresses the TLS leaf cert must be valid for, so any host form
# used to reach an https server validates against the generated CA.
CERT_SAN_HOSTS = ["localhost", HOST_DOMAIN]
CERT_SAN_IPS = sorted({"127.0.0.1", HOST_IP, "192.168.5.2"})

DEFAULT_BASE_PORT = 3400


def _port_block_available(bind_host: str, base_port: int, count: int) -> bool:
    listeners: list[socket.socket] = []
    try:
        for port in range(base_port, base_port + count):
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listeners.append(listener)
            listener.bind((bind_host, port))
        return True
    except OSError:
        return False
    finally:
        for listener in listeners:
            listener.close()


def find_available_base_port(
    bind_host: str,
    *,
    preferred_base: int,
    count: int,
) -> int:
    """Return the first contiguous available port block at/after ``preferred_base``."""
    if not 1 <= preferred_base <= 65535:
        raise ValueError("preferred_base must be between 1 and 65535")
    if count < 1 or preferred_base + count - 1 > 65535:
        raise ValueError("count does not fit in the TCP port range")

    final_base = 65535 - count + 1
    for candidate in range(preferred_base, final_base + 1):
        if _port_block_available(bind_host, candidate, count):
            return candidate
    raise RuntimeError(
        f"no contiguous block of {count} ports available at or after {preferred_base}"
    )


# --- transports / schemes --------------------------------------------------------

TRANSPORTS = ("sse", "streamable_http")
PROTOCOLS = ("http", "https")
AUTH_KINDS = ("none", "required")
HOST_FORMS = ("domain", "ip")

_configured_base_port = os.getenv("JOYSAFETER_TEST_BASE_PORT")
_server_count = len(TRANSPORTS) * len(PROTOCOLS) * len(AUTH_KINDS)
BASE_PORT = (
    int(_configured_base_port)
    if _configured_base_port is not None
    else find_available_base_port(
        BIND_HOST,
        preferred_base=DEFAULT_BASE_PORT,
        count=_server_count,
    )
)

# JoySafeter canonical MCP auth schemes (see CredentialAuthScheme).
SCHEME_BEARER = "static_bearer"
SCHEME_API_KEY = "header_api_key"
SCHEME_CUSTOM = "custom_header"
ROTATED_SCHEMES = (SCHEME_BEARER, SCHEME_API_KEY, SCHEME_CUSTOM)

# MCP endpoint sub-paths per transport (fastmcp defaults we pin explicitly).
TRANSPORT_PATH = {"streamable_http": "/mcp", "sse": "/sse"}
# fastmcp transport= kwarg value for http_app().
TRANSPORT_HTTP_APP_KIND = {"streamable_http": "streamable-http", "sse": "sse"}


@dataclass(frozen=True)
class AuthMaterial:
    """How a scheme's secret is presented on the wire and stored in JoySafeter.

    ``header_name``/``value_prefix`` mirror ``validate_mcp_credential_material``.
    """

    scheme: str
    token_value: str
    header_name: str
    value_prefix: str

    @property
    def wire_header(self) -> tuple[str, str]:
        """The (lowercased header name, exact value) the server must receive."""
        return self.header_name.lower(), f"{self.value_prefix}{self.token_value}"

    def credential_data(self) -> dict[str, str]:
        """The JoySafeter credential ``data`` payload for this scheme."""
        if self.scheme == SCHEME_BEARER:
            return {"token_value": self.token_value}
        if self.scheme == SCHEME_API_KEY:
            return {"token_value": self.token_value, "header_name": self.header_name}
        return {
            "token_value": self.token_value,
            "header_name": self.header_name,
            "value_prefix": self.value_prefix,
        }


def _auth_material(scheme: str) -> AuthMaterial:
    token = f"jsf-{scheme}-{secrets.token_hex(8)}"
    if scheme == SCHEME_BEARER:
        return AuthMaterial(scheme, token, "Authorization", "Bearer ")
    if scheme == SCHEME_API_KEY:
        return AuthMaterial(scheme, token, "X-Api-Key", "")
    if scheme == SCHEME_CUSTOM:
        return AuthMaterial(scheme, token, "X-Service-Authorization", "Token ")
    raise ValueError(f"unknown scheme {scheme!r}")


@dataclass(frozen=True)
class ServerSpec:
    """One fastmcp server process (transport × protocol × auth_kind)."""

    index: int
    transport: str  # "sse" | "streamable_http"
    protocol: str  # "http" | "https"
    auth_kind: str  # "none" | "required"
    port: int
    auth: AuthMaterial | None  # None when auth_kind == "none"
    instance_token: str

    @property
    def key(self) -> str:
        return f"{self.transport}-{self.auth_kind}-{self.protocol}"

    @property
    def path(self) -> str:
        return TRANSPORT_PATH[self.transport]

    @property
    def is_tls(self) -> bool:
        return self.protocol == "https"

    def url(self, host_form: str) -> str:
        host = HOST_DOMAIN if host_form == "domain" else HOST_IP
        return f"{self.protocol}://{host}:{self.port}{self.path}"


@dataclass(frozen=True)
class Cell:
    """One logical matrix cell: a server addressed via one host form."""

    server: ServerSpec
    host_form: str  # "domain" | "ip"

    @property
    def id(self) -> str:
        auth = self.server.auth.scheme if self.server.auth else "noauth"
        return f"{self.server.transport}.{auth}.{self.server.protocol}.{self.host_form}"

    @property
    def url(self) -> str:
        return self.server.url(self.host_form)

    @property
    def transport(self) -> str:
        return self.server.transport

    @property
    def requires_auth(self) -> bool:
        return self.server.auth_kind == "required"

    @property
    def auth(self) -> AuthMaterial | None:
        return self.server.auth


def build_server_specs() -> list[ServerSpec]:
    """The 8 server processes, with schemes rotated across the auth servers."""
    specs: list[ServerSpec] = []
    port = BASE_PORT
    index = 0
    auth_index = 0
    for transport in TRANSPORTS:
        for protocol in PROTOCOLS:
            for auth_kind in AUTH_KINDS:
                auth: AuthMaterial | None = None
                if auth_kind == "required":
                    scheme = ROTATED_SCHEMES[auth_index % len(ROTATED_SCHEMES)]
                    auth = _auth_material(scheme)
                    auth_index += 1
                specs.append(
                    ServerSpec(
                        index=index,
                        transport=transport,
                        protocol=protocol,
                        auth_kind=auth_kind,
                        port=port,
                        auth=auth,
                        instance_token=secrets.token_urlsafe(24),
                    )
                )
                index += 1
                port += 1
    return specs


def build_cells(specs: list[ServerSpec]) -> list[Cell]:
    """The 16 logical cells (each server addressed via domain and ip)."""
    return [Cell(server=spec, host_form=hf) for spec in specs for hf in HOST_FORMS]


# Deterministic tool contract every server exposes.
ECHO_TEXT = "joysafeter-mcp-matrix"
PING_RESULT = "pong"

# Import-time singletons so the fixture-started servers and the parametrized test
# cells share the SAME per-run auth tokens. Rebuilding would mint fresh tokens and
# break auth matching. Child (spawned) server processes receive their spec via
# pickled args, so their re-import recomputing these is harmless.
SERVER_SPECS = build_server_specs()
CELLS = build_cells(SERVER_SPECS)
