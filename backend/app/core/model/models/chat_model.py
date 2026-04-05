"""Chat model wrapper."""

from langchain_core.language_models import BaseChatModel

from .base import BaseModelWrapper


class ChatModelWrapper(BaseModelWrapper[BaseChatModel]):
    """Chat model wrapper.

    Fully compatible with the LangChain BaseChatModel interface,
    providing unified model management.

    Attributes:
        provider_name: provider identifier
        model_name: model identifier
    """

    def __init__(self, model: BaseChatModel, provider_name: str, model_name: str):
        """Initialize the chat model wrapper.

        Args:
            model: LangChain BaseChatModel instance
            provider_name: provider identifier
            model_name: model identifier

        Raises:
            TypeError: if model is not a BaseChatModel instance
        """
        self._validate_model_type(model, BaseChatModel, "BaseChatModel")
        super().__init__(model, provider_name, model_name)

    @property
    def chat_model(self) -> BaseChatModel:
        """Return the chat model instance.

        Returns:
            LangChain BaseChatModel instance.
        """
        return self.model
