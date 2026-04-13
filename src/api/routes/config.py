from fastapi import APIRouter
from fastapi import Depends

from src.api.auth import AuthContext, require_roles
from src.api.dependencies import prediction_service
from src.api.schemas import ModelConfigResponse


router = APIRouter(tags=["config"])


@router.get("/config", response_model=ModelConfigResponse)
def get_model_config(
    auth: AuthContext = Depends(require_roles("counsellor", "admin", "system")),
) -> ModelConfigResponse:
    return ModelConfigResponse(**prediction_service.model_config)
