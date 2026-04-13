from fastapi import APIRouter, Depends, HTTPException

from src.api.auth import AuthContext, require_roles
from src.api.dependencies import prediction_service
from src.api.schemas import PredictionRequest, PredictionResponse


router = APIRouter(tags=["predict"])


@router.post("/predict", response_model=PredictionResponse)
def predict(
    payload: PredictionRequest,
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> PredictionResponse:
    try:
        prediction_result = prediction_service.predict_all_models(payload.model_dump())
        return PredictionResponse(**prediction_result)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
