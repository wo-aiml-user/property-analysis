"""
Pydantic models for Authentication operations.
"""

from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from datetime import datetime

class UserLogin(BaseModel):
    """Login request model."""
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str):
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password is too long (maximum 72 bytes)")
        return v

class UserRegister(BaseModel):
    """Registration request model."""
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")
    full_name: Optional[str] = None
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")

        # bcrypt hard limit
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password is too long (maximum 72 bytes)")

        return v

class UserInDB(BaseModel):
    """User model as stored in database."""
    email: str
    hashed_password: str
    full_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True

class UserResponse(BaseModel):
    """Public user profile response."""
    email: str
    full_name: Optional[str] = None
    created_at: datetime
    is_active: bool
    
class TokenResponse(BaseModel):
    """Token response model."""
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int = Field(default=3600, description="Access token expiry in seconds")

class RefreshToken(BaseModel):
    """Refresh token model for DB storage."""
    user_id: str
    token_hash: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
    revoked: bool = False
    family_id: str = Field(..., description="ID to track token families for rotation")
    user_agent: Optional[str] = None
