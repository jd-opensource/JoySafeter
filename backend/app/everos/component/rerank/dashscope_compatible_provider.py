"""DashScope OpenAI-compatible rerank provider.

Aliyun Bailian exposes newer rerank models such as ``qwen3-rerank`` through
the compatible-mode endpoint::

    POST {base_url}/reranks

where ``base_url`` usually includes ``/compatible-mode/v1``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import httpx

from ._errors import retries_exhausted_error, transport_error, upstream_http_error
from .protocol import RerankResult, RerankServiceError


class DashScopeCompatibleRerankProvider:
    """Rerank provider for DashScope compatible-mode ``/reranks`` endpoints."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        batch_size: int = 10,
        max_concurrent: int = 5,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._url = f"{base_url.rstrip('/')}/reranks"
        self._timeout = timeout
        self._max_retries = max_retries
        self._batch_size = batch_size
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        instruction: str | None = None,
    ) -> list[RerankResult]:
        """Score every document against ``query``; return sorted desc."""
        if not documents:
            return []

        chunks: list[tuple[int, list[str]]] = [
            (offset, list(documents[offset : offset + self._batch_size]))
            for offset in range(0, len(documents), self._batch_size)
        ]
        chunk_results = await asyncio.gather(
            *(self._score_chunk(query, docs, instruction) for _, docs in chunks)
        )
        scored: list[RerankResult] = []
        for (offset, _), partial in zip(chunks, chunk_results, strict=True):
            scored.extend(
                RerankResult(index=offset + r.index, score=r.score) for r in partial
            )
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored

    async def _score_chunk(
        self, query: str, documents: list[str], instruction: str | None
    ) -> list[RerankResult]:
        payload: dict[str, Any] = {
            "model": self._model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
        }
        if instruction:
            payload["instruct"] = instruction

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with self._semaphore:
            for attempt in range(self._max_retries + 1):
                try:
                    async with httpx.AsyncClient(timeout=self._timeout) as client:
                        response = await client.post(
                            self._url, json=payload, headers=headers
                        )
                except httpx.HTTPError as exc:
                    if attempt == self._max_retries:
                        raise transport_error("DashScope compatible rerank", exc) from exc
                    continue

                if response.status_code == 200:
                    return _parse_rerank_results(response.json())

                if response.status_code >= 500 or response.status_code == 429:
                    if attempt == self._max_retries:
                        raise upstream_http_error(
                            "DashScope compatible rerank", response
                        )
                    continue
                raise upstream_http_error("DashScope compatible rerank", response)

            raise retries_exhausted_error(
                "DashScope compatible rerank", self._max_retries
            )


def _parse_rerank_results(body: dict[str, Any]) -> list[RerankResult]:
    items = body.get("results")
    if items is None and isinstance(body.get("output"), dict):
        items = body["output"].get("results")
    if not isinstance(items, list):
        raise RerankServiceError(
            f"DashScope compatible rerank response missing results: {body!r}"
        )

    parsed: list[RerankResult] = []
    for item in items:
        try:
            parsed.append(
                RerankResult(
                    index=int(item["index"]),
                    score=float(item["relevance_score"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RerankServiceError(
                f"malformed DashScope compatible rerank result entry: {item!r}"
            ) from exc
    parsed.sort(key=lambda r: r.score, reverse=True)
    return parsed
