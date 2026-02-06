"""
Security utilities for password hashing, token generation, and verification.
"""

import secrets
import hashlib
from typing import Optional
import bcrypt
from loguru import logger
from passlib.context import CryptContext

# Fix for passlib incompatibility with bcrypt >= 4.0
if not hasattr(bcrypt, "__about__"):
    try:
        class About:
            __version__ = bcrypt.__version__
        bcrypt.__about__ = About()
    except Exception:
        pass


# Setup password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Generate a bcrypt hash for a password."""
    try:
        logger.info(f"Hashing password of length: {len(password)}")
        return pwd_context.hash(password)
    except Exception as e:
        logger.error(f"Error in pwd_context.hash: {e}")
        raise e

def generate_opaque_token(length: int = 64) -> str:
    """Generate a secure random string for use as a refresh token."""
    return secrets.token_urlsafe(length)

def get_token_hash(token: str) -> str:
    """
    Generate a SHA-256 hash of the token for storage.
    We hash refresh tokens so that even if the DB is compromised, 
    active tokens cannot be used without the cookie.
    """
    return hashlib.sha256(token.encode()).hexdigest()
