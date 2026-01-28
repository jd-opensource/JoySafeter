"""
Graph 部署版本 Schema
"""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class GraphDeploymentVersionResponse(BaseModel):
    """Graph 部署版本响应"""

    id: uuid.UUID
    version: int
    name: Optional[str] = None
    is_active: bool
    created_at: datetime
    created_by: Optional[str] = None

    class Config:
        from_attributes = True


class GraphDeploymentVersionResponseCamel(BaseModel):
    """Graph 部署版本响应 - 使用 camelCase 字段名"""

    id: str
    version: int
    name: Optional[str] = None
    isActive: bool
    createdAt: str
    createdBy: Optional[str] = None
    createdByName: Optional[str] = None  # 创建者用户名

    class Config:
        from_attributes = True


class GraphDeploymentVersionStateResponse(BaseModel):
    """Graph 部署版本状态响应 - 包含完整的 nodes, edges 等"""

    id: str
    version: int
    name: Optional[str] = None
    isActive: bool
    createdAt: str
    createdBy: Optional[str] = None
    # 完整的图状态，前端可以用来预览
    state: dict = Field(default_factory=dict, description="版本的完整状态 (nodes, edges, variables)")

    class Config:
        from_attributes = True


class GraphDeploymentVersionListResponse(BaseModel):
    """Graph 部署版本列表响应（分页）"""

    versions: List[GraphDeploymentVersionResponseCamel]
    total: int
    page: int = Field(default=1, description="当前页码")
    pageSize: int = Field(default=10, description="每页数量")
    totalPages: int = Field(default=1, description="总页数")


class GraphDeployRequest(BaseModel):
    """部署 Graph 请求"""

    name: Optional[str] = Field(None, description="版本名称（可选）")


class GraphDeployResponse(BaseModel):
    """部署 Graph 响应"""

    success: bool
    message: str
    version: int
    isActive: bool
    needsRedeployment: bool = Field(default=False, description="是否需要重新部署")


class GraphRevertResponse(BaseModel):
    """回滚版本响应"""

    success: bool
    message: str
    version: int
    is_active: bool


class GraphRenameVersionRequest(BaseModel):
    """重命名版本请求"""

    name: str = Field(..., min_length=1, max_length=255, description="新的版本名称")
