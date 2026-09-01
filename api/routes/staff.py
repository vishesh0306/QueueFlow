import uuid

import bcrypt
from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import APIError, JWTClaims, create_access_token, require_role
from api.schemas import (
    CallNextResponse,
    EmergencyOverrideRequest,
    LoginRequest,
    LoginResponse,
    MarkPaidRequest,
    NoShowResponse,
    WalkInRequest,
)
from core import queue_engine, session_service, token_service
from core.exceptions import InvalidTransitionError, QueueEmptyError, SessionClosedError
from db.models import QueueSession, StaffAccount, Token
from db.session import get_db
from ws.gateway import manager

router = APIRouter(tags=["staff"])

_STAFF_ROLES = ("receptionist", "doctor", "admin")
_OVERRIDE_ROLES = ("doctor", "admin")


def _verify_token_in_clinic(db: Session, token_id: uuid.UUID, clinic_id: uuid.UUID) -> None:
    row = db.execute(
        select(Token.id)
        .join(QueueSession, Token.session_id == QueueSession.id)
        .where(Token.id == token_id, QueueSession.clinic_id == clinic_id)
    ).scalar_one_or_none()
    if row is None:
        raise APIError(404, "TOKEN_NOT_FOUND", "No such token.")


@router.post("/staff/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    staff = db.execute(
        select(StaffAccount).where(StaffAccount.contact == body.contact)
    ).scalar_one_or_none()
    if staff is None or not bcrypt.checkpw(body.password.encode(), staff.password_hash.encode()):
        raise APIError(401, "INVALID_CREDENTIALS", "Contact or password is incorrect.")

    token = create_access_token(staff.id, staff.clinic_id, staff.role)
    return LoginResponse(access_token=token, role=staff.role, clinic_id=staff.clinic_id)


@router.post("/staff/queue/call-next", response_model=CallNextResponse)
async def call_next(db: Session = Depends(get_db), claims: JWTClaims = Depends(require_role(*_STAFF_ROLES))):
    session = await run_in_threadpool(session_service.get_or_create_active_session, db, claims.clinic_id)
    try:
        token = await run_in_threadpool(queue_engine.call_next, db, session.id)
    except QueueEmptyError:
        raise APIError(409, "QUEUE_EMPTY", "No patients are currently waiting.")

    await manager.broadcast_queue_updated(claims.clinic_id, session.id)

    return CallNextResponse(
        token_id=token.id, display_number=token.display_number, tier=token.tier,
        patient_contact=token.patient_contact, called_at=token.called_at,
    )


@router.post("/staff/queue/tokens/{token_id}/no-show", response_model=NoShowResponse)
async def no_show(token_id: uuid.UUID, db: Session = Depends(get_db),
                   claims: JWTClaims = Depends(require_role(*_STAFF_ROLES))):
    _verify_token_in_clinic(db, token_id, claims.clinic_id)
    try:
        result = await run_in_threadpool(queue_engine.handle_no_show, db, token_id)
    except InvalidTransitionError as exc:
        raise APIError(409, "INVALID_TRANSITION", str(exc))

    session_id = db.execute(select(Token.session_id).where(Token.id == token_id)).scalar_one()
    await manager.broadcast_queue_updated(claims.clinic_id, session_id)

    return NoShowResponse(token_id=token_id, **result)


@router.post("/staff/queue/tokens/{token_id}/mark-served")
def mark_served(token_id: uuid.UUID, db: Session = Depends(get_db),
                 claims: JWTClaims = Depends(require_role(*_STAFF_ROLES))):
    _verify_token_in_clinic(db, token_id, claims.clinic_id)
    try:
        token = token_service.mark_served(db, token_id)
    except InvalidTransitionError as exc:
        raise APIError(409, "INVALID_TRANSITION", str(exc))

    return {"token_id": token.id, "status": token.status, "served_at": token.served_at}


@router.post("/staff/queue/tokens/{token_id}/mark-paid")
def mark_paid(token_id: uuid.UUID, body: MarkPaidRequest, db: Session = Depends(get_db),
              claims: JWTClaims = Depends(require_role(*_STAFF_ROLES))):
    _verify_token_in_clinic(db, token_id, claims.clinic_id)
    payment = token_service.mark_paid(db, token_id, claims.staff_id, body.fee_amount_paise)
    return {"token_id": token_id, "paid": payment.paid, "fee_amount_paise": payment.fee_amount_paise}


@router.post("/staff/queue/walk-in", status_code=201)
def walk_in(body: WalkInRequest, db: Session = Depends(get_db),
            claims: JWTClaims = Depends(require_role(*_STAFF_ROLES))):
    session = session_service.get_or_create_active_session(db, claims.clinic_id)
    try:
        token = token_service.join_queue(db, session, body.patient_contact.as_column_value(), body.tier)
    except SessionClosedError:
        raise APIError(409, "SESSION_CLOSED", "This clinic's queue is not currently accepting new tokens.")

    return {"token_id": token.id, "display_number": token.display_number, "tier": token.tier, "status": token.status}


@router.post("/staff/queue/emergency-override", status_code=201)
def emergency_override(body: EmergencyOverrideRequest, db: Session = Depends(get_db),
                        claims: JWTClaims = Depends(require_role(*_OVERRIDE_ROLES))):
    session = session_service.get_or_create_active_session(db, claims.clinic_id)
    token = queue_engine.trigger_emergency_override(db, session.id, body.patient_contact.as_column_value())
    return {"token_id": token.id, "display_number": token.display_number, "emergency_override": token.emergency_override}


@router.post("/staff/queue/pause")
def pause(db: Session = Depends(get_db), claims: JWTClaims = Depends(require_role(*_OVERRIDE_ROLES))):
    session = session_service.get_or_create_active_session(db, claims.clinic_id)
    session = session_service.pause_session(db, session.id)
    return {"session_id": session.id, "status": session.status}


@router.post("/staff/queue/resume")
def resume(db: Session = Depends(get_db), claims: JWTClaims = Depends(require_role(*_OVERRIDE_ROLES))):
    session = session_service.get_or_create_active_session(db, claims.clinic_id)
    session = session_service.resume_session(db, session.id)
    return {"session_id": session.id, "status": session.status}
