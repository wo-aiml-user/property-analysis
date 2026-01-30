from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from typing import Any
from pydantic import BaseModel


def success_response(data: Any, status_code: int = 200) -> JSONResponse:
    # jsonable_encoder handles Pydantic models and datetime objects
    return JSONResponse(
        content=jsonable_encoder({"result": data}),
        status_code=status_code
    )

def error_response(error: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        content={"error": error},
        status_code=status_code
    )