from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BeginLoginCommand:
    provider_id: str
    callback_url: str | None = None


@dataclass(frozen=True, slots=True)
class CompleteLoginCommand:
    provider_id: str
