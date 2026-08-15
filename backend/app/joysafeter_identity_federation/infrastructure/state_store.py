import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..domain.errors import FederationError
from ..domain.models import CorrelationMethod, LoginAttempt, ProviderId

_ATTEMPT_TTL_SECONDS = 600
_CONSUME_ATTEMPT_LUA = """
local value = redis.call('GET', KEYS[1])
if value then
  redis.call('DEL', KEYS[1])
end
return value
"""
_ATTEMPT_FIELDS = frozenset(
    {
        "id",
        "provider_id",
        "callback_url",
        "redirect_uri",
        "correlation_method",
        "retry_count",
        "created_at",
        "expires_at",
    }
)


class RedisLoginAttemptStore:
    def __init__(self, redis_factory: Callable[[], Any | None]) -> None:
        self._redis_factory = redis_factory

    async def create(self, attempt: LoginAttempt) -> None:
        redis = self._redis()
        try:
            created = await redis.set(
                self._key(attempt.id),
                self._serialize(attempt),
                nx=True,
                ex=_ATTEMPT_TTL_SECONDS,
            )
        except Exception as error:
            raise self._unavailable() from error

        if not created:
            raise FederationError(
                "FEDERATION_ATTEMPT_COLLISION",
                "Federation login attempt could not be created",
            )

    async def consume(self, attempt_id: str) -> LoginAttempt | None:
        redis = self._redis()
        try:
            value = await redis.eval(_CONSUME_ATTEMPT_LUA, 1, self._key(attempt_id))
        except Exception as error:
            raise self._unavailable() from error

        if value is None:
            return None
        return self._deserialize(value)

    async def replace_for_retry(self, consumed: LoginAttempt, replacement: LoginAttempt) -> None:
        await self.create(replacement)

    def _redis(self) -> Any:
        try:
            redis = self._redis_factory()
        except Exception as error:
            raise self._unavailable() from error
        if redis is None:
            raise self._unavailable()
        return redis

    @staticmethod
    def _key(attempt_id: str) -> str:
        return f"identity_federation:attempt:{attempt_id}"

    @staticmethod
    def _serialize(attempt: LoginAttempt) -> str:
        return json.dumps(
            {
                "id": attempt.id,
                "provider_id": str(attempt.provider_id),
                "callback_url": attempt.callback_url,
                "redirect_uri": attempt.redirect_uri,
                "correlation_method": attempt.correlation_method.value,
                "retry_count": attempt.retry_count,
                "created_at": attempt.created_at.isoformat(),
                "expires_at": attempt.expires_at.isoformat(),
            },
            separators=(",", ":"),
        )

    @classmethod
    def _deserialize(cls, value: str | bytes) -> LoginAttempt:
        try:
            decoded = value.decode() if isinstance(value, bytes) else value
            payload = json.loads(decoded)
            if not isinstance(payload, dict) or set(payload) != _ATTEMPT_FIELDS:
                raise ValueError("Invalid federation login attempt payload")

            created_at = datetime.fromisoformat(cls._string(payload, "created_at"))
            expires_at = datetime.fromisoformat(cls._string(payload, "expires_at"))
            if created_at.tzinfo is None or expires_at.tzinfo is None:
                raise ValueError("Federation login attempt timestamps must have timezones")

            retry_count = payload["retry_count"]
            if not isinstance(retry_count, int) or isinstance(retry_count, bool):
                raise ValueError("Federation login attempt retry count is invalid")

            return LoginAttempt(
                id=cls._string(payload, "id"),
                provider_id=ProviderId(cls._string(payload, "provider_id")),
                callback_url=cls._string(payload, "callback_url"),
                redirect_uri=cls._string(payload, "redirect_uri"),
                correlation_method=CorrelationMethod(cls._string(payload, "correlation_method")),
                retry_count=retry_count,
                created_at=created_at,
                expires_at=expires_at,
            )
        except (TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise FederationError(
                "FEDERATION_ATTEMPT_INVALID",
                "Federation login attempt is invalid",
            ) from error

    @staticmethod
    def _string(payload: dict[str, object], name: str) -> str:
        value = payload[name]
        if not isinstance(value, str):
            raise ValueError(f"Federation login attempt {name} is invalid")
        return value

    @staticmethod
    def _unavailable() -> FederationError:
        return FederationError(
            "FEDERATION_STATE_STORE_UNAVAILABLE",
            "Federation login state is unavailable",
            retryable=True,
        )
