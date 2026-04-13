from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.auth import AuthContext, require_roles, require_same_student_or_roles
from src.api.schemas import StudentProfileResponse, StudentProfileUpsertRequest
from src.db.database import get_db
from src.db.repository import EventRepository


router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.put("/{student_id}", response_model=StudentProfileResponse)
def upsert_student_profile(
    student_id: int,
    payload: StudentProfileUpsertRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_roles("admin", "system")),
) -> StudentProfileResponse:
    if student_id != payload.student_id:
        raise HTTPException(status_code=400, detail="Path student_id must match payload student_id.")

    repository = EventRepository(db)
    profile = repository.upsert_student_profile(payload.model_dump())
    print(
        f"[profile] upserted student_id={profile.student_id} "
        f"gender={profile.gender} education={profile.highest_education}"
    )
    return StudentProfileResponse(
        student_id=profile.student_id,
        student_email=profile.student_email,
        faculty_name=profile.faculty_name,
        faculty_email=profile.faculty_email,
        counsellor_name=getattr(profile, "counsellor_name", None),
        counsellor_email=getattr(profile, "counsellor_email", None),
        parent_name=profile.parent_name,
        parent_relationship=profile.parent_relationship,
        parent_email=profile.parent_email,
        parent_phone=profile.parent_phone,
        preferred_guardian_channel=profile.preferred_guardian_channel,
        guardian_contact_enabled=bool(profile.guardian_contact_enabled),
        external_student_ref=getattr(profile, "external_student_ref", None),
        profile_context=getattr(profile, "profile_context", None),
        gender=profile.gender,
        highest_education=profile.highest_education,
        age_band=profile.age_band,
        disability_status=profile.disability_status,
        num_previous_attempts=float(profile.num_previous_attempts),
    )


@router.get("/{student_id}", response_model=StudentProfileResponse)
def get_student_profile(
    student_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_same_student_or_roles("counsellor", "admin", "system")),
) -> StudentProfileResponse:
    repository = EventRepository(db)
    profile = repository.get_student_profile(student_id)

    if profile is None:
        print(f"[profile] not_found student_id={student_id}")
        raise HTTPException(status_code=404, detail="Student profile not found.")

    print(f"[profile] fetched student_id={profile.student_id}")

    return StudentProfileResponse(
        student_id=profile.student_id,
        student_email=profile.student_email,
        faculty_name=profile.faculty_name,
        faculty_email=profile.faculty_email,
        counsellor_name=getattr(profile, "counsellor_name", None),
        counsellor_email=getattr(profile, "counsellor_email", None),
        parent_name=profile.parent_name,
        parent_relationship=profile.parent_relationship,
        parent_email=profile.parent_email,
        parent_phone=profile.parent_phone,
        preferred_guardian_channel=profile.preferred_guardian_channel,
        guardian_contact_enabled=bool(profile.guardian_contact_enabled),
        external_student_ref=getattr(profile, "external_student_ref", None),
        profile_context=getattr(profile, "profile_context", None),
        gender=profile.gender,
        highest_education=profile.highest_education,
        age_band=profile.age_band,
        disability_status=profile.disability_status,
        num_previous_attempts=float(profile.num_previous_attempts),
    )
