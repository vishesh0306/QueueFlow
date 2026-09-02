import uuid

import bcrypt
from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.deps import APIError, JWTClaims, create_access_token, require_role
from api.schemas import (
    CallNextResponse,
    EmergencyOverrideRequest,
    LoginRequest,
    LoginResponse,
    MarkPaidRequest,
    NoShowResponse,
    QueueListResponse,
    QueueTokenSummary,
    SignupRequest,
    WalkInRequest,
)
from core import queue_engine, session_service, token_service
from core.exceptions import (
    InvalidTransitionError,
    NoDoctorConfiguredError,
    PatientAlreadyCalledError,
    QueueEmptyError,
    SessionClosedError,
    SessionNotActiveError,
)
from db.models import Clinic, QueueSession, StaffAccount, Token
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


def _resolve_session(db: Session, clinic_id: uuid.UUID) -> QueueSession:
    """Every queue-control action needs today's session, which needs a doctor account to
    exist first (see get_or_create_active_session). A freshly signed-up clinic has an
    admin but no doctor yet -- without this, every one of these routes would crash with
    an unhandled 500 the moment a new admin's dashboard loads."""
    try:
        return session_service.get_or_create_active_session(db, clinic_id)
    except NoDoctorConfiguredError:
        raise APIError(
            409, "NO_DOCTOR_CONFIGURED",
            "This clinic has no doctor account yet. Add one under Admin > Staff before running the queue.",
        )


@router.post("/staff/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    staff = db.execute(
        select(StaffAccount).where(StaffAccount.contact == body.contact)
    ).scalar_one_or_none()
    if staff is None or not bcrypt.checkpw(body.password.encode(), staff.password_hash.encode()):
        raise APIError(401, "INVALID_CREDENTIALS", "Contact or password is incorrect.")

    token = create_access_token(staff.id, staff.clinic_id, staff.role)
    return LoginResponse(access_token=token, role=staff.role, clinic_id=staff.clinic_id)


@router.post("/staff/signup", response_model=LoginResponse, status_code=201)
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    """Creates a brand-new clinic plus its first staff account (admin), and logs them
    straight in. This is the only way a clinic comes into existence in v1 -- every other
    admin/staff-management action requires an already-authenticated admin, so this has
    to be the one unauthenticated bootstrap path."""
    clinic = Clinic(name=body.clinic_name)
    db.add(clinic)
    db.flush()

    admin = StaffAccount(
        clinic_id=clinic.id,
        name=body.admin_name,
        role="admin",
        contact=body.admin_contact,
        password_hash=bcrypt.hashpw(body.admin_password.encode(), bcrypt.gensalt()).decode(),
    )
    db.add(admin)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise APIError(409, "CONTACT_TAKEN", "That contact is already registered to a staff account.")

    token = create_access_token(admin.id, clinic.id, admin.role)
    return LoginResponse(access_token=token, role=admin.role, clinic_id=clinic.id)


@router.get("/staff/queue", response_model=QueueListResponse)
def list_queue(db: Session = Depends(get_db), claims: JWTClaims = Depends(require_role(*_STAFF_ROLES))):
    session = _resolve_session(db, claims.clinic_id)

    tokens = db.execute(
        select(Token)
        .where(Token.session_id == session.id, Token.status.in_(("waiting", "called")))
        .order_by(Token.sequence_no)
    ).scalars().all()

    def _summary(t: Token) -> QueueTokenSummary:
        return QueueTokenSummary(
            token_id=t.id, display_number=t.display_number, tier=t.tier, status=t.status,
            patient_contact=t.patient_contact, emergency_override=t.emergency_override,
            joined_at=t.joined_at, called_at=t.called_at,
        )

    return QueueListResponse(
        session_id=session.id,
        session_status=session.status,
        called=[_summary(t) for t in tokens if t.status == "called"],
        waiting=[_summary(t) for t in tokens if t.status == "waiting"],
    )


@router.post("/staff/queue/call-next", response_model=CallNextResponse)
async def call_next(db: Session = Depends(get_db), claims: JWTClaims = Depends(require_role(*_STAFF_ROLES))):
    session = await run_in_threadpool(_resolve_session, db, claims.clinic_id)
    try:
        token = await run_in_threadpool(queue_engine.call_next, db, session.id)
    except QueueEmptyError:
        raise APIError(409, "QUEUE_EMPTY", "No patients are currently waiting.")
    except SessionNotActiveError as exc:
        raise APIError(409, "QUEUE_PAUSED", f"The queue is currently {exc.status}, not accepting call-next.")
    except PatientAlreadyCalledError:
        raise APIError(409, "PATIENT_ALREADY_CALLED", "A patient is already called; resolve them before calling next.")

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
async def mark_served(token_id: uuid.UUID, db: Session = Depends(get_db),
                       claims: JWTClaims = Depends(require_role(*_STAFF_ROLES))):
    _verify_token_in_clinic(db, token_id, claims.clinic_id)
    try:
        token = await run_in_threadpool(token_service.mark_served, db, token_id)
    except InvalidTransitionError as exc:
        raise APIError(409, "INVALID_TRANSITION", str(exc))

    # Not just for the staff dashboard's own list — this is the only signal a patient's
    # own status page gets that their visit is over (it has no other reason to re-fetch).
    await manager.broadcast_queue_updated(claims.clinic_id, token.session_id)

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
    session = _resolve_session(db, claims.clinic_id)
    try:
        token = token_service.join_queue(
            db, session, body.patient_contact.as_column_value(), body.tier, body.patient_email
        )
    except SessionClosedError:
        raise APIError(409, "SESSION_CLOSED", "This clinic's queue is not currently accepting new tokens.")

    return {"token_id": token.id, "display_number": token.display_number, "tier": token.tier, "status": token.status}


@router.post("/staff/queue/emergency-override", status_code=201)
def emergency_override(body: EmergencyOverrideRequest, db: Session = Depends(get_db),
                        claims: JWTClaims = Depends(require_role(*_OVERRIDE_ROLES))):
    session = _resolve_session(db, claims.clinic_id)
    token = queue_engine.trigger_emergency_override(db, session.id, body.patient_contact.as_column_value())
    return {"token_id": token.id, "display_number": token.display_number, "emergency_override": token.emergency_override}


@router.post("/staff/queue/pause")
async def pause(db: Session = Depends(get_db), claims: JWTClaims = Depends(require_role(*_OVERRIDE_ROLES))):
    session = await run_in_threadpool(_resolve_session, db, claims.clinic_id)
    session = await run_in_threadpool(session_service.pause_session, db, session.id)
    await manager.broadcast_queue_updated(claims.clinic_id, session.id)
    return {"session_id": session.id, "status": session.status}


@router.post("/staff/queue/resume")
async def resume(db: Session = Depends(get_db), claims: JWTClaims = Depends(require_role(*_OVERRIDE_ROLES))):
    session = await run_in_threadpool(_resolve_session, db, claims.clinic_id)
    session = await run_in_threadpool(session_service.resume_session, db, session.id)
    await manager.broadcast_queue_updated(claims.clinic_id, session.id)
    return {"session_id": session.id, "status": session.status}
