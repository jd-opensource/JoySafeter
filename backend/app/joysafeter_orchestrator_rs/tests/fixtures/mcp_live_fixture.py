from __future__ import annotations

import json
import os
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _payload(self) -> bytes:
        return json.dumps(
            {
                "method": self.command,
                "path": self.path,
                "host": self.headers.get("host"),
                "authorization": self.headers.get("authorization"),
                "x_api_key": self.headers.get("x-api-key"),
                "x_custom_auth": self.headers.get("x-custom-auth"),
                "server_port": self.server.server_port,
            },
            sort_keys=True,
        ).encode()

    def _serve(self) -> None:
        if self.path.startswith("/events/"):
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "close")
            self.end_headers()
            self.wfile.write(b"data: first\n\n")
            self.wfile.flush()
            time.sleep(1.0)
            self.wfile.write(b"data: second\n\n")
            self.wfile.flush()
            self.close_connection = True
            return

        payload = self._payload()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _serve
    do_POST = _serve


def serve(port: int, *, tls: bool) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    if tls:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain("/fixture/cert.pem", "/fixture/key.pem")
        server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


threads = [
    threading.Thread(target=serve, args=(80,), kwargs={"tls": False}, daemon=True),
    threading.Thread(target=serve, args=(8765,), kwargs={"tls": False}, daemon=True),
    threading.Thread(target=serve, args=(443,), kwargs={"tls": True}, daemon=True),
    threading.Thread(target=serve, args=(8443,), kwargs={"tls": True}, daemon=True),
]
for thread in threads:
    thread.start()

print(json.dumps({"ready": True, "pid": os.getpid()}), flush=True)
threads[0].join()
