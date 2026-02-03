from functools import lru_cache
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Base configuration
    APP_NAME: str = "Property Analysis API"
    DEBUG: bool = False
    
    # JWT configuration
    JWT_SECRET_KEY: str = "your-secret-key-here"  # Change this in production!
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7  # Refresh token valid for 7 days

    # Server configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Logging configuration
    LOG_LEVEL: str = "INFO"

    # CORS configuration
    CORS_ORIGINS: str = ""  # Empty by default, set to comma-separated list of domains or "*" for all
    CORS_METHODS: list = ["*"]
    CORS_HEADERS: list = ["*"]

    # Environment-specific settings (for dynamic behavior)
    ENVIRONMENT: str = "development"  # Default to development
    
    # OpenAI API configuration
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-image-1.5"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash-image"
    
    # AWS S3 configuration
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = ""
    AWS_BUCKET_NAME: str = ""
    
    # MongoDB configuration
    MONGODB_URI: str = ""
    MONGODB_DB_NAME: str = ""
    MONGODB_COLLECTION_NAME: str = ""
    
    class Config:
        env_file = ".env"  # Single .env file for all environments
        case_sensitive = True
        extra = "ignore"  # Allow extra env vars not defined in Settings

@lru_cache()
def get_settings():
    """
    Function to load settings based on the environment from the `.env` file.
    """
    settings = Settings()  # Load the settings from the .env file
    
    # Adjust settings dynamically based on the environment
    if settings.ENVIRONMENT.lower() == "production":
        settings.DEBUG = False
        settings.LOG_LEVEL = "INFO"
        # Parse CORS origins from the environment string
        if settings.CORS_ORIGINS:
            # Remove quotes if present
            cors_str = settings.CORS_ORIGINS.strip('"').strip("'")
            if cors_str == "*":
                settings.CORS_ORIGINS = []  # Disallow "*" in production for security
            else:
                settings.CORS_ORIGINS = [origin.strip() for origin in cors_str.split(",") if origin.strip()]
        else:
            settings.CORS_ORIGINS = []  # No CORS origins allowed if not specified
        settings.CORS_HEADERS: list = [
            "Authorization",  # For JWT tokens
            "Content-Type",   # For application/json and other content types
            "Accept",         # For content negotiation
            "Origin",        # Required for CORS
            "X-Requested-With"  # For AJAX requests
        ]
    else:
        settings.DEBUG = True
        settings.LOG_LEVEL = "DEBUG"
        settings.CORS_ORIGINS = [
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:3000",
            "http://localhost:8000"
        ]  # Specific origins for development with credentials
    
    return settings

# Create a settings instance
settings = get_settings()