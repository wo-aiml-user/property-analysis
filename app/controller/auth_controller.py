"""
Authentication Controller - Register, Login, Refresh, Logout.
"""

from fastapi import APIRouter, Response, Request, Depends, Cookie
from datetime import timedelta, datetime
from typing import Optional
import uuid
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
        users_collection = await mongo.get_users_collection()
        if users_collection is None:
            logger.error("Users collection is None. Database connection might have failed.")
            return error_response("Database service unavailable", 503)

        logger.info("Checking if user exists...")
        # Check if user exists
        user_exists = await users_collection.find_one({"email": request.email})
        if user_exists:
            logger.info("User already exists")
            return success_response({
                "message": "You have already registered. Please sign in."
            }, 200)
            
        logger.info("Hashing password...")
        # Create user
        try:
            hashed_pw = get_password_hash(request.password)
            logger.info("Password hashed successfully")
        except Exception as e:
            logger.error(f"Password hashing failed: {e}")
            raise e

        # Create user document (normalized - no properties array)
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
        logger.error(f"Registration error for {request.email}: {e}")
        return error_response("Registration failed", 500)

@router.post("/login", response_model=TokenResponse)
async def login(response: Response, request: UserLogin, mongo: MongoService = Depends(get_mongo_service)):
    """Login and issue access/refresh tokens."""
    try:
        users_collection = await mongo.get_users_collection()
        user = await users_collection.find_one({"email": request.email})
        
        if not user:
            logger.warning(f"Login failed: User not found for email {request.email}")
            return error_response("You haven't signed up. Please sign up first.", 401)
            
        if not verify_password(request.password, user["hashed_password"]):
            logger.warning(f"Login failed: Invalid password for user {request.email}")
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
        }
        
        # Store refresh token
        await users_collection.update_one(
            {"_id": user["_id"]},
            {"$push": {"refresh_tokens": refresh_doc}}
        )
        
        logger.info(f"User logged in successfully: {user.get('full_name')}")
        
        # Create response first
        resp = success_response(TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        ))
        
        # Set HttpOnly Cookie on the response object
        resp.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value=refresh_token,
            httponly=True,
            secure=settings.ENVIRONMENT.lower() == "production",
            samesite="lax",
            path="/auth/refresh", # Restrict cookie to refresh endpoint
            max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
        )
        
        return resp
        
    except Exception as e:
        logger.error(f"Login error for {request.email}: {e}")
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
        logger.warning("Token refresh failed: Missing refresh_token cookie")
        return error_response("Refresh token missing", 401)
        
    try:
        token_hash = get_token_hash(refresh_token)
        users_col = await mongo.get_users_collection()
        
        # Find user with this token
        user = await users_col.find_one({"refresh_tokens.token_hash": token_hash})
        
        if not user:
            # Token not found in any user (possibly rotated/deleted)
            logger.warning("Attempted to use unknown refresh token")
            response.delete_cookie(REFRESH_COOKIE_NAME, path="/auth/refresh")
            return error_response("Invalid refresh token", 401)
            
        # Find the specific token object in the list
        stored_token = next((t for t in user.get("refresh_tokens", []) if t["token_hash"] == token_hash), None)
        
        if not stored_token:
            # Should not happen if query matched
            return error_response("Token mismatch", 401)

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
        
        # 1. Pull old token (delete it)
        await users_col.update_one(
            {"_id": user["_id"]},
            {"$pull": {"refresh_tokens": {"token_hash": token_hash}}}
        )
        
        # 2. Issue new tokens
        new_access_token = JWTAuth.create_token(
            {"user_id": str(user["_id"]), "email": user["email"]}
        )
        
        new_refresh_token = generate_opaque_token()
        new_refresh_hash = get_token_hash(new_refresh_token)
        
        new_refresh_doc = {
            "user_id": str(user["_id"]),
            "family_id": stored_token.get("family_id", str(uuid.uuid4())), # Preserve family ID if exists
            "token_hash": new_refresh_hash,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            "revoked": False,
        }
        
        # Add new token to user's list
        await users_col.update_one(
            {"_id": user["_id"]},
            {"$push": {"refresh_tokens": new_refresh_doc}}
        )
        
        # Create response
        resp = success_response(TokenResponse(access_token=new_access_token))
        
        # Set new cookie on response
        resp.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value=new_refresh_token,
            httponly=True,
            secure=settings.ENVIRONMENT.lower() == "production",
            samesite="lax",
            path="/auth/refresh",
            max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
        )
        
        return resp
    
    except Exception as e:
        logger.error(f"Refresh error: {e}")
        return error_response("Token refresh failed", 500)

@router.post("/logout")
async def logout(response: Response, refresh_token: Optional[str] = Cookie(None, alias=REFRESH_COOKIE_NAME), mongo: MongoService = Depends(get_mongo_service)):
    """Logout user and delete token."""
    logger.info("Logout request received")
    if refresh_token:
        try:
            token_hash = get_token_hash(refresh_token)
            users_col = await mongo.get_users_collection()
            
            # Delete token from user's list
            await users_col.update_one(
                {"refresh_tokens.token_hash": token_hash},
                {"$pull": {"refresh_tokens": {"token_hash": token_hash}}}
            )
        except Exception:
            pass # Fail silently on logout
            
    # Create response and delete cookie
    resp = success_response({"message": "Logged out successfully"})
    resp.delete_cookie(REFRESH_COOKIE_NAME, path="/auth/refresh")
    logger.info("Logged out successfully")
    return resp