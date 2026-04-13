from fastapi import APIRouter, Depends, HTTPException

from src.api.auth import AUTH_ENABLED, AuthContext, create_access_token, get_auth_context
from src.api.schemas import AuthLoginRequest, AuthMeResponse, AuthTokenResponse


router = APIRouter(prefix="/auth", tags=["auth"])


_DEMO_USERS = {
    "student_880001": {
        "password": "student_880001",
        "role": "student",
        "student_id": 880001,
        "display_name": "Student 880001",
    },
    "student_880002": {
        "password": "student_880002",
        "role": "student",
        "student_id": 880002,
        "display_name": "Student 880002",
    },
    "student_880003": {
        "password": "student_880003",
        "role": "student",
        "student_id": 880003,
        "display_name": "Student 880003",
    },
    "counsellor_demo": {
        "password": "counsellor_demo",
        "role": "counsellor",
        "student_id": None,
        "display_name": "Counsellor Demo",
    },
    "admin_demo": {
        "password": "admin_demo",
        "role": "admin",
        "student_id": None,
        "display_name": "Admin Demo",
    },
}


@router.post("/login", response_model=AuthTokenResponse)
def login(payload: AuthLoginRequest) -> AuthTokenResponse:
    if not AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="Auth is disabled in this environment.")

    user = _DEMO_USERS.get(payload.username)
    if user is None or user["password"] != payload.password:
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    token = create_access_token(
        role=user["role"],
        subject=payload.username,
        student_id=user["student_id"],
        display_name=user["display_name"],
    )
    return AuthTokenResponse(
        access_token=token,
        token_type="bearer",
        role=user["role"],
        student_id=user["student_id"],
        display_name=user["display_name"],
    )


@router.get("/me", response_model=AuthMeResponse)
def get_current_user(auth: AuthContext = Depends(get_auth_context)) -> AuthMeResponse:
    return AuthMeResponse(
        role=auth.role,
        subject=auth.subject,
        student_id=auth.student_id,
        display_name=auth.display_name,
        auth_provider=auth.auth_provider,
    )
