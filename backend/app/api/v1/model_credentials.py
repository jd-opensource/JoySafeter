"""
Model credential management API
"""

import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.response import success_response
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.model_credential_service import ModelCredentialService

router = APIRouter(prefix="/v1/model-credentials", tags=["ModelCredentials"])


class CredentialCreate(BaseModel):
    """Create/update credential request (builtin providers only)."""

    provider_name: str = Field(description="Provider name", examples=["openaiapicompatible"])
    credentials: Dict[str, Any] = Field(..., description="Credentials dict (plaintext)")
    should_validate: bool = Field(default=True, alias="validate", description="Whether to validate credentials")


@router.post("")
async def create_or_update_credential(
    payload: CredentialCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create or update a builtin provider's credential."""
    service = ModelCredentialService(db)
    credential = await service.upsert_credential(
        user_id=current_user.id,
        provider_name=payload.provider_name,
        credentials=payload.credentials,
        validate=payload.should_validate,
    )
    return success_response(data=credential, message="Credential created/updated")


@router.get("")
async def list_credentials(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List credentials (global, workspace-independent).
    """
    service = ModelCredentialService(db)
    credentials = await service.list_credentials()
    return success_response(data=credentials, message="Credential list retrieved")


@router.get("/{credential_id}")
async def get_credential(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get credential details.

    Args:
        credential_id: credential ID

    Returns:
        Credential details (without decrypted credentials)
    """
    service = ModelCredentialService(db)
    credential = await service.get_credential(credential_id, include_credentials=True)
    return success_response(data=credential, message="Credential details retrieved")


@router.post("/{credential_id}/validate")
async def validate_credential(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Validate a credential.

    Args:
        credential_id: credential ID

    Returns:
        Validation result
    """
    service = ModelCredentialService(db)
    result = await service.validate_credential(credential_id)
    return success_response(data=result, message="Credential validation completed")


@router.delete("/{credential_id}")
async def delete_credential(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a credential.

    Args:
        credential_id: credential ID
    """
    service = ModelCredentialService(db)
    await service.delete_credential(credential_id)
    return success_response(message="Credential deleted")
