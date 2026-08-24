"""Cross-language MCP-URL normalization vectors.

These vectors are the shared contract between the Python
``normalize_mcp_url`` and the Rust ``mcp_url::normalize``: both languages must
map every ``raw`` input to the same ``normalized`` canonical form, so the DB
uniqueness constraint ``(group_id, normalized_mcp_server_url)`` and the runtime
credential match agree on a single normal form.
"""

import json
from pathlib import Path

import pytest

from app.joysafeter_shared.mcp_url import normalize_mcp_url
from app.joysafeter_shared.security.ssrf_guard import validate_url_scheme

pytestmark = pytest.mark.no_db

_VECTORS_PATH = Path(__file__).parent / "fixtures" / "mcp_url_vectors.json"
_ADDRESS_VECTORS_PATH = Path(__file__).parent / "fixtures" / "mcp_network_address_vectors.json"


def _load_vectors() -> list[dict]:
    return json.loads(_VECTORS_PATH.read_text(encoding="utf-8"))


def _load_address_vectors() -> list[dict]:
    return json.loads(_ADDRESS_VECTORS_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("vector", _load_vectors())
def test_normalize_matches_vector(vector: dict) -> None:
    assert normalize_mcp_url(vector["raw"]) == vector["normalized"]


def test_trailing_slash_and_bare_are_equal() -> None:
    assert normalize_mcp_url("https://example.com/mcp/") == normalize_mcp_url("https://example.com/mcp")


def test_default_port_removed_but_custom_kept() -> None:
    assert normalize_mcp_url("https://h.com:443/x") == "https://h.com/x"
    assert normalize_mcp_url("https://h.com:8443/x") == "https://h.com:8443/x"


@pytest.mark.parametrize("vector", _load_address_vectors())
def test_write_time_literal_ip_policy_matches_shared_vectors(vector: dict) -> None:
    url = f"http://[{vector['address']}]/mcp" if ":" in vector["address"] else f"http://{vector['address']}/mcp"
    if vector["default_allowed"]:
        assert validate_url_scheme(url) == url
    else:
        with pytest.raises(ValueError, match="blocked address"):
            validate_url_scheme(url)
