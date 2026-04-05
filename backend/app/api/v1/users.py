"""
User API (path: /api/v1/users)
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.exceptions import ForbiddenException, NotFoundException
from app.common.response import success_response
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.settings import Settings
from app.services.user_service import UserService
from app.services.workspace_file_service import WorkspaceFileService

router = APIRouter(prefix="/v1/users", tags=["Users"])


# Schemas


class UserCreateRequest(BaseModel):
    """Create user request."""

    email: EmailStr
    name: str = Field(..., min_length=1, max_length=255)
    image: Optional[str] = None
    is_super_user: bool = False
    email_verified: bool = False


class UserUpdateRequest(BaseModel):
    """Update user request."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    image: Optional[str] = None
    is_super_user: Optional[bool] = None
    email_verified: Optional[bool] = None
    stripe_customer_id: Optional[str] = None


class UserResponse(BaseModel):
    """User response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str
    image: Optional[str]
    email_verified: bool
    is_super_user: bool
    stripe_customer_id: Optional[str]
    created_at: str
    updated_at: str


class SettingsUpdateRequest(BaseModel):
    """Update settings request."""

    autoConnect: Optional[bool] = None
    showTrainingControls: Optional[bool] = None
    superUserModeEnabled: Optional[bool] = None
    theme: Optional[str] = None
    telemetryEnabled: Optional[bool] = None
    billingUsageNotificationsEnabled: Optional[bool] = None
    errorNotificationsEnabled: Optional[bool] = None


# Endpoints


@router.get("/me", response_model=UserResponse)
async def get_me(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current user profile."""
    return success_response(
        data=_user_to_response(current_user),
        message="Fetched user profile",
    )


@router.put("/me", response_model=UserResponse)
async def update_me(
    request: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update current user profile."""
    service = UserService(db)
    updated_user = await service.update_user(
        current_user,
        name=request.name,
        email=request.email,
        image=request.image,
    )
    return success_response(
        data=_user_to_response(updated_user),
        message="Profile updated successfully",
    )


@router.get("/me/settings")
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current user settings."""
    result = await db.execute(select(Settings).where(Settings.user_id == current_user.id))
    settings = result.scalar_one_or_none()

    if not settings:
        # if no record exists, return defaults
        default_settings = {
            "autoConnect": True,
            "showTrainingControls": False,
            "superUserModeEnabled": True,
            "theme": "dark",
            "telemetryEnabled": True,
            "billingUsageNotificationsEnabled": True,
            "errorNotificationsEnabled": True,
        }
        return {"success": True, "data": default_settings}

    return {
        "success": True,
        "data": {
            "autoConnect": settings.auto_connect,
            "showTrainingControls": settings.show_training_controls,
            "superUserModeEnabled": settings.super_user_mode_enabled,
            "theme": settings.theme,
            "telemetryEnabled": settings.telemetry_enabled,
            "billingUsageNotificationsEnabled": settings.billing_usage_notifications_enabled,
            "errorNotificationsEnabled": settings.error_notifications_enabled,
        },
    }


@router.patch("/me/settings")
async def update_settings(
    request: SettingsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update current user settings."""
    result = await db.execute(select(Settings).where(Settings.user_id == current_user.id))
    settings = result.scalar_one_or_none()

    if not settings:
        # if no record exists, create one
        settings = Settings(user_id=current_user.id)
        db.add(settings)

    # update only the provided fields
    if request.autoConnect is not None:
        settings.auto_connect = request.autoConnect
    if request.showTrainingControls is not None:
        settings.show_training_controls = request.showTrainingControls
    if request.superUserModeEnabled is not None:
        settings.super_user_mode_enabled = request.superUserModeEnabled
    if request.theme is not None:
        settings.theme = request.theme
    if request.telemetryEnabled is not None:
        settings.telemetry_enabled = request.telemetryEnabled
    if request.billingUsageNotificationsEnabled is not None:
        settings.billing_usage_notifications_enabled = request.billingUsageNotificationsEnabled
    if request.errorNotificationsEnabled is not None:
        settings.error_notifications_enabled = request.errorNotificationsEnabled

    await db.commit()
    await db.refresh(settings)

    return {
        "success": True,
        "data": {
            "autoConnect": settings.auto_connect,
            "showTrainingControls": settings.show_training_controls,
            "superUserModeEnabled": settings.super_user_mode_enabled,
            "theme": settings.theme,
            "telemetryEnabled": settings.telemetry_enabled,
            "billingUsageNotificationsEnabled": settings.billing_usage_notifications_enabled,
            "errorNotificationsEnabled": settings.error_notifications_enabled,
        },
    }


@router.get("/me/usage-limits")
async def get_usage_limits(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current user's storage usage (workspace files)."""
    service = WorkspaceFileService(db)
    storage = await service.get_user_storage_usage(current_user)
    usage = {"plan": "standard"}
    base = success_response(
        data={"storage": storage, "usage": usage},
        message="Fetched storage usage",
    )
    return {**base, "storage": storage, "usage": usage}


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get user by ID (requires superuser permission)."""
    if not current_user.is_superuser:
        raise ForbiddenException("Forbidden")

    service = UserService(db)
    user = await service.get_user_by_id(user_id)
    if not user:
        raise NotFoundException("User not found")

    return success_response(
        data=_user_to_response(user),
        message="Fetched user",
    )


@router.get("", response_model=list[UserResponse])
async def list_users(
    keyword: Optional[str] = Query(None, description="Search keyword"),
    limit: int = Query(20, ge=1, le=100, description="Result limit"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search/list users (requires superuser permission)."""
    if not current_user.is_superuser:
        raise ForbiddenException("Forbidden")

    service = UserService(db)
    if keyword:
        users = await service.search_users(keyword, limit)
    else:
        users = await service.list_users(limit)

    return success_response(
        data=[_user_to_response(user) for user in users],
        message="Fetched users",
    )


@router.post("", response_model=UserResponse)
async def create_user(
    request: UserCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new user (requires superuser permission)."""
    if not current_user.is_superuser:
        raise ForbiddenException("Forbidden")

    service = UserService(db)
    user = await service.create_user(
        email=request.email,
        name=request.name,
        image=request.image,
        is_super_user=request.is_super_user,
        email_verified=request.email_verified,
    )

    return success_response(
        data=_user_to_response(user),
        message="User created successfully",
    )


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    request: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update user info (requires superuser permission)."""
    if not current_user.is_superuser:
        raise ForbiddenException("Forbidden")

    service = UserService(db)
    user = await service.get_user_by_id(user_id)
    if not user:
        raise NotFoundException("User not found")

    updated_user = await service.update_user(
        user,
        name=request.name,
        email=request.email,
        image=request.image,
        is_super_user=request.is_super_user,
        email_verified=request.email_verified,
        stripe_customer_id=request.stripe_customer_id,
    )

    return success_response(
        data=_user_to_response(updated_user),
        message="User updated successfully",
    )


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a user (requires superuser permission)."""
    if not current_user.is_superuser:
        raise ForbiddenException("Forbidden")

    service = UserService(db)
    await service.delete_user(user_id)

    return success_response(message="User deleted successfully")


# Helpers


def _user_to_response(user: User) -> dict:
    """Convert a User model to response format."""
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "image": user.image,
        "email_verified": user.email_verified,
        "is_super_user": user.is_super_user,
        "stripe_customer_id": user.stripe_customer_id,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }
