"""
用户 Schema
"""

from typing import Optional

from pydantic import BaseModel, EmailStr

from .common import IDSchema


class UserBase(BaseModel):
    """用户基础"""

    email: EmailStr
    username: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    avatar: Optional[str] = None


class UserResponse(IDSchema, UserBase):
    """用户响应"""

    is_active: bool
    is_superuser: bool
    is_verified: bool

    @property
    def full_name(self) -> str:
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.username
