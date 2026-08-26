"""L1 — direct fastmcp self-test of the server matrix (no JoySafeter).

Proves every matrix server behaves before JoySafeter is involved:
  * no-auth servers accept anonymous clients;
  * auth-required servers reject a credential-less client and accept the correct
    credential (rotating static_bearer / header_api_key / custom_header);
  * https servers complete a real TLS handshake against the generated CA;
  * the deterministic ``ping`` / ``echo`` tools return expected values.

Run:  cd tests/mcp_connection_matrix && ../../backend/.venv/bin/python -m pytest test_l1_direct.py -v
"""

from __future__ import annotations

import pytest

import matrix
from mcp_client import make_client, reachable_url

CELLS = matrix.CELLS
AUTH_CELLS = [c for c in CELLS if c.requires_auth]


@pytest.mark.parametrize("cell", CELLS, ids=[c.id for c in CELLS])
async def test_cell_connects_and_tools_work(matrix_servers, ca_path, cell):
    """With the correct credential (when required) the server is fully usable."""
    url = reachable_url(cell)
    async with make_client(cell, ca_path, credentials=True, url=url) as client:
        tool_names = {t.name for t in await client.list_tools()}
        assert {"ping", "echo"} <= tool_names, (
            f"{cell.id}: tools missing ({tool_names})"
        )

        ping = await client.call_tool("ping", {})
        assert ping.data == matrix.PING_RESULT, (
            f"{cell.id}: ping returned {ping.data!r}"
        )

        echo = await client.call_tool("echo", {"text": matrix.ECHO_TEXT})
        assert echo.data == matrix.ECHO_TEXT, f"{cell.id}: echo returned {echo.data!r}"


@pytest.mark.parametrize("cell", AUTH_CELLS, ids=[c.id for c in AUTH_CELLS])
async def test_auth_server_rejects_without_credentials(matrix_servers, ca_path, cell):
    """An auth-required server must refuse a client that presents no credential."""
    url = reachable_url(cell)
    with pytest.raises(Exception):
        async with make_client(cell, ca_path, credentials=False, url=url) as client:
            await client.list_tools()


@pytest.mark.parametrize("cell", AUTH_CELLS, ids=[c.id for c in AUTH_CELLS])
async def test_auth_server_rejects_wrong_credential(matrix_servers, ca_path, cell):
    """A wrong token must be rejected even though the header is present."""
    url = reachable_url(cell)
    # Reconstruct a client whose header carries a corrupted token value.
    bad = _corrupt(cell)
    with pytest.raises(Exception):
        async with make_client(bad, ca_path, credentials=True, url=url) as client:
            await client.list_tools()


def _corrupt(cell):
    """Return a shallow copy of ``cell`` whose auth token is invalid."""
    import dataclasses

    bad_auth = dataclasses.replace(
        cell.server.auth, token_value=cell.server.auth.token_value + "-WRONG"
    )
    bad_server = dataclasses.replace(cell.server, auth=bad_auth)
    return dataclasses.replace(cell, server=bad_server)
