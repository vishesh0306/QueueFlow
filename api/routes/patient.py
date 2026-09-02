import uuid

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import APIError
from api.schemas import JoinQueueRequest, JoinQueueResponse, TokenStatusResponse
from core import session_service, token_service
from core.estimator import estimated_wait_seconds
from core.exceptions import DuplicateBookingError, InvalidTransitionError, NoDoctorConfiguredError, SessionClosedError
from db.models import Clinic, QueueSession, Token
from db.session import get_db
from ws.gateway import manager

router = APIRouter(tags=["patient"])


@router.post("/clinics/{clinic_id}/queue/join", response_model=JoinQueueResponse, status_code=201)
async def join_queue(clinic_id: uuid.UUID, body: JoinQueueRequest, db: Session = Depends(get_db)):
    clinic = db.get(Clinic, clinic_id)
    if clinic is None:
        raise APIError(404, "CLINIC_NOT_FOUND", "No such clinic.")

    try:
        session = await run_in_threadpool(session_service.get_or_create_active_session, db, clinic_id)
        token = await run_in_threadpool(
            token_service.join_queue, db, session, body.patient_contact.as_column_value(), body.tier,
            body.patient_email,
        )
    except SessionClosedError:
        raise APIError(409, "SESSION_CLOSED", "This clinic's queue is not currently accepting new tokens.")
    except NoDoctorConfiguredError:
        raise APIError(409, "SESSION_CLOSED", "This clinic has no doctor configured yet.")
    except DuplicateBookingError:
        raise APIError(409, "ALREADY_IN_QUEUE", "This contact already has an active token in today's queue.")

    position = token_service.position_in_queue(db, token)
    fee_due = token_service.fee_due_for(clinic, token.tier, token.emergency_override)

    await manager.broadcast_queue_updated(clinic_id, session.id)

    return JoinQueueResponse(
        token_id=token.id,
        display_number=token.display_number,
        tier=token.tier,
        position=position,
        estimated_wait_seconds=estimated_wait_seconds(db, session.id, position),
        fee_due_paise=fee_due,
        session_status=session.status,
    )


@router.delete("/queue/tokens/{token_id}", status_code=204)
async def cancel_own_token(token_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        token = await run_in_threadpool(token_service.cancel_token, db, token_id)
    except InvalidTransitionError as exc:
        raise APIError(409, "INVALID_TRANSITION", str(exc))

    session = db.get(QueueSession, token.session_id)
    await manager.broadcast_queue_updated(session.clinic_id, session.id)


@router.post("/queue/tokens/{token_id}/upgrade-to-priority")
async def upgrade_to_priority(token_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        token = await run_in_threadpool(token_service.upgrade_to_priority, db, token_id)
    except InvalidTransitionError as exc:
        raise APIError(409, "INVALID_TRANSITION", str(exc))

    session = db.get(QueueSession, token.session_id)
    clinic = db.get(Clinic, session.clinic_id)
    position = token_service.position_in_queue(db, token)

    await manager.broadcast_queue_updated(session.clinic_id, session.id)

    return {
        "token_id": token.id,
        "tier": token.tier,
        "position": position,
        "fee_due_paise": token_service.fee_due_for(clinic, token.tier, token.emergency_override),
    }


@router.get("/queue/tokens/{token_id}/status", response_model=TokenStatusResponse)
def token_status(token_id: uuid.UUID, db: Session = Depends(get_db)):
    token = db.execute(select(Token).where(Token.id == token_id)).scalar_one_or_none()
    if token is None:
        raise APIError(404, "TOKEN_NOT_FOUND", "No such token.")

    if token.status == "waiting":
        position = token_service.position_in_queue(db, token)
        eta = estimated_wait_seconds(db, token.session_id, position)
    else:
        position = None
        eta = None

    session = db.get(QueueSession, token.session_id)

    return TokenStatusResponse(
        token_id=token.id, display_number=token.display_number, tier=token.tier, status=token.status,
        position=position, estimated_wait_seconds=eta, session_status=session.status,
    )
