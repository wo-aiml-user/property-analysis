from fastapi import HTTPException, Request, FastAPI
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from loguru import logger
from app.services.token import JWTAuth
from app.utils.response import error_response

# Paths that don't require authentication
PUBLIC_PATHS = [
    "/docs",  # Swagger UI
    "/redoc",  # ReDoc UI
    "/openapi.json",  # OpenAPI schema
    "/auth/login",  # User login endpoint
    "/auth/register",
    "/auth/refresh",
    "/auth/logout",
]

class JWTAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, exclude_paths=None):
        super().__init__(app)
        self.exclude_paths = exclude_paths or PUBLIC_PATHS

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        request_path = request.url.path
        request_method = request.method

        logger.debug(f"JWT Middleware: {request_method} {request_path}")

        # Allow public paths without authentication
        if any(request_path.startswith(path) for path in self.exclude_paths):
            logger.debug(f"Public path, skipping auth: {request_path}")
            return await call_next(request)

        logger.debug(f"Protected path, checking auth: {request_path}")

        # Get Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            logger.error(f"No Authorization header for {request_method} {request_path}")
            return error_response("Authentication required", 401)
        
        # Validate Bearer token format
        try:
            jwt_payload = JWTAuth.verify_token(auth_header)
            # Store the jwt_payload in the request state
            request.state.jwt_payload = jwt_payload
            logger.info(f"JWT payload set in request.state for user: {jwt_payload.get('user_id')}")
            return await call_next(request)  # Continue processing
        except HTTPException as e:
            logger.error(f"JWT validation error: {str(e)}")
            return error_response(str(e.detail), e.status_code)
        except Exception as e:
            logger.error(f"Unexpected error in JWT middleware: {str(e)}")
            return error_response("Internal server error", 500)