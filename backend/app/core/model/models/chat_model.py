"""Chat模型包装器"""

from langchain_core.language_models import BaseChatModel

from .base import BaseModelWrapper


class ChatModelWrapper(BaseModelWrapper[BaseChatModel]):
    """Chat模型包装器

    完全兼容LangChain的BaseChatModel接口，提供统一的模型管理功能。

    Attributes:
        provider_name: 供应商名称
        model_name: 模型名称
    """

    def __init__(self, model: BaseChatModel, provider_name: str, model_name: str):
        """初始化Chat模型包装器

        Args:
            model: LangChain Chat模型实例
            provider_name: 供应商名称
            model_name: 模型名称

        Raises:
            TypeError: 如果model不是BaseChatModel的实例
        """
        self._validate_model_type(model, BaseChatModel, "BaseChatModel")
        super().__init__(model, provider_name, model_name)

    @property
    def chat_model(self) -> BaseChatModel:
        """获取Chat模型实例

        Returns:
            LangChain Chat模型实例
        """
        return self.model
