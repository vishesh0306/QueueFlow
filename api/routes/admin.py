import uuid

import bcrypt
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import APIError, JWTClaims, require_role
from api.schemas import (
    ClinicConfigResponse,
    ClinicConfigUpdateRequest,
    StaffCreateRequest,
    StaffResponse,
)
from db.models import Clinic, StaffAccount
from db.session import get_db

router = APIRouter(tags=["admin"])


@router.get("/admin/clinics/{clinic_id}/config", response_model=ClinicConfigResponse)
def get_clinic_config(clinic_id: uuid.UUID, db: Session = Depends(get_db),
                       claims: JWTClaims = Depends(require_role("admin"))):
    clinic = db.get(Clinic, clinic_id)
    if clinic is None:
        raise APIError(404, "CLINIC_NOT_FOUND", "No such clinic.")
    return ClinicConfigResponse(
        clinic_id=clinic.id, name=clinic.name, priority_fee_paise=clinic.priority_fee_paise,
        standard_priority_ratio=clinic.standard_priority_ratio, notify_lead_count=clinic.notify_lead_count,
        timezone=clinic.timezone,
    )


@router.put("/admin/clinics/{clinic_id}/config", response_model=ClinicConfigResponse)
def update_clinic_config(clinic_id: uuid.UUID, body: ClinicConfigUpdateRequest, db: Session = Depends(get_db),
                          claims: JWTClaims = Depends(require_role("admin"))):
    clinic = db.get(Clinic, clinic_id)
    if clinic is None:
        raise APIError(404, "CLINIC_NOT_FOUND", "No such clinic.")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(clinic, field, value)
    db.commit()
    db.refresh(clinic)

    return ClinicConfigResponse(
        clinic_id=clinic.id, name=clinic.name, priority_fee_paise=clinic.priority_fee_paise,
        standard_priority_ratio=clinic.standard_priority_ratio, notify_lead_count=clinic.notify_lead_count,
        timezone=clinic.timezone,
    )


@router.get("/admin/staff", response_model=list[StaffResponse])
def list_staff(db: Session = Depends(get_db), claims: JWTClaims = Depends(require_role("admin"))):
    staff = db.execute(
        select(StaffAccount).where(StaffAccount.clinic_id == claims.clinic_id)
    ).scalars().all()
    return [StaffResponse(id=s.id, name=s.name, role=s.role, contact=s.contact) for s in staff]


@router.post("/admin/staff", response_model=StaffResponse, status_code=201)
def create_staff(body: StaffCreateRequest, db: Session = Depends(get_db),
                  claims: JWTClaims = Depends(require_role("admin"))):
    password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    staff = StaffAccount(
        clinic_id=claims.clinic_id, name=body.name, role=body.role,
        contact=body.contact, password_hash=password_hash,
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return StaffResponse(id=staff.id, name=staff.name, role=staff.role, contact=staff.contact)


# GET /admin/analytics/daily is deliberately not built here — it belongs to the
# stats phase (queueflow-workflow.md, Phase 6), which is what actually gives
# no-show tracking a persisted representation to report on. Wiring up a
# same-looking-but-wrong endpoint now would just mean redoing it later.
