"""
模型管理API
"""

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.response import success_response
from app.core.database import get_db
from app.core.model import ModelType
from app.models.auth import AuthUser as User
from app.services.model_service import ModelService

router = APIRouter(prefix="/v1/models", tags=["Models"])


class ModelInstanceCreate(BaseModel):
    """创建模型实例配置请求"""

    provider_name: str = Field(description="供应商名称", examples=["openaiapicompatible"])
    model_name: str = Field(description="模型名称", examples=["DeepSeek-V3.2"])
    model_type: str = Field(default="chat", description="模型类型：chat, llm, embedding等", examples=["chat"])
    model_parameters: Optional[Dict[str, Any]] = Field(default=None, description="模型参数配置", examples=[{}])
    workspace_id: Optional[uuid.UUID] = Field(
        default=None,
        alias="workspaceId",
        description="工作空间ID（可选）",
        examples=["38e895c7-eb7a-4c7c-be2a-4a1e1ec4e3dc"],
    )
    is_default: bool = Field(default=True, description="是否为默认模型")


class ModelTestRequest(BaseModel):
    """测试模型输出请求"""

    model_name: str = Field(description="模型名称", examples=["DeepSeek-V3.2"])
    input: str = Field(description="输入文本", examples=["你好，请介绍一下你自己"])
    workspace_id: Optional[uuid.UUID] = Field(
        default=None,
        alias="workspaceId",
        description="工作空间ID（可选）",
        examples=["38e895c7-eb7a-4c7c-be2a-4a1e1ec4e3dc"],
    )


@router.get("")
async def list_available_models(
    model_type: str = Query(default="chat", description="模型类型：chat, llm, embedding等"),
    workspace_id: Optional[uuid.UUID] = Query(default=None, alias="workspaceId"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取可用模型列表

    Args:
        model_type: 模型类型
        workspace_id: 工作空间ID（可选）

    Returns:
        可用模型列表
    """
    try:
        model_type_enum = ModelType(model_type)
    except ValueError:
        from app.common.exceptions import BadRequestException

        raise BadRequestException(f"不支持的模型类型: {model_type}")

    service = ModelService(db)
    user_id = current_user.id
    models = await service.get_available_models(
        model_type=model_type_enum,
        user_id=user_id,
        workspace_id=workspace_id,
    )
    return success_response(data=models, message="获取模型列表成功")


@router.post("/instances")
async def create_model_instance(
    payload: ModelInstanceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    创建模型实例配置

    Args:
        payload: 模型实例创建请求

    Returns:
        创建的模型实例配置
    """
    try:
        model_type_enum = ModelType(payload.model_type)
    except ValueError:
        from app.common.exceptions import BadRequestException

        raise BadRequestException(f"不支持的模型类型: {payload.model_type}")

    service = ModelService(db)
    user_id = current_user.id
    instance = await service.create_model_instance_config(
        user_id=user_id,
        provider_name=payload.provider_name,
        model_name=payload.model_name,
        model_type=model_type_enum,
        model_parameters=payload.model_parameters,
        workspace_id=payload.workspace_id,
        is_default=payload.is_default,
    )
    return success_response(data=instance, message="创建模型实例配置成功")


@router.get("/instances")
async def list_model_instances(
    workspace_id: Optional[uuid.UUID] = Query(default=None, alias="workspaceId"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取用户的所有模型实例配置

    Args:
        workspace_id: 工作空间ID（可选）

    Returns:
        模型实例配置列表
    """
    service = ModelService(db)
    user_id = current_user.id
    instances = await service.list_model_instances(
        user_id=user_id,
        workspace_id=workspace_id,
    )
    return success_response(data=instances, message="获取模型实例配置列表成功")


@router.post("/test-output")
async def test_output(
    payload: ModelTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    测试模型输出

    Args:
        payload: 测试请求，包含模型名称和输入文本

    Returns:
        模型输出结果
    """
    service = ModelService(db)
    user_id = current_user.id
    output = await service.test_output(
        user_id=user_id,
        model_name=payload.model_name,
        input_text=payload.input,
        workspace_id=payload.workspace_id,
    )
    return success_response(data={"output": output}, message="测试模型输出成功")


class ModelInstanceUpdateDefaultRequest(BaseModel):
    """更新模型实例默认状态请求"""

    provider_name: str = Field(description="供应商名称", examples=["openaiapicompatible"])
    model_name: str = Field(description="模型名称", examples=["DeepSeek-V3.2"])
    is_default: bool = Field(..., description="是否为默认模型")


@router.patch("/instances/default")
async def update_model_instance_default(
    payload: ModelInstanceUpdateDefaultRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    更新模型实例的默认状态

    Args:
        payload: 更新请求，包含供应商名称、模型名称和是否默认

    Returns:
        更新后的模型实例配置
    """
    service = ModelService(db)
    instance = await service.update_model_instance_default(
        provider_name=payload.provider_name,
        model_name=payload.model_name,
        is_default=payload.is_default,
        user_id=current_user.id,
    )
    return success_response(data=instance, message="更新模型默认状态成功")
