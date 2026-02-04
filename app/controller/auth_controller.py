"""
Authentication Controller - Register, Login, Refresh, Logout.
"""

from fastapi import APIRouter, Response, Request, Depends, Cookie
from datetime import timedelta, datetime
from typing import Optional
from loguru import logger

from app.utils.response import error_response, success_response
from app.model.auth_model import UserLogin, UserRegister, UserResponse, TokenResponse
from app.services.mongo_service import get_mongo_service, MongoService
from app.services.security import verify_password, get_password_hash, generate_opaque_token, get_token_hash
from app.services.token import JWTAuth
from app.config import settings

router = APIRouter()

REFRESH_COOKIE_NAME = "refresh_token"

@router.post("/register", response_model=UserResponse, status_code=201)
async def register(request: UserRegister, mongo: MongoService = Depends(get_mongo_service)):
    """Register a new user."""
    logger.info(f"Received registration request for email: {request.email}")
    try:
        users_collection = mongo.get_users_collection()
        if users_collection is None:
            logger.error("Users collection is None. Database connection might have failed.")
            return error_response("Database service unavailable", 503)

        logger.info("Checking if user exists...")
        # Check if user exists
        if await users_collection.find_one({"email": request.email}):
            logger.info("User already exists")
            return error_response("Email already registered", 400)
            
        logger.info("Hashing password...")
        # Create user
        try:
            hashed_pw = get_password_hash(request.password)
            logger.info("Password hashed successfully")
        except Exception as e:
            logger.error(f"Password hashing failed: {e}")
            raise e

        user_doc = {
            "email": request.email,
            "hashed_password": hashed_pw,
            "full_name": request.full_name,
            "created_at": datetime.utcnow(),
            "is_active": True
        }
        
        logger.info("Inserting user into database...")
        await users_collection.insert_one(user_doc)
        logger.info("User inserted successfully")
        
        return success_response(UserResponse(**user_doc), 201)
        
    except Exception as e:
        logger.error(f"Registration error: {e}")
        return error_response("Registration failed", 500)

@router.post("/login", response_model=TokenResponse)
async def login(response: Response, request: UserLogin, user_agent: Optional[str] = None, mongo: MongoService = Depends(get_mongo_service)):
    """Login and issue access/refresh tokens."""
    try:
        users_collection = mongo.get_users_collection()
        user = await users_collection.find_one({"email": request.email})
        
        if not user or not verify_password(request.password, user["hashed_password"]):
            return error_response("Invalid email or password", 401)
            
        if not user.get("is_active", True):
            return error_response("Account is inactive", 403)
            
        # 1. Access Token (JWT)
        access_token = JWTAuth.create_token(
            {"user_id": str(user["_id"]), "email": user["email"]}
        )
        
        # 2. Refresh Token (Opaque)
        refresh_token = generate_opaque_token()
        refresh_token_hash = get_token_hash(refresh_token)
        
        refresh_doc = {
            "user_id": str(user["_id"]),
            "token_hash": refresh_token_hash,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            "revoked": False,
            "user_agent": user_agent
        }
        
        # Store refresh token
        await mongo.db["refresh_tokens"].insert_one(refresh_doc)
        
        # Set HttpOnly Cookie
        response.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value=refresh_token,
            httponly=True,
            secure=settings.ENVIRONMENT.lower() == "production",
            samesite="lax",
            path="/auth/refresh", # Restrict cookie to refresh endpoint
            max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
        )
        
        return success_response(TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        ))
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        return error_response("Login failed", 500)

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    response: Response, 
    request: Request,
    refresh_token: Optional[str] = Cookie(None, alias=REFRESH_COOKIE_NAME),
    mongo: MongoService = Depends(get_mongo_service)
):
    """Rotate refresh token and issue new access token."""
    if not refresh_token:
        return error_response("Refresh token missing", 401)
        
    try:
        token_hash = get_token_hash(refresh_token)
        tokens_col = mongo.db["refresh_tokens"]
        
        # Find token
        stored_token = await tokens_col.find_one({"token_hash": token_hash})
        
        if not stored_token:
            # Token reuse detection? If we can't find it, it might have been rotated or is just garbage.
            # Ideally we would track it, but for now just fail.
            logger.warning("Attempted to use unknown refresh token")
            response.delete_cookie(REFRESH_COOKIE_NAME, path="/auth/refresh")
            return error_response("Invalid refresh token", 401)
            
        # Check if revoked
        if stored_token.get("revoked"):
            logger.warning(f"Attempted to use revoked token")
            response.delete_cookie(REFRESH_COOKIE_NAME, path="/auth/refresh")
            return error_response("Token has been revoked", 401)
            
        # Check expiration
        if stored_token["expires_at"] < datetime.utcnow():
            response.delete_cookie(REFRESH_COOKIE_NAME, path="/auth/refresh")
            return error_response("Token expired", 401)
            
        # --- Token Rotation ---
        
        # 1. Revoke current token
        await tokens_col.update_one(
            {"_id": stored_token["_id"]},
            {"$set": {"revoked": True}}
        )
        
        # 2. Issue new tokens
        users_col = mongo.get_users_collection()
        from bson.objectid import ObjectId
        user = await users_col.find_one({"_id": ObjectId(stored_token["user_id"])})
        
        if not user:
            return error_response("User not found", 401)
            
        new_access_token = JWTAuth.create_token(
            {"user_id": str(user["_id"]), "email": user["email"]}
        )
        
        new_refresh_token = generate_opaque_token()
        new_refresh_hash = get_token_hash(new_refresh_token)
        
        new_refresh_doc = {
            "user_id": stored_token["user_id"],
            "token_hash": new_refresh_hash,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            "revoked": False,
            "user_agent": request.headers.get("user-agent")
        }
        
        await tokens_col.insert_one(new_refresh_doc)
        
        # Set new cookie
        response.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value=new_refresh_token,
            httponly=True,
            secure=settings.ENVIRONMENT.lower() == "production",
            samesite="lax",
            path="/auth/refresh",
            max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
        )
        
        return success_response(TokenResponse(access_token=new_access_token))

    except Exception as e:
        logger.error(f"Refresh error: {e}")
        return error_response("Token refresh failed", 500)

@router.post("/logout")
async def logout(response: Response, refresh_token: Optional[str] = Cookie(None, alias=REFRESH_COOKIE_NAME), mongo: MongoService = Depends(get_mongo_service)):
    """Logout user and revoke token."""
    if refresh_token:
        try:
            token_hash = get_token_hash(refresh_token)
            await mongo.db["refresh_tokens"].update_one(
                {"token_hash": token_hash},
                {"$set": {"revoked": True}}
            )
        except Exception:
            pass # Fail silently on logout
            
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/auth/refresh")
    return success_response({"message": "Logged out successfully"})