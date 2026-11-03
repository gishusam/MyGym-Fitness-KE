from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz", operation_id="healthCheck")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
