"""Regression tests for connection-matrix process isolation."""

from __future__ import annotations

import socket

from starlette.applications import Starlette
from starlette.testclient import TestClient

import matrix
from mcp_servers import InstanceIdentityMiddleware, READINESS_PATH


def test_find_available_base_port_skips_an_occupied_preferred_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        occupied_port = listener.getsockname()[1]

        selected = matrix.find_available_base_port(
            "127.0.0.1",
            preferred_base=occupied_port,
            count=1,
        )

    assert selected != occupied_port


def test_instance_identity_middleware_exposes_only_its_own_token():
    app = InstanceIdentityMiddleware(Starlette(), instance_token="expected-token")

    with TestClient(app) as client:
        response = client.get(READINESS_PATH)

    assert response.status_code == 200
    assert response.text == "expected-token"
