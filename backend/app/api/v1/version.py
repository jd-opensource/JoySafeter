"""版本信息 API"""

import os
import subprocess

from fastapi import APIRouter

from app.common.response import success_response
from app.core.settings import settings

router = APIRouter(prefix="/v1/version", tags=["Version"])

_git_sha: str | None = None


def _get_git_sha() -> str:
    global _git_sha
    if _git_sha is not None:
        return _git_sha

    sha = os.environ.get("GIT_COMMIT_SHA", "")
    if not sha:
        try:
            sha = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        except Exception:
            sha = "unknown"

    _git_sha = sha
    return _git_sha


@router.get("")
async def get_version():
    """获取应用版本信息"""
    return success_response(
        data={
            "version": settings.app_version,
            "git_sha": _get_git_sha(),
            "environment": settings.environment,
        },
        message="Version retrieved successfully",
    )
