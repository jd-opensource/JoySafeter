# backend/app/core/observation/instrumentation/copilot_extractor.py
"""Copilot stream → observation extractor."""
from __future__ import annotations

from app.core.observation.collector import ObservationCollector


class CopilotObservationExtractor:
    def __init__(self, collector: ObservationCollector, model_name: str):
        self._collector = collector
        self._model_name = model_name
        self._chunks: list[str] = []

    def accumulate(self, content: str) -> None:
        self._chunks.append(content)

    async def flush(
        self,
        *,
        prompt: str,
        mode: str,
        elapsed_ms: float,
        usage_details: dict | None = None,
    ) -> None:
        await self._collector.record_generation(
            f"copilot:{self._model_name}",
            input={"prompt": prompt, "mode": mode},
            output={"completion": "".join(self._chunks)},
            model=self._model_name,
            usage_details=usage_details,
            cost_details=None,
            latency_ms=elapsed_ms,
        )
