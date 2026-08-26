"""Shared fixtures for the fastmcp <-> JoySafeter connection-matrix suite.

Layers:
  * L1 (``test_l1_direct``)  — direct fastmcp client, needs ``matrix_servers``.
  * L2 (``test_l2_contract``) — real admin API registration; does NOT need the
    servers running (JoySafeter only validates URL shape at registration).
  * L3 (``test_l3_live``)    — gated real agent sessions, needs ``matrix_servers``
    and ``--live``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure suite modules are importable when pytest's rootdir handling varies.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

import matrix
from mcp_servers import MatrixServers
from tls import generate_tls_material


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="run gated L3 live-session tests against the deployment",
    )
    parser.addoption(
        "--jsf-base-url",
        default=os.getenv("JOYSAFETER_TEST_BASE_URL", "http://localhost:8000"),
        help="JoySafeter API base URL (default http://localhost:8000; the :3000 UI calls this)",
    )
    parser.addoption(
        "--jsf-email",
        default=os.getenv("JOYSAFETER_TEST_EMAIL", "admin@joysafeter.com"),
        help="JoySafeter admin email",
    )
    parser.addoption(
        "--jsf-password",
        default=os.getenv("JOYSAFETER_TEST_PASSWORD"),
        help="JoySafeter admin password (or set JOYSAFETER_TEST_PASSWORD)",
    )


# --- server matrix ---------------------------------------------------------------


@pytest.fixture(scope="session")
def tls_material():
    return generate_tls_material(matrix.CERT_SAN_HOSTS, matrix.CERT_SAN_IPS)


@pytest.fixture(scope="session")
def ca_path(tls_material) -> str:
    return tls_material.ca_cert_path


@pytest.fixture(scope="session")
def matrix_servers(tls_material):
    servers = MatrixServers(matrix.SERVER_SPECS, tls_material)
    servers.start_all()
    try:
        yield servers
    finally:
        servers.stop_all()


# --- JoySafeter deployment -------------------------------------------------------


@pytest.fixture(scope="session")
def live_enabled(request) -> bool:
    return bool(request.config.getoption("--live"))


@pytest.fixture(scope="session")
def jsf_config(request) -> dict:
    return {
        "base_url": request.config.getoption("--jsf-base-url"),
        "email": request.config.getoption("--jsf-email"),
        "password": request.config.getoption("--jsf-password"),
    }


@pytest.fixture(scope="session")
def jsf(jsf_config):
    """A logged-in JoySafeter API client (bearer auth, CSRF-exempt)."""
    from joysafeter_client import JoySafeterClient

    if not jsf_config["password"]:
        pytest.fail(
            "JoySafeter API tests require --jsf-password or JOYSAFETER_TEST_PASSWORD"
        )

    client = JoySafeterClient(
        base_url=jsf_config["base_url"],
        email=jsf_config["email"],
        password=jsf_config["password"],
    )
    client.login()
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def tracker(jsf):
    """A per-test resource tracker; created resources are cleaned up on teardown."""
    from joysafeter_client import ResourceTracker

    t = ResourceTracker()
    try:
        yield t
    finally:
        jsf.cleanup(t)
