import pytest
from starlette.requests import Request

from app.joysafeter_shared.config.settings import settings
from app.joysafeter_shared.rate_limit import get_client_ip

pytestmark = pytest.mark.no_db


def _request(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("10.0.0.9", 34567),
            "path": "/api/v1/test",
            "headers": [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in headers.items()],
            "query_string": b"",
        }
    )


def test_client_ip_ignores_spoofable_forwarded_headers_by_default(monkeypatch):
    monkeypatch.setattr(settings, "trust_forwarded_headers", False)

    request = _request({"X-Forwarded-For": "203.0.113.1", "X-Real-IP": "203.0.113.2"})

    assert get_client_ip(request) == "10.0.0.9"


def test_client_ip_honors_forwarded_headers_only_when_trusted(monkeypatch):
    monkeypatch.setattr(settings, "trust_forwarded_headers", True)

    assert (
        get_client_ip(_request({"X-Forwarded-For": "203.0.113.1, 198.51.100.10"}))
        == "203.0.113.1"
    )
    assert get_client_ip(_request({"X-Real-IP": "203.0.113.2"})) == "203.0.113.2"
