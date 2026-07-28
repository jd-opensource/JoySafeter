"""webhook cURL sample builder computes a correct HMAC-SHA256 signature."""

import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService

pytestmark = pytest.mark.no_db


class _StubService(JoySafeterTriggerService):
    def __init__(self, secret: str) -> None:
        self._secret = secret
        self.db = SimpleNamespace()

    async def _resolve_webhook_secret(self, trigger):
        return self._secret


@pytest.mark.asyncio
async def test_build_webhook_curl_signs_sample_body():
    svc = _StubService("s3kret")
    trigger = SimpleNamespace(id="TID", secret_ref="hook", secret_key="WEBHOOK_SECRET")
    url = "https://api.example.com/api/v1/triggers/trig_TID/webhook"
    sample = {"example": "payload"}

    curl = await svc.build_webhook_curl(trigger, url=url, sample_body=sample)

    body = json.dumps(sample, separators=(",", ":"))
    expected_sig = hmac.new(b"s3kret", body.encode(), hashlib.sha256).hexdigest()
    assert url in curl
    assert f"X-JoySafeter-Signature: sha256={expected_sig}" in curl
    assert f"-d '{body}'" in curl
