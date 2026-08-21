from fastapi import APIRouter
from app.core.config import state
from app.models import HealthResponse

router = APIRouter()

@router.get(path="/health", response_model=HealthResponse, tags=["system"])
async def health():
    return HealthResponse(
        status="healthy",
        model_loaded=state.client is not None
    )