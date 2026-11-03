from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


async def http_error_handler(
    _request: Request, exception: StarletteHTTPException
) -> JSONResponse:
    detail = exception.detail
    if isinstance(detail, dict) and "error" in detail and "code" in detail:
        payload = detail
    else:
        payload = {
            "error": str(detail),
            "code": "request_error",
        }
    return JSONResponse(status_code=exception.status_code, content=payload)


async def validation_error_handler(
    _request: Request, _exception: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": "The submitted data is invalid", "code": "validation_error"},
    )
