from fastapi import FastAPI, Request
from starlette.exceptions import HTTPException
from fastapi.exceptions import RequestValidationError
from app.controller.auth_controller import router as auth_router
from app.controller.doc_controller import router as doc_router
from app.controller.chat_controller import router as chat_router
from app.utils.response import error_response

def setup_routes(app: FastAPI):
    """Setup all routes for the application"""

    # Setup exception handlers
    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc: HTTPException):
        return error_response("The requested resource was not found", 404)

    @app.exception_handler(405)
    async def method_not_allowed_handler(request: Request, exc: HTTPException):
        return error_response(f"Method {request.method} not allowed for this endpoint", 405)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # Get only the first error
        if exc.errors():
            error = exc.errors()[0]
            field = error["loc"][-1] if error["loc"] else "unknown field"
            error_message = f"{field} {error['msg']}".lower()
        else:
            error_message = "Validation error"
        
        return error_response(error_message, 422)

    # Include all routes
    app.include_router(auth_router, prefix="/auth", tags=["Auth"])
    app.include_router(doc_router, prefix="/doc", tags=["Document"])
    app.include_router(chat_router, prefix="/chat", tags=["Chat"])