from app.config import settings
from fastapi import FastAPI
from .logging import log_requests_middleware
from fastapi.middleware.cors import CORSMiddleware
from .jwt_auth import JWTAuthMiddleware

def setup_middlewares(app: FastAPI):
    """Apply all middlewares to the FastAPI app"""
    
    # Add JWT authentication middleware first
    app.add_middleware(JWTAuthMiddleware)
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,  # Configure this appropriately for production
        allow_credentials=True,
        allow_methods=settings.CORS_METHODS,
        allow_headers=settings.CORS_HEADERS,
    )
    
    # Add logging middleware last
    app.middleware("http")(log_requests_middleware)