"""
Pydantic models for Authentication operations.
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class UserLogin(BaseModel):
    """Login request model."""
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=6, description="User password")


class UserInDB(BaseModel):
    """User model as stored in database."""
    email: str
    hashed_password: str
    full_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True


class TokenRequest(BaseModel):
    """Token creation request (legacy - to be deprecated)."""
    user_id: str = Field(..., min_length=3, max_length=50, pattern="^[a-zA-Z0-9_]+$")


class TokenResponse(BaseModel):
    """Token response model."""
    access_token: str
    token_type: str = "bearer"