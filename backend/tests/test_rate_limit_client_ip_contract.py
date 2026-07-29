import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import Request

from app.joysafeter_shared.common.exceptions import register_exception_handlers
from app.joysafeter_shared.config.settings import settings
from app.joysafeter_shared.rate_limit import _rate_limiter, get_client_ip, rate_limit

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
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "")

    request = _request({"X-Forwarded-For": "203.0.113.1", "X-Real-IP": "203.0.113.2"})

    assert get_client_ip(request) == "10.0.0.9"


def test_client_ip_still_ignores_forwarded_headers_without_trusted_proxy_cidr(monkeypatch):
    monkeypatch.setattr(settings, "trust_forwarded_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "")

    request = _request({"X-Forwarded-For": "203.0.113.1", "X-Real-IP": "203.0.113.2"})

    assert get_client_ip(request) == "10.0.0.9"


def test_client_ip_honors_forwarded_headers_only_from_trusted_proxy(monkeypatch):
    monkeypatch.setattr(settings, "trust_forwarded_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "10.0.0.0/8")

    assert (
        get_client_ip(_request({"X-Forwarded-For": "203.0.113.1, 198.51.100.10"}))
        == "203.0.113.1"
    )
    assert get_client_ip(_request({"X-Real-IP": "203.0.113.2"})) == "203.0.113.2"


def test_client_ip_ignores_forwarded_headers_from_untrusted_proxy(monkeypatch):
    monkeypatch.setattr(settings, "trust_forwarded_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "192.0.2.0/24")

    assert get_client_ip(_request({"X-Forwarded-For": "203.0.113.1"})) == "10.0.0.9"


class _FakeRedisRateCounter:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.eval_calls: list[tuple[str, int]] = []

    async def eval(self, _script: str, _num_keys: int, key: str, window_seconds: int):
        self.eval_calls.append((key, window_seconds))
        self.counts[key] = self.counts.get(key, 0) + 1
        return [self.counts[key], window_seconds]


def _rate_limit_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/limited")
    @rate_limit(max_requests=2, window_seconds=60, key_func=lambda request: "rate_limit:test:redis")
    async def limited(request: Request):
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_rate_limit_uses_redis_counter_when_available(monkeypatch):
    _rate_limiter._requests.clear()
    redis = _FakeRedisRateCounter()
    monkeypatch.setattr("app.joysafeter_shared.rate_limit.RedisClient.get_client", staticmethod(lambda: redis))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_rate_limit_app()), base_url="http://test") as client:
        assert (await client.get("/limited")).status_code == 200
        assert (await client.get("/limited")).status_code == 200
        limited = await client.get("/limited")

    assert limited.status_code == 429
    assert limited.json()["code"] == "RATE_LIMITED"
    assert redis.eval_calls == [("rate_limit:test:redis", 60)] * 3
    assert "rate_limit:test:redis" not in _rate_limiter._requests
