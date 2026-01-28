"""Embedding 模型包装器"""

from langchain_core.embeddings import Embeddings

from .base import BaseModelWrapper


class EmbeddingModelWrapper(BaseModelWrapper[Embeddings]):
    """Embedding 模型包装器

    基于 LangChain Embeddings 接口，保持完全兼容，提供统一的模型管理功能。

    Attributes:
        provider_name: 供应商名称
        model_name: 模型名称
    """

    def __init__(self, model: Embeddings, provider_name: str, model_name: str):
        """初始化Embedding模型包装器

        Args:
            model: LangChain Embeddings模型实例
            provider_name: 供应商名称
            model_name: 模型名称

        Raises:
            TypeError: 如果model不是Embeddings的实例
        """
        self._validate_model_type(model, Embeddings, "Embeddings")
        super().__init__(model, provider_name, model_name)

    @property
    def embedding_model(self) -> Embeddings:
        """获取 Embeddings 模型实例

        Returns:
            LangChain Embeddings模型实例
        """
        return self.model
