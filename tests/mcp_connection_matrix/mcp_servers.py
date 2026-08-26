"""fastmcp server matrix: build + run the 8 servers of the connection matrix.

Each server is a ``FastMCP`` app served over its transport (SSE / streamable
HTTP), optionally TLS-wrapped and optionally guarded by a static-header auth
shim that mirrors JoySafeter's egress credential injection.
"""

from __future__ import annotations

import hmac
import http.client
import multiprocessing as mp
import ssl
import time

import uvicorn
from fastmcp import FastMCP

import matrix
from matrix import ServerSpec
from tls import TlsMaterial

READINESS_PATH = "/.well-known/joysafeter-mcp-matrix-ready"


class InstanceIdentityMiddleware:
    """Expose an unambiguous readiness token for the owning parent process."""

    def __init__(self, app, instance_token: str) -> None:
        self.app = app
        self._token = instance_token.encode("ascii")

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope.get("path") == READINESS_PATH:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"text/plain; charset=utf-8"),
                        (b"content-length", str(len(self._token)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": self._token})
            return
        await self.app(scope, receive, send)


# --- static-header auth shim -----------------------------------------------------


class StaticAuthMiddleware:
    """Reject requests whose single expected header is missing/incorrect.

    Pure-ASGI so it also guards the SSE and streamable-HTTP sub-paths. Mirrors
    the header JoySafeter's Envoy egress injects for each auth scheme.
    """

    def __init__(self, app, header_name: str, expected_value: str) -> None:
        self.app = app
        self._header = header_name.lower().encode("latin-1")
        self._expected = expected_value.encode("latin-1")

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        got = headers.get(self._header)
        if got is None or not hmac.compare_digest(got, self._expected):
            body = b'{"error":"unauthorized"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("latin-1")),
                        (b"www-authenticate", b"MCP"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


# --- app construction ------------------------------------------------------------


def build_fastmcp(spec: ServerSpec) -> FastMCP:
    server = FastMCP(name=f"matrix-{spec.key}")

    @server.tool
    def ping() -> str:
        """Return a constant so connectivity is verifiable."""
        return matrix.PING_RESULT

    @server.tool
    def echo(text: str) -> str:
        """Echo the input back unchanged."""
        return text

    return server


def build_app(spec: ServerSpec):
    server = build_fastmcp(spec)
    app = server.http_app(
        path=spec.path,
        transport=matrix.TRANSPORT_HTTP_APP_KIND[spec.transport],
    )
    if spec.auth is not None:
        header_name, expected_value = spec.auth.wire_header
        app.add_middleware(
            StaticAuthMiddleware,
            header_name=header_name,
            expected_value=expected_value,
        )
    app.add_middleware(
        InstanceIdentityMiddleware,
        instance_token=spec.instance_token,
    )
    return app


# --- process management ----------------------------------------------------------
#
# Each server runs in its own *spawned* process. fastmcp's http lifespan opens an
# in-memory Docket task queue whose module-level asyncio lock binds to a single
# event loop, so running several servers as threads in one interpreter fails with
# "bound to a different event loop". Separate processes give each server its own
# interpreter globals + loop, and avoid touching the production Redis.


def _run_server(
    spec: ServerSpec, ssl_certfile: str | None, ssl_keyfile: str | None
) -> None:
    """Child-process entrypoint: build the app and serve it (blocking)."""
    config_kwargs: dict = {
        "app": build_app(spec),
        "host": matrix.BIND_HOST,
        "port": spec.port,
        "log_level": "warning",
        "access_log": False,
        "loop": "asyncio",
    }
    if spec.is_tls:
        config_kwargs["ssl_certfile"] = ssl_certfile
        config_kwargs["ssl_keyfile"] = ssl_keyfile
    uvicorn.Server(uvicorn.Config(**config_kwargs)).run()


class ServerProcess:
    """One uvicorn server for a spec, running in a spawned process."""

    _ctx = mp.get_context("spawn")

    def __init__(self, spec: ServerSpec, tls: TlsMaterial | None) -> None:
        self.spec = spec
        if spec.is_tls and tls is None:
            raise RuntimeError(f"TLS material required for https server {spec.key}")
        cert = tls.server_cert_path if (spec.is_tls and tls) else None
        key = tls.server_key_path if (spec.is_tls and tls) else None
        self._ca_cert_path = tls.ca_cert_path if (spec.is_tls and tls) else None
        self._proc = self._ctx.Process(
            target=_run_server,
            args=(spec, cert, key),
            name=f"mcp-{spec.key}",
            daemon=True,
        )

    def start(self) -> None:
        self._proc.start()

    def wait_ready(self, timeout: float = 25.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._proc.is_alive():
                raise RuntimeError(
                    f"server {self.spec.key} on :{self.spec.port} exited during startup "
                    f"with code {self._proc.exitcode}"
                )
            if self._owns_listener():
                return
            time.sleep(0.05)
        raise TimeoutError(
            f"server {self.spec.key} on :{self.spec.port} not ready in {timeout}s"
        )

    def _owns_listener(self) -> bool:
        connection: http.client.HTTPConnection
        if self.spec.is_tls:
            context = ssl.create_default_context(cafile=self._ca_cert_path)
            connection = http.client.HTTPSConnection(
                "127.0.0.1",
                self.spec.port,
                timeout=0.5,
                context=context,
            )
        else:
            connection = http.client.HTTPConnection(
                "127.0.0.1",
                self.spec.port,
                timeout=0.5,
            )
        try:
            connection.request("GET", READINESS_PATH)
            response = connection.getresponse()
            body = response.read().decode("ascii")
            return response.status == 200 and hmac.compare_digest(
                body,
                self.spec.instance_token,
            )
        except (OSError, UnicodeError):
            return False
        finally:
            connection.close()

    def stop(self) -> None:
        if self._proc.is_alive():
            self._proc.terminate()
        self._proc.join(timeout=10.0)


class MatrixServers:
    """Start/stop the full set of matrix servers."""

    def __init__(self, specs: list[ServerSpec], tls: TlsMaterial | None) -> None:
        self._procs = [ServerProcess(spec, tls) for spec in specs]

    def start_all(self) -> None:
        for proc in self._procs:
            proc.start()
        for proc in self._procs:
            proc.wait_ready()

    def stop_all(self) -> None:
        for proc in self._procs:
            proc.stop()
