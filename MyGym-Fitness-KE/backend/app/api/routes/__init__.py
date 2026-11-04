from fastapi import APIRouter

from backend.app.api.routes.gym_settings import router as gym_settings_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.operations import router as operations_router
from backend.app.api.routes.staff import router as staff_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(staff_router)
api_router.include_router(gym_settings_router)
api_router.include_router(operations_router)
