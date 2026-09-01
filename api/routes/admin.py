import uuid

import bcrypt
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import APIError, JWTClaims, require_role
from api.schemas import (
    ClinicConfigResponse,
    ClinicConfigUpdateRequest,
    DailyAnalyticsResponse,
    StaffCreateRequest,
    StaffResponse,
)
from core import session_service
from db.models import Clinic, ServiceTimeSample, StaffAccount, Token
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


@router.get("/admin/analytics/daily", response_model=DailyAnalyticsResponse)
def daily_analytics(db: Session = Depends(get_db),
                     claims: JWTClaims = Depends(require_role("doctor", "admin"))):
    session = session_service.get_or_create_active_session(db, claims.clinic_id)

    served_count = db.execute(
        select(func.count()).select_from(Token).where(Token.session_id == session.id, Token.status == "served")
    ).scalar_one()
    average_service_seconds = db.execute(
        select(func.avg(ServiceTimeSample.duration_seconds)).where(ServiceTimeSample.session_id == session.id)
    ).scalar_one()
    average_wait_seconds = db.execute(
        select(func.avg(func.extract("epoch", Token.called_at - Token.joined_at))).where(
            Token.session_id == session.id, Token.called_at.is_not(None),
        )
    ).scalar_one()

    total_calls = session.call_counter
    no_show_rate = (session.no_show_count / total_calls) if total_calls > 0 else None

    return DailyAnalyticsResponse(
        session_date=str(session.session_date),
        served_count=served_count,
        average_wait_seconds=average_wait_seconds,
        average_service_seconds=average_service_seconds,
        no_show_count=session.no_show_count,
        no_show_rate=no_show_rate,
    )
