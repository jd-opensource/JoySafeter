"""模型基类包装器"""

from typing import Any, Generic, Type, TypeVar, Union

T = TypeVar("T")


class BaseModelWrapper(Generic[T]):
    """模型包装器基类

    这个类主要用于统一管理模型实例，支持任何类型的模型实例，
    通过 __getattr__ 代理所有方法调用到内部模型，以确保完全兼容。

    Attributes:
        provider_name: 供应商名称
        model_name: 模型名称
    """

    def __init__(self, model: T, provider_name: str, model_name: str):
        """初始化模型包装器

        Args:
            model: 模型实例（可以是任何类型）
            provider_name: 供应商名称
            model_name: 模型名称
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
        """验证模型类型

        Args:
            model: 要验证的模型实例
            expected_type: 期望的类型或类型元组
            type_name: 类型名称（用于错误消息）

        Raises:
            TypeError: 如果model不是期望类型的实例
        """
        if not isinstance(model, expected_type):
            raise TypeError(f"model必须是{type_name}的实例，但得到: {type(model)}")

    @property
    def model(self) -> T:
        """获取模型实例

        Returns:
            内部模型实例
        """
        return self._model

    def __getattr__(self, name: str) -> Any:
        """代理所有方法调用到内部模型

        Args:
            name: 属性或方法名

        Returns:
            内部模型的属性或方法
        """
        return getattr(self._model, name)

    def __repr__(self) -> str:
        """返回对象的字符串表示

        Returns:
            对象的字符串表示
        """
        return f"{self.__class__.__name__}(provider_name={self.provider_name!r}, model_name={self.model_name!r})"
