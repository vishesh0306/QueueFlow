import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.clock import utcnow
from core.exceptions import InvalidTransitionError, SessionClosedError
from core.session_service import next_display_number
from db.models import Payment, QueueSession, ServiceTimeSample, Token


def join_queue(db: Session, session: QueueSession, patient_contact: str, tier: str,
               patient_email: str | None = None) -> Token:
    locked_session = db.execute(
        select(QueueSession).where(QueueSession.id == session.id).with_for_update()
    ).scalar_one()
    if locked_session.status == "closed":
        raise SessionClosedError(locked_session.clinic_id)

    token = Token(
        session_id=locked_session.id,
        patient_contact=patient_contact,
        patient_email=patient_email,
        tier=tier,
        status="waiting",
        display_number=next_display_number(locked_session, tier=tier, emergency=False),
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


def cancel_token(db: Session, token_id: uuid.UUID) -> Token:
    token = db.execute(select(Token).where(Token.id == token_id).with_for_update()).scalar_one()
    if token.status not in ("waiting", "called"):
        raise InvalidTransitionError(f"Token {token_id} cannot be cancelled from status '{token.status}'")
    token.status = "cancelled"
    db.commit()
    return token


def mark_served(db: Session, token_id: uuid.UUID) -> Token:
    token = db.execute(select(Token).where(Token.id == token_id).with_for_update()).scalar_one()
    if token.status != "called":
        raise InvalidTransitionError(f"Token {token_id} is not in 'called' state")
    token.status = "served"
    token.served_at = utcnow()
    db.add(ServiceTimeSample(
        session_id=token.session_id,
        token_id=token.id,
        duration_seconds=max(1, int((token.served_at - token.called_at).total_seconds())),
    ))
    db.commit()
    return token


def mark_paid(db: Session, token_id: uuid.UUID, collected_by: uuid.UUID, fee_amount_paise: int) -> Payment:
    payment = db.get(Payment, token_id)
    if payment is None:
        payment = Payment(token_id=token_id, fee_amount_paise=fee_amount_paise)
        db.add(payment)
    payment.paid = True
    payment.collected_by = collected_by
    payment.collected_at = utcnow()
    db.commit()
    db.refresh(payment)
    return payment


def position_in_queue(db: Session, token: Token) -> int:
    """1-indexed position among waiting tokens of the same tier, ordered by join order."""
    ahead = db.execute(
        select(func.count()).select_from(Token).where(
            Token.session_id == token.session_id,
            Token.tier == token.tier,
            Token.status == "waiting",
            Token.sequence_no < token.sequence_no,
        )
    ).scalar_one()
    return ahead + 1
