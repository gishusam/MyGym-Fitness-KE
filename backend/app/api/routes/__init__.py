from fastapi import APIRouter

from backend.app.api.routes.gym_settings import router as gym_settings_router
from backend.app.api.routes.events import router as events_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.operations import router as operations_router
from backend.app.api.routes.onboarding import router as onboarding_router
from backend.app.api.routes.staff import router as staff_router
from backend.app.api.routes.workouts import router as workouts_router
from backend.app.api.routes.workspaces import router as workspaces_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(staff_router)
api_router.include_router(gym_settings_router)
api_router.include_router(workspaces_router)
api_router.include_router(operations_router)
api_router.include_router(onboarding_router)
api_router.include_router(workouts_router)
api_router.include_router(events_router)
