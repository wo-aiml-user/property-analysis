"""
Authentication Controller - User login.
"""

from fastapi import APIRouter, HTTPException
from datetime import timedelta
from passlib.context import CryptContext
from loguru import logger

from app.utils.response import error_response, success_response
from app.middleware.jwt_auth import JWTAuth
from app.model.auth_model import UserLogin, TokenResponse
from app.services.mongo_service import get_mongo_service
from app.config import settings


router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


@router.post("/login", response_model=TokenResponse)
async def login(request: UserLogin):
    """
    User login endpoint.
    
    Parameters:
    - email: User email address
    - password: User password
    
    Returns:
    - access_token: JWT token for authenticated requests
    - token_type: "bearer"
    """
    try:
        mongo = get_mongo_service()
        users_collection = mongo.get_users_collection()
        
        if not users_collection:
            logger.error("Users collection not available")
            return error_response("Database connection error", 500)
        
        # Find user by email
        user = users_collection.find_one({"email": request.email})
        
        if not user:
            return error_response("Invalid email or password", 401)
        
        # Verify password
        if not verify_password(request.password, user["hashed_password"]):
            return error_response("Invalid email or password", 401)
        
        # Check if user is active
        if not user.get("is_active", True):
            return error_response("Account is inactive", 403)
        
        # Create JWT token
        token = JWTAuth.create_token(
            {"user_id": str(user["_id"]), "email": user["email"]},
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        
        logger.info(f"User logged in: {request.email}")
        return success_response(
            TokenResponse(access_token=token, token_type="bearer"),
            200
        )
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return error_response("Login failed", 500)