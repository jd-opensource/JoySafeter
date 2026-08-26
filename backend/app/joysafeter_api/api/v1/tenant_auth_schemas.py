from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.joysafeter_shared.ids import OrganizationId, ProjectId, UserId


class LoginUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UserId
    email: str
    name: str
    image: str | None = None
    email_verified: bool = Field(serialization_alias="emailVerified")
    is_super_user: bool = Field(serialization_alias="isSuperUser")
    created_at: datetime | None = Field(default=None, serialization_alias="createdAt")
    updated_at: datetime | None = Field(default=None, serialization_alias="updatedAt")


class LoginResponseData(BaseModel):
    user: LoginUserResponse
    access_token: str
    refresh_token: str
    csrf_token: str
    token_type: str
    expires_in: int


class RegistrationResponseData(BaseModel):
    user: LoginUserResponse


class RefreshResponseData(BaseModel):
    access_token: str
    csrf_token: str
    token_type: str
    expires_in: int


class AuthUserSummaryResponse(BaseModel):
    id: UserId
    email: str
    name: str


class OrganizationContextResponse(BaseModel):
    id: OrganizationId
    name: str
    slug: str
    role: str
    owner_name: str | None = None
    owner_email: str | None = None
    project_creation_policy: Literal["admins_only", "all_members"]
    created_at: str | None = None


class ProjectContextResponse(BaseModel):
    id: ProjectId
    org_id: OrganizationId
    name: str
    slug: str
    is_default: bool
    archived_at: str | None = None


class ActiveProjectContextResponse(ProjectContextResponse):
    project_role: str | None = None
    capability: str


class AuthMeResponse(BaseModel):
    user: AuthUserSummaryResponse
    organization: OrganizationContextResponse
    project: ActiveProjectContextResponse
    organizations: list[OrganizationContextResponse]
    projects: list[ProjectContextResponse]


class SwitchContextResponse(BaseModel):
    org_id: OrganizationId
    project_id: ProjectId
    access_token: str
    project: ActiveProjectContextResponse
    projects: list[ProjectContextResponse]
