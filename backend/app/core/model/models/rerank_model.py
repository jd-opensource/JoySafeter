"""Rerank 模型包装器与接口"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from langchain_core.runnables.config import run_in_executor

from .base import BaseModelWrapper


class Rerank(ABC):
    """Rerank 模型抽象接口

    定义了Rerank模型应该实现的核心方法，包括同步和异步接口。
    """

    @abstractmethod
    def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: Optional[int] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """同步 Rerank

        Args:
            query: 查询字符串
            documents: 文档列表
            top_k: 返回前k个结果，如果为None则返回所有结果
            **kwargs: 其他参数

        Returns:
            重排序后的文档列表，每个文档包含排序信息和元数据
        """
        ...

    async def arerank(
        self,
        query: str,
        documents: List[str],
        top_k: Optional[int] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """异步 Rerank，默认在线程池中调用同步方法

        Args:
            query: 查询字符串
            documents: 文档列表
            top_k: 返回前k个结果，如果为None则返回所有结果
            **kwargs: 其他参数

        Returns:
            重排序后的文档列表，每个文档包含排序信息和元数据
        """
        return await run_in_executor(None, self.rerank, query, documents, top_k, **kwargs)


class RerankModelWrapper(BaseModelWrapper[Rerank]):
    """Rerank 模型包装器

    包装Rerank模型实例，提供统一的模型管理功能。

    Attributes:
        provider_name: 供应商名称
        model_name: 模型名称
    """

    def __init__(self, model: Rerank, provider_name: str, model_name: str):
        """初始化Rerank模型包装器

        Args:
            model: Rerank模型实例
            provider_name: 供应商名称
            model_name: 模型名称

        Raises:
            TypeError: 如果model不是Rerank的实例
        """
        self._validate_model_type(model, Rerank, "Rerank")
        super().__init__(model, provider_name, model_name)

    @property
    def rerank_model(self) -> Rerank:
        """获取 Rerank 模型实例

        Returns:
            Rerank模型实例
        """
        return self.model
