import pytest

from app.joysafeter_identity_federation.domain.errors import FederationError
from app.joysafeter_identity_federation.infrastructure.correlation import SignedCorrelationCodec

pytestmark = pytest.mark.no_db


def test_signed_correlation_rejects_tampering_and_expiry() -> None:
    codec = SignedCorrelationCodec(secret=b"application-secret", cookie_name="federation_attempt")
    value = codec.sign("attempt-1", expires_at=1_786_748_600)

    assert codec.verify(value, now_epoch=1_786_748_000) == "attempt-1"
    with pytest.raises(FederationError):
        codec.verify(value + "x", now_epoch=1_786_748_000)
    with pytest.raises(FederationError):
        codec.verify(value, now_epoch=1_786_748_601)


@pytest.mark.parametrize("value", ["", "attempt.expiry", "....", "a.b.c.d", "@@@.MQ.@@@"])
def test_signed_correlation_rejects_malformed_values(value: str) -> None:
    codec = SignedCorrelationCodec(secret=b"application-secret", cookie_name="federation_attempt")

    with pytest.raises(FederationError) as exc_info:
        codec.verify(value, now_epoch=1_786_748_000)

    assert exc_info.value.code == "FEDERATION_CORRELATION_INVALID"


def test_signed_correlation_does_not_include_cookie_name_in_signature() -> None:
    original = SignedCorrelationCodec(secret=b"application-secret", cookie_name="federation_attempt")
    renamed = SignedCorrelationCodec(secret=b"application-secret", cookie_name="other_cookie")
    value = original.sign("attempt-1", expires_at=1_786_748_600)

    assert renamed.verify(value, now_epoch=1_786_748_000) == "attempt-1"
