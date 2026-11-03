from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api.routes import api_router
from backend.app.core.errors import http_error_handler, validation_error_handler

app = FastAPI(
    title="MyGym Fitness KE API",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
)
app.add_exception_handler(StarletteHTTPException, http_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(api_router, prefix="/api")
