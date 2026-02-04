from fastapi import HTTPException
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
from typing import Optional
from app.config import settings
from loguru import logger

# You should store this securely in environment variables
JWT_SECRET_KEY = settings.JWT_SECRET_KEY
JWT_ALGORITHM = settings.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

class JWTAuth:
    @staticmethod
    def create_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """
        Create a new JWT token
        """
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
            
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        return encoded_jwt
    
    @staticmethod
    def decrypt_token(token: str) -> dict:
        """
        Decrypt and validate the JWT token
        """
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return payload
        except JWTError as e:
            logger.error(f"JWT validation error: {str(e)}")
            raise HTTPException(
                status_code=403,
                detail="Invalid token or expired token"
            )

    @staticmethod
    def verify_token(auth_header: str | None) -> dict:
        """Verify JWT token and return payload
        
        Args:
            auth_header: Authorization header containing the Bearer token
            
        Returns:
            dict: The token payload
            
        Raises:
            HTTPException: If token is invalid or missing required data
        """
        if not auth_header:
            logger.error("No authorization header found")
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        logger.debug("Auth header received")
        
        scheme = ""
        token = ""
        
        try:
            scheme, token = auth_header.split()
        except ValueError:
            logger.error("Invalid authorization header format")
            raise HTTPException(status_code=401, detail="Invalid authorization header format")

        if scheme.lower() != "bearer":
            logger.error(f"Invalid authentication scheme: {scheme}")
            raise HTTPException(status_code=401, detail="Invalid authentication scheme")

        logger.debug("Verifying token...")
        
        try:
            payload = JWTAuth.decrypt_token(token)
            logger.info(f"Token verified successfully for user: {payload.get('user_id')}")
                
            return payload
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Token validation error: {str(e)}")
            raise HTTPException(status_code=401, detail="Invalid token")
