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
    "/token",  # Token generation endpoint (legacy)
    "/health",  # Health check endpoint if you have one
    "/auth/token",  # Token generation endpoint (legacy)
    "/auth/login",  # User login endpoint
    "/auth/register",
    "/auth/refresh",
    "/auth/logout",
    "/doc/image/",  # Image serving endpoint (verifies ownership internally)
]

class JWTAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, exclude_paths=None):
        super().__init__(app)
        self.exclude_paths = exclude_paths or PUBLIC_PATHS
        self.valid_routes = None  # Initialize as None

    def get_valid_routes(self, app: FastAPI):
        """ Extract all (path, method) pairs after app is fully initialized. """
        if self.valid_routes is None:
            self.valid_routes = set()
            for route in app.router.routes:
                if hasattr(route, "path") and hasattr(route, "methods"):
                    for method in route.methods:
                        self.valid_routes.add((route.path, method))
        return self.valid_routes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        request_path = request.url.path
        request_method = request.method

        # Ensure routes are extracted after app initialization
        valid_routes = self.get_valid_routes(request.app)

        # Check if the route exists with the correct method
        if (request_path, request_method) not in valid_routes:
            # Check if the path exists but method is incorrect → 405
            if any(request_path == path for path, _ in valid_routes):
                return await call_next(request)
            # Otherwise, the route does not exist → 404
            return await call_next(request)

        # Allow public paths without authentication
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            return await call_next(request)

        # Get Authorization header
        auth_header = request.headers.get("Authorization")
        # Validate Bearer token format
        try:
            jwt_payload = JWTAuth.verify_token(auth_header)
            # Store the jwt_payload in the request state
            request.state.jwt_payload = jwt_payload
            return await call_next(request)  # Continue processing
        except HTTPException as e:
            logger.error(f"JWT validation error: {str(e)}")
            return error_response(str(e.detail), e.status_code)
        except Exception as e:
            logger.error(f"Unexpected error in JWT middleware: {str(e)}")
            return error_response("Internal server error", 500)