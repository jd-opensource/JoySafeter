"""
供应商基类
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional

from langchain_core.language_models.base import BaseLanguageModel


class ModelType(str, Enum):
    """模型类型枚举"""

    CHAT = "chat"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    MODERATION = "moderation"


class BaseProvider(ABC):
    """供应商基类

    所有供应商都应该继承此类，实现以下方法：
    - validate_credentials: 验证凭据
    - get_model_list: 获取模型列表
    - create_model_instance: 创建模型实例
    """

    def __init__(self, provider_name: str, display_name: str):
        """
        初始化供应商

        Args:
            provider_name: 供应商唯一标识（如 'openai'）
            display_name: 显示名称（如 'OpenAI'）
        """
        self.provider_name = provider_name
        self.display_name = display_name

    @abstractmethod
    def get_supported_model_types(self) -> List[ModelType]:
        """
        获取支持的模型类型列表

        Returns:
            支持的模型类型列表
        """
        pass

    @abstractmethod
    def get_credential_schema(self) -> Dict[str, Any]:
        """
        获取凭据表单规则（JSON Schema格式）

        Returns:
            凭据表单规则字典
        """
        pass

    @abstractmethod
    def get_config_schema(self, model_type: ModelType) -> Optional[Dict[str, Any]]:
        """
        获取模型参数配置规则（JSON Schema格式）

        Args:
            model_type: 模型类型

        Returns:
            配置规则字典，如果该模型类型不支持配置则返回None
        """
        pass

    @abstractmethod
    async def validate_credentials(self, credentials: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        验证凭据

        Args:
            credentials: 凭据字典

        Returns:
            (是否有效, 错误信息)
        """
        pass

    @abstractmethod
    def get_model_list(
        self, model_type: ModelType, credentials: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        获取模型列表

        Args:
            model_type: 模型类型
            credentials: 可选的凭据，用于获取远程模型列表

        Returns:
            模型列表，每个模型包含：
            - name: 模型名称
            - display_name: 显示名称
            - description: 描述
            - is_available: 是否可用（需要凭据时）
        """
        pass

    @abstractmethod
    def create_model_instance(
        self,
        model_name: str,
        model_type: ModelType,
        credentials: Dict[str, Any],
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> BaseLanguageModel:
        """
        创建模型实例

        Args:
            model_name: 模型名称
            model_type: 模型类型
            credentials: 凭据字典
            model_parameters: 模型参数（如 temperature, max_tokens 等）

        Returns:
            LangChain模型实例（BaseChatModel, BaseLLM等）
        """
        pass

    def get_predefined_models(self, model_type: ModelType) -> List[Dict[str, Any]]:
        """
        获取预定义模型列表（不需要凭据）

        Args:
            model_type: 模型类型

        Returns:
            预定义模型列表
        """
        return []

    async def test_output(self, instance_dict: Dict[str, Any], input: str) -> str:
        """
        测试模型输出

        Args:
            instance_dict: 模型实例字典
            input: 输入

        Returns:
            测试输出字符串
        """
        return ""
