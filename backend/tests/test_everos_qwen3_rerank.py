from __future__ import annotations

import httpx
import pytest

from app.everos.component.rerank.factory import build_rerank_provider
from app.everos.config import RerankSettings

pytestmark = pytest.mark.no_db


class _FakeResponse:
    status_code = 200

    def json(self):
        return {
            "results": [
                {"index": 1, "relevance_score": 0.91},
                {"index": 0, "relevance_score": 0.42},
            ]
        }


class _FakeAsyncClient:
    requests: list[dict] = []

    def __init__(self, *, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, *, json, headers):
        self.requests.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse()


async def test_qwen3_rerank_provider_uses_dashscope_compatible_reranks_endpoint(
    monkeypatch,
):
    from app.everos.component.rerank.dashscope_compatible_provider import (
        DashScopeCompatibleRerankProvider,
    )

    _FakeAsyncClient.requests = []
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    provider = DashScopeCompatibleRerankProvider(
        model="qwen3-rerank",
        api_key="dashscope-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    results = await provider.rerank(
        "修复模型调用失败",
        ["候选 A", "候选 B"],
        instruction="判断候选记忆是否能帮助解决问题",
    )

    assert [(item.index, item.score) for item in results] == [(1, 0.91), (0, 0.42)]
    assert _FakeAsyncClient.requests == [
        {
            "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/reranks",
            "json": {
                "model": "qwen3-rerank",
                "query": "修复模型调用失败",
                "documents": ["候选 A", "候选 B"],
                "top_n": 2,
                "instruct": "判断候选记忆是否能帮助解决问题",
            },
            "headers": {
                "Authorization": "Bearer dashscope-key",
                "Content-Type": "application/json",
            },
        }
    ]


def test_rerank_factory_builds_qwen3_dashscope_compatible_provider():
    provider = build_rerank_provider(
        RerankSettings(
            provider="dashscope_compatible",
            model="qwen3-rerank",
            api_key="dashscope-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
    )

    assert provider.__class__.__name__ == "DashScopeCompatibleRerankProvider"
