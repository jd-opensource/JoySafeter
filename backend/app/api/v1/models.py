"""
模型管理API（全局，与 workspace 无关）
"""

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
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
    is_default: bool = Field(default=True, description="是否为默认模型")


class ModelInstanceUpdate(BaseModel):
    """更新模型实例请求"""

    model_parameters: Optional[Dict[str, Any]] = Field(
        default=None, description="模型参数覆盖值（仅包含用户显式设置的字段）"
    )
    is_default: Optional[bool] = Field(default=None, description="是否为默认模型")


class ModelInstanceUpdateDefaultRequest(BaseModel):
    """更新模型实例默认状态请求"""

    provider_name: str = Field(description="供应商名称", examples=["openaiapicompatible"])
    model_name: str = Field(description="模型名称", examples=["DeepSeek-V3.2"])
    is_default: bool = Field(..., description="是否为默认模型")


class ModelTestRequest(BaseModel):
    """测试模型输出请求"""

    model_name: str = Field(description="模型名称", examples=["DeepSeek-V3.2"])
    input: str = Field(description="输入文本", examples=["你好，请介绍一下你自己"])


@router.get("/overview")
async def get_models_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取全局模型概览：Provider 健康摘要、默认模型、最近凭证失败"""
    service = ModelService(db)
    overview = await service.get_overview()
    return success_response(data=overview, message="获取模型概览成功")


@router.get("")
async def list_available_models(
    model_type: str = Query(default="chat", description="模型类型：chat, llm, embedding等"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取可用模型列表（含 unavailable_reason）"""
    try:
        model_type_enum = ModelType(model_type)
    except ValueError:
        from app.common.exceptions import BadRequestException

        raise BadRequestException(f"不支持的模型类型: {model_type}")

    service = ModelService(db)
    models = await service.get_available_models(model_type=model_type_enum, user_id=current_user.id)
    return success_response(data=models, message="获取模型列表成功")


@router.post("/instances")
async def create_model_instance(
    payload: ModelInstanceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建模型实例配置"""
    try:
        model_type_enum = ModelType(payload.model_type)
    except ValueError:
        from app.common.exceptions import BadRequestException

        raise BadRequestException(f"不支持的模型类型: {payload.model_type}")

    service = ModelService(db)
    instance = await service.create_model_instance_config(
        user_id=current_user.id,
        provider_name=payload.provider_name,
        model_name=payload.model_name,
        model_type=model_type_enum,
        model_parameters=payload.model_parameters,
        is_default=payload.is_default,
    )
    return success_response(data=instance, message="创建模型实例配置成功")


@router.get("/instances")
async def list_model_instances(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取模型实例配置列表（全局）"""
    service = ModelService(db)
    instances = await service.list_model_instances()
    return success_response(data=instances, message="获取模型实例配置列表成功")


@router.patch("/instances/default")
async def update_model_instance_default(
    payload: ModelInstanceUpdateDefaultRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新模型实例的默认状态（按 provider_name + model_name 查找）"""
    service = ModelService(db)
    instance = await service.update_model_instance_default(
        provider_name=payload.provider_name,
        model_name=payload.model_name,
        is_default=payload.is_default,
        user_id=current_user.id,
    )
    return success_response(data=instance, message="更新模型默认状态成功")


@router.patch("/instances/{instance_id}")
async def update_model_instance(
    instance_id: uuid.UUID,
    payload: ModelInstanceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新模型实例参数和/或默认状态"""
    service = ModelService(db)
    instance = await service.update_model_instance(
        instance_id=instance_id,
        model_parameters=payload.model_parameters,
        is_default=payload.is_default,
    )
    return success_response(data=instance, message="更新模型实例成功")


class ModelTestStreamRequest(BaseModel):
    """流式测试模型输出请求"""

    model_name: str = Field(description="模型名称")
    input: str = Field(description="输入文本")
    model_parameters: Optional[Dict[str, Any]] = Field(default=None, description="临时参数覆盖")


@router.post("/test-output-stream")
async def test_output_stream(
    payload: ModelTestStreamRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """流式测试模型输出（SSE）"""
    service = ModelService(db)

    async def event_generator():
        async for event in service.test_output_stream(
            user_id=current_user.id,
            model_name=payload.model_name,
            input_text=payload.input,
            model_parameters=payload.model_parameters,
        ):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/test-output")
async def test_output(
    payload: ModelTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """测试模型输出"""
    service = ModelService(db)
    output = await service.test_output(
        user_id=current_user.id,
        model_name=payload.model_name,
        input_text=payload.input,
    )
    return success_response(data={"output": output}, message="测试模型输出成功")
