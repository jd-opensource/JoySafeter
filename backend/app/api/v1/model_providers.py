"""Model provider management API"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.response import success_response
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.model_provider_service import ModelProviderService

router = APIRouter(prefix="/v1/model-providers", tags=["ModelProviders"])


class ProviderDefaultsUpdate(BaseModel):
    """Update provider default parameters request."""

    default_parameters: Dict[str, Any] = Field(
        description="Provider-level default parameters, e.g. {temperature: 0.7, max_tokens: 2000}"
    )


@router.get("")
async def list_providers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all providers."""
    service = ModelProviderService(db)
    providers = await service.get_all_providers()
    return success_response(data=providers, message="Provider list retrieved")


class CustomProviderCreate(BaseModel):
    """Add custom provider request."""

    model_name: str = Field(description="Model name", examples=["gpt-4o"])
    credentials: Dict[str, Any] = Field(description="Credentials dict (plaintext)")
    display_name: Optional[str] = Field(default=None, description="Custom display name")
    model_parameters: Optional[Dict[str, Any]] = Field(default=None, description="Model parameters")
    validate_credentials: bool = Field(default=True, description="Whether to validate credentials")


@router.post("/custom")
async def add_custom_provider(
    payload: CustomProviderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a custom provider (one-step creation of provider + credential + model_instance)."""
    service = ModelProviderService(db)
    result = await service.add_custom_provider(
        user_id=current_user.id,
        credentials=payload.credentials,
        model_name=payload.model_name,
        display_name=payload.display_name,
        model_parameters=payload.model_parameters,
        validate=payload.validate_credentials,
    )
    return success_response(data=result, message="Custom provider added")


@router.get("/{provider_name}")
async def get_provider(
    provider_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single provider's details."""
    service = ModelProviderService(db)
    provider = await service.get_provider(provider_name)

    if not provider:
        from app.common.exceptions import NotFoundException

        raise NotFoundException(f"Provider not found: {provider_name}")

    return success_response(data=provider, message="Provider details retrieved")


@router.patch("/{provider_name}/defaults")
async def update_provider_defaults(
    provider_name: str,
    payload: ProviderDefaultsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update provider-level default parameters."""
    service = ModelProviderService(db)
    provider = await service.update_provider_defaults(provider_name, payload.default_parameters)
    return success_response(data=provider, message="Provider defaults updated")


@router.post("/sync")
async def sync_providers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sync providers and model info to the database."""
    service = ModelProviderService(db)
    result = await service.sync_all()
    return success_response(data=result, message="Sync completed")


@router.delete("/{provider_name}")
async def delete_provider(
    provider_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a provider (custom providers only)."""
    service = ModelProviderService(db)
    await service.delete_provider(provider_name)
    return success_response(message=f"Provider {provider_name} deleted")
