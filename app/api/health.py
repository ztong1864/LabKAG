from fastapi import APIRouter

from app.config import settings
from app.services.skill_orchestrator import success_response

router = APIRouter()


@router.get("/health")
def health():
    return success_response(
        data={
            "service": settings.app_name,
            "version": settings.app_version,
        }
    )
