import base64
import hashlib
import hmac
import re
import time

from ..domain.errors import FederationError

_KEY_CONTEXT = b"joysafeter:identity-federation:correlation:v1"
_BASE64URL_PART = re.compile(r"[A-Za-z0-9_-]+")


class SignedCorrelationCodec:
    def __init__(self, secret: bytes, cookie_name: str) -> None:
        self.cookie_name = cookie_name
        self._key = hmac.new(secret, _KEY_CONTEXT, hashlib.sha256).digest()

    def sign(self, attempt_id: str, expires_at: int) -> str:
        encoded_attempt_id = self._encode(attempt_id.encode())
        encoded_expiry = self._encode(str(expires_at).encode())
        signed_value = f"{encoded_attempt_id}.{encoded_expiry}".encode()
        signature = hmac.new(self._key, signed_value, hashlib.sha256).digest()
        return f"{signed_value.decode()}.{self._encode(signature)}"

    def verify(self, value: str, now_epoch: int | None = None) -> str:
        try:
            encoded_attempt_id, encoded_expiry, encoded_signature = self._parts(value)
            signed_value = f"{encoded_attempt_id}.{encoded_expiry}".encode()
            signature = self._decode(encoded_signature)
            expected_signature = hmac.new(self._key, signed_value, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected_signature):
                raise ValueError("Federation correlation signature is invalid")

            attempt_id = self._decode(encoded_attempt_id).decode()
            expiry_text = self._decode(encoded_expiry).decode()
            if not attempt_id or not expiry_text.isdecimal():
                raise ValueError("Federation correlation payload is invalid")
            expires_at = int(expiry_text)
            if str(expires_at) != expiry_text:
                raise ValueError("Federation correlation expiry is invalid")
            if expires_at <= (int(time.time()) if now_epoch is None else now_epoch):
                raise ValueError("Federation correlation has expired")
            return attempt_id
        except (UnicodeDecodeError, ValueError, TypeError):
            raise FederationError(
                "FEDERATION_CORRELATION_INVALID",
                "Federation login correlation is invalid",
            ) from None

    @staticmethod
    def _parts(value: str) -> tuple[str, str, str]:
        if not isinstance(value, str):
            raise ValueError("Federation correlation is invalid")
        parts = value.split(".")
        if len(parts) != 3 or any(_BASE64URL_PART.fullmatch(part) is None for part in parts):
            raise ValueError("Federation correlation is invalid")
        return parts[0], parts[1], parts[2]

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    @staticmethod
    def _decode(value: str) -> bytes:
        if _BASE64URL_PART.fullmatch(value) is None:
            raise ValueError("Federation correlation encoding is invalid")
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
