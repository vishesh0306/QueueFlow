import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import APIError
from api.schemas import JoinQueueRequest, JoinQueueResponse, TokenStatusResponse
from core import queue_engine
from core.estimator import estimated_wait_seconds
from db.models import Clinic, Token
from db.session import get_db

router = APIRouter(tags=["patient"])


@router.post("/clinics/{clinic_id}/queue/join", response_model=JoinQueueResponse, status_code=201)
def join_queue(clinic_id: uuid.UUID, body: JoinQueueRequest, db: Session = Depends(get_db)):
    clinic = db.get(Clinic, clinic_id)
    if clinic is None:
        raise APIError(404, "CLINIC_NOT_FOUND", "No such clinic.")

    try:
        session = queue_engine.get_or_create_active_session(db, clinic_id)
        token = queue_engine.join_queue(db, session, body.patient_contact.as_column_value(), body.tier)
    except queue_engine.SessionClosedError:
        raise APIError(409, "SESSION_CLOSED", "This clinic's queue is not currently accepting new tokens.")
    except queue_engine.NoDoctorConfiguredError:
        raise APIError(409, "SESSION_CLOSED", "This clinic has no doctor configured yet.")

    position = queue_engine.position_in_queue(db, token)
    fee_due = clinic.priority_fee_paise if token.tier == "priority" else 0

    return JoinQueueResponse(
        token_id=token.id,
        display_number=token.display_number,
        tier=token.tier,
        position=position,
        estimated_wait_seconds=estimated_wait_seconds(db, session.id, position),
        fee_due_paise=fee_due,
    )


@router.delete("/queue/tokens/{token_id}", status_code=204)
def cancel_own_token(token_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        queue_engine.cancel_token(db, token_id)
    except queue_engine.InvalidTransitionError as exc:
        raise APIError(409, "INVALID_TRANSITION", str(exc))


@router.get("/queue/tokens/{token_id}/status", response_model=TokenStatusResponse)
def token_status(token_id: uuid.UUID, db: Session = Depends(get_db)):
    token = db.execute(select(Token).where(Token.id == token_id)).scalar_one_or_none()
    if token is None:
        raise APIError(404, "TOKEN_NOT_FOUND", "No such token.")

    if token.status == "waiting":
        position = queue_engine.position_in_queue(db, token)
        eta = estimated_wait_seconds(db, token.session_id, position)
    else:
        position = None
        eta = None

    return TokenStatusResponse(
        token_id=token.id, display_number=token.display_number, tier=token.tier, status=token.status,
        position=position, estimated_wait_seconds=eta,
    )
