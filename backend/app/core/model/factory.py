"""
模型工厂层
"""

from typing import Any, Dict, List, Optional

from langchain_core.language_models.base import BaseLanguageModel

# 向后兼容导入（保留以避免破坏现有代码）
from .providers import (
    BaseProvider,
    ModelType,
    get_all_provider_instances,
)


class ModelFactory:
    """模型工厂类

    管理所有供应商，提供统一的模型创建接口
    """

    def __init__(self):
        """初始化工厂"""
        self._providers: Dict[str, BaseProvider] = {}
        self._register_default_providers()

    def _register_default_providers(self):
        """注册默认供应商（自动发现并注册所有 Provider）"""
        # 自动发现并注册所有 Provider 类
        provider_instances = get_all_provider_instances()
        for provider in provider_instances:
            self.register_provider(provider)

    def register_provider(self, provider: BaseProvider):
        """
        注册供应商

        Args:
            provider: 供应商实例
        """
        self._providers[provider.provider_name] = provider

    def get_provider(self, provider_name: str) -> Optional[BaseProvider]:
        """
        获取供应商实例

        Args:
            provider_name: 供应商名称

        Returns:
            供应商实例，如果不存在则返回None
        """
        return self._providers.get(provider_name)

    def get_all_providers(self) -> List[Dict[str, Any]]:
        """
        获取所有供应商信息

        Returns:
            供应商信息列表，每个包含：
            - provider_name: 供应商名称
            - display_name: 显示名称
            - supported_model_types: 支持的模型类型列表
            - credential_schema: 凭据表单规则
            - config_schema: 配置规则（按模型类型）
        """
        providers = []
        for provider_name, provider in self._providers.items():
            model_count = 0
            for model_type in provider.get_supported_model_types():
                models = provider.get_model_list(model_type, None)
                model_count += len(models)

            provider_info = {
                "provider_name": provider_name,
                "display_name": provider.display_name,
                "supported_model_types": [mt.value for mt in provider.get_supported_model_types()],
                "credential_schema": provider.get_credential_schema(),
                "model_count": model_count,
            }

            # 为每种模型类型添加配置规则
            config_schemas = {}
            for model_type in provider.get_supported_model_types():
                config_schema = provider.get_config_schema(model_type)
                if config_schema:
                    config_schemas[model_type.value] = config_schema

            if config_schemas:
                provider_info["config_schemas"] = config_schemas

            providers.append(provider_info)

        return providers

    def get_all_models(
        self,
        model_type: ModelType,
        credentials: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取所有可用模型列表

        Args:
            model_type: 模型类型
            credentials: 可选的凭据字典，格式为 {provider_name: credentials}

        Returns:
            模型列表，每个包含：
            - provider_name: 供应商名称
            - display_name: 供应商显示名称
            - name: 模型名称
            - display_name: 显示名称
            - description: 描述
            - is_available: 是否可用
        """
        all_models = []

        for provider_name, provider in self._providers.items():
            if model_type not in provider.get_supported_model_types():
                continue

            # 获取该供应商的凭据（如果有）
            provider_credentials = credentials.get(provider_name) if credentials else None

            # 获取模型列表
            models = provider.get_model_list(model_type, provider_credentials)

            for model in models:
                model_info = {
                    "provider_name": provider_name,
                    "provider_display_name": provider.display_name,
                    "name": model["name"],
                    "display_name": model.get("display_name", model["name"]),
                    "description": model.get("description", ""),
                    "is_available": model.get("is_available", True),
                }
                all_models.append(model_info)

        return all_models

    async def validate_provider_credentials(
        self,
        provider_name: str,
        credentials: Dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        """
        验证供应商凭据

        Args:
            provider_name: 供应商名称
            credentials: 凭据字典

        Returns:
            (是否有效, 错误信息)
        """
        provider = self.get_provider(provider_name)
        if not provider:
            return False, f"供应商不存在: {provider_name}"

        return await provider.validate_credentials(credentials)

    async def validate_model_credentials(
        self,
        provider_name: str,
        model_name: str,
        model_type: ModelType,
        credentials: Dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        """
        验证模型凭据（通过尝试创建模型实例）

        Args:
            provider_name: 供应商名称
            model_name: 模型名称
            model_type: 模型类型
            credentials: 凭据字典

        Returns:
            (是否有效, 错误信息)
        """
        provider = self.get_provider(provider_name)
        if not provider:
            return False, f"供应商不存在: {provider_name}"

        try:
            # 先验证凭据
            is_valid, error = await provider.validate_credentials(credentials)
            if not is_valid:
                return False, error

            # 尝试创建模型实例
            model = provider.create_model_instance(model_name, model_type, credentials)
            if model:
                return True, None
            else:
                return False, "无法创建模型实例"
        except Exception as e:
            return False, f"验证失败: {str(e)}"

    def create_model_instance(
        self,
        provider_name: str,
        model_name: str,
        model_type: ModelType,
        credentials: Dict[str, Any],
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> BaseLanguageModel:
        """
        创建模型实例

        Args:
            provider_name: 供应商名称
            model_name: 模型名称
            model_type: 模型类型
            credentials: 凭据字典
            model_parameters: 模型参数

        Returns:
            LangChain模型实例
        """
        provider = self.get_provider(provider_name)
        if not provider:
            raise ValueError(f"供应商不存在: {provider_name}")

        model = provider.create_model_instance(model_name, model_type, credentials, model_parameters)
        return model


# 全局工厂实例
_factory = ModelFactory()


def get_factory() -> ModelFactory:
    """获取全局工厂实例"""
    return _factory


def get_all_providers() -> List[Dict[str, Any]]:
    """获取所有供应商信息"""
    return _factory.get_all_providers()


def get_all_models(
    model_type: ModelType,
    credentials: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """获取所有可用模型列表"""
    return _factory.get_all_models(model_type, credentials)


def get_provider(provider_name: str) -> Optional[BaseProvider]:
    """获取供应商实例"""
    return _factory.get_provider(provider_name)


async def validate_provider_credentials(
    provider_name: str,
    credentials: Dict[str, Any],
) -> tuple[bool, Optional[str]]:
    """验证供应商凭据"""
    return await _factory.validate_provider_credentials(provider_name, credentials)


async def validate_model_credentials(
    provider_name: str,
    model_name: str,
    model_type: ModelType,
    credentials: Dict[str, Any],
) -> tuple[bool, Optional[str]]:
    """验证模型凭据"""
    return await _factory.validate_model_credentials(provider_name, model_name, model_type, credentials)


def create_model_instance(
    provider_name: str,
    model_name: str,
    model_type: ModelType,
    credentials: Dict[str, Any],
    model_parameters: Optional[Dict[str, Any]] = None,
) -> BaseLanguageModel:
    """创建模型实例"""
    return _factory.create_model_instance(provider_name, model_name, model_type, credentials, model_parameters)
