"""
Zhipu 智谱大模型供应商实现
"""

from typing import Any, Dict, List, Optional

from langchain_core.language_models import BaseChatModel

from .base import BaseProvider, ModelType
from .OpenaiApiCompatible import OpenAIAPICompatibleProvider

class ZhipuProvider(OpenAIAPICompatibleProvider):
    """Zhipu 智谱大模型供应商"""

    PREDEFINED_CHAT_MODELS = [
        {
            "name": "glm-5",
            "display_name": "GLM-5",
            "description": "智谱新一代的旗舰基座模型，面向Agentic Engineering 打造，能够在复杂系统工程与长程Agent 任务中提供可靠生产力",
        },
        {
            "name": "glm-4-plus",
            "display_name": "GLM-4 Plus",
            "description": "智谱最新旗舰大模型",
        },
        {
            "name": "glm-4-0520",
            "display_name": "GLM-4",
            "description": "智谱综合大模型",
        },
        {
            "name": "glm-4-air",
            "display_name": "GLM-4 Air",
            "description": "性价比高的主力模型",
        },
        {
            "name": "glm-4-flash",
            "display_name": "GLM-4 Flash",
            "description": "速度极快、价格极低的轻量级模型",
        },
    ]

    def __init__(self):
        BaseProvider.__init__(self, provider_name="zhipu", display_name="Zhipu (GLM)")

    def get_credential_schema(self) -> Dict[str, Any]:
        """获取凭据表单规则"""
        schema = super().get_credential_schema()
        
        # 定制 Zhipu 的基础 URL
        base_url_prop = schema["properties"]["base_url"]
        base_url_prop["description"] = "Zhipu API 基础 URL (保留为空则使用默认值)"
        base_url_prop["default"] = "https://open.bigmodel.cn/api/paas/v4/"
        # 移除 strict required, 使得 default 可以生效或者可以在代码中配置
        if "required" in schema and "base_url" in schema["required"]:
            schema["required"].remove("base_url")

        return schema

    async def validate_credentials(self, credentials: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """验证凭据"""
        creds = credentials.copy()
        if not creds.get("base_url"):
            creds["base_url"] = "https://open.bigmodel.cn/api/paas/v4/"
            
        return await super().validate_credentials(creds)

    def create_model_instance(
        self,
        model_name: str,
        model_type: ModelType,
        credentials: Dict[str, Any],
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> BaseChatModel:
        """创建模型实例"""
        creds = credentials.copy()
        if not creds.get("base_url"):
            creds["base_url"] = "https://open.bigmodel.cn/api/paas/v4/"
            
        return super().create_model_instance(
            model_name=model_name,
            model_type=model_type,
            credentials=creds,
            model_parameters=model_parameters,
        )
