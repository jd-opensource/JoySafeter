import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class Packages(BaseModel):
    apt: list[str] = Field(default_factory=list)
    pip: list[str] = Field(default_factory=list)
    npm: list[str] = Field(default_factory=list)
    cargo: list[str] = Field(default_factory=list)
    gem: list[str] = Field(default_factory=list)
    go: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not any([self.apt, self.pip, self.npm, self.cargo, self.gem, self.go])

    def install_commands(self) -> list[str]:
        cmds: list[str] = []
        if self.apt:
            cmds.append(f"apt-get update && apt-get install -y {' '.join(self.apt)}")
        if self.pip:
            cmds.append(f"pip install {' '.join(self.pip)}")
        if self.npm:
            cmds.append(f"npm install -g {' '.join(self.npm)}")
        if self.cargo:
            cmds.append(f"cargo install {' '.join(self.cargo)}")
        if self.gem:
            cmds.append(f"gem install {' '.join(self.gem)}")
        if self.go:
            cmds.append(f"go install {' '.join(self.go)}")
        return cmds


class Networking(BaseModel):
    type: str = "unrestricted"
    allowed_hosts: list[str] = Field(default_factory=list)
    allow_mcp_servers: bool = False
    allow_package_managers: bool = False

    def is_default(self) -> bool:
        return self.type == "unrestricted"

    @staticmethod
    def normalize_allowed_host(host: str) -> str:
        host = host.lower().strip()
        for prefix in ("https://", "http://"):
            if host.startswith(prefix):
                host = host[len(prefix):]
        return host.rstrip("/")


class EnvironmentConfig(BaseModel):
    type: str = "cloud"
    packages: Packages = Field(default_factory=Packages)
    networking: Networking = Field(default_factory=Networking)


class CreateEnvironmentRequest(BaseModel):
    name: str
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    config: EnvironmentConfig = Field(default_factory=EnvironmentConfig)


class UpdateEnvironmentRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    config: Optional[EnvironmentConfig] = None


class EnvironmentResponse(BaseModel):
    id: uuid.UUID
    type: str = "environment"
    name: str
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    config: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    image_tag: Optional[str] = None
    image_version: int = 0

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"env_{v}"
