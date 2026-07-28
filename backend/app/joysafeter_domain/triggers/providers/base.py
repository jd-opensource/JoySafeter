"""Trigger-type provider registry.

Each trigger *type* (cron / webhook / manual, and future event/queue types)
implements one ``TriggerProvider`` and registers it here. This is the single
dispatch seam the control plane uses instead of ``if type == "cron" ...``
string branches scattered across the service, scheduler and API. Adding a new
type is: drop a new module implementing the protocol and import it in
``__init__``. Nothing else needs to know the concrete types.

A provider owns three pure operations:
  - ``build_config``      the persisted JSONB ``config`` snapshot for the type.
  - ``idempotency_key``   the exactly-once key for one fire occurrence.
  - ``build_payload``     the payload dict fed to the prompt template.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.joysafeter_shared.common.app_errors import RequestValidationAppError


@runtime_checkable
class TriggerProvider(Protocol):
    kind: str

    def build_config(self, **fields: Any) -> dict[str, Any]:
        """Return the persisted ``config`` JSONB snapshot for this type."""
        ...

    def idempotency_key(self, trigger: Any, **context: Any) -> str:
        """Return the exactly-once key identifying one fire occurrence."""
        ...

    def build_payload(self, trigger: Any, **context: Any) -> dict[str, Any]:
        """Return the payload dict rendered into the prompt template."""
        ...


_REGISTRY: dict[str, TriggerProvider] = {}


def register(provider: TriggerProvider) -> None:
    _REGISTRY[provider.kind] = provider


def get_provider(kind: str) -> TriggerProvider:
    provider = _REGISTRY.get(kind)
    if provider is None:
        raise RequestValidationAppError(
            code="TRIGGER_TYPE_UNSUPPORTED",
            message=f"Unsupported trigger type: {kind}",
            data={"type": kind, "supported": sorted(_REGISTRY)},
            user_action="fix_input",
        )
    return provider


def supported_kinds() -> list[str]:
    return sorted(_REGISTRY)
