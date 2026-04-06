"""Base model wrapper."""

from typing import Any, Generic, Type, TypeVar, Union

T = TypeVar("T")


class BaseModelWrapper(Generic[T]):
    """Base class for model wrappers.

    Provide unified model instance management for any model type.
    Proxy all attribute access to the inner model via __getattr__
    to ensure full compatibility.

    Attributes:
        provider_name: provider identifier
        model_name: model identifier
    """

    def __init__(self, model: T, provider_name: str, model_name: str):
        """Initialize the model wrapper.

        Args:
            model: model instance (any type)
            provider_name: provider identifier
            model_name: model identifier
        """
        self._model: T = model
        self.provider_name = provider_name
        self.model_name = model_name

    @staticmethod
    def _validate_model_type(
        model: Any,
        expected_type: Union[Type[Any], tuple[Type[Any], ...]],
        type_name: str,
    ) -> None:
        """Validate the model type.

        Args:
            model: model instance to validate
            expected_type: expected type or tuple of types
            type_name: type name for error messages

        Raises:
            TypeError: if model is not an instance of expected_type
        """
        if not isinstance(model, expected_type):
            raise TypeError(f"model must be an instance of {type_name}, got: {type(model)}")

    @property
    def model(self) -> T:
        """Return the inner model instance.

        Returns:
            The inner model instance.
        """
        return self._model

    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to the inner model.

        Args:
            name: attribute or method name

        Returns:
            The attribute or method from the inner model.
        """
        return getattr(self._model, name)

    def __repr__(self) -> str:
        """Return a string representation of this wrapper.

        Returns:
            String representation.
        """
        return f"{self.__class__.__name__}(provider_name={self.provider_name!r}, model_name={self.model_name!r})"
