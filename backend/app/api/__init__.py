"""
API 路由聚合

- /api/v1/... 版本化接口（包括 auth, workspaces, graphs, users, environment 等）
"""

from fastapi import APIRouter

from .v1 import api_router as api_v1_router

api_router = APIRouter()
api_router.include_router(api_v1_router)

__all__ = ["api_router"]
