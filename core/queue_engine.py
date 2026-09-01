import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from core.interleave import next_subqueue, parse_ratio
from db.models import Payment, QueueSession, ServiceTimeSample, StaffAccount, Token


class QueueEmptyError(Exception):
    def __init__(self, session_id: uuid.UUID):
        super().__init__(f"No waiting tokens in session {session_id}")
        self.session_id = session_id


class InvalidTransitionError(Exception):
    pass


class SessionClosedError(Exception):
    def __init__(self, clinic_id: uuid.UUID):
        super().__init__(f"Clinic {clinic_id}'s queue is not currently accepting new tokens")
        self.clinic_id = clinic_id


class NoDoctorConfiguredError(Exception):
    def __init__(self, clinic_id: uuid.UUID):
        super().__init__(f"Clinic {clinic_id} has no doctor account configured")
        self.clinic_id = clinic_id


def _now():
    return datetime.now(timezone.utc)


def _next_waiting_token(db: Session, session_id: uuid.UUID, *, tier: str | None = None,
                         emergency_override: bool | None = None) -> Token | None:
    stmt = select(Token).where(Token.session_id == session_id, Token.status == "waiting")
    if tier is not None:
        stmt = stmt.where(Token.tier == tier)
    if emergency_override is not None:
        stmt = stmt.where(Token.emergency_override == emergency_override)
    stmt = stmt.order_by(Token.sequence_no).with_for_update(skip_locked=True).limit(1)
    return db.execute(stmt).scalars().first()


def _sequence_after(db: Session, partner: Token) -> int:
    """Make room for a value immediately after `partner` within its session+tier waiting list."""
    db.execute(
        update(Token)
        .where(
            Token.session_id == partner.session_id,
            Token.tier == partner.tier,
            Token.status == "waiting",
            Token.sequence_no > partner.sequence_no,
        )
        .values(sequence_no=Token.sequence_no + 1)
    )
    return partner.sequence_no + 1


def _sequence_for_back_of_queue(db: Session) -> int:
    """A fresh value from the tokens.sequence_no identity sequence — guaranteed past every existing row."""
    seq_name = db.execute(text("SELECT pg_get_serial_sequence('tokens', 'sequence_no')")).scalar_one()
    return db.execute(text(f"SELECT nextval('{seq_name}')")).scalar_one()


def call_next(db: Session, session_id: uuid.UUID) -> Token:
    session = db.execute(
        select(QueueSession).where(QueueSession.id == session_id).with_for_update()
    ).scalar_one()

    # 1. Emergency override always wins, regardless of interleave state.
    token = _next_waiting_token(db, session_id, emergency_override=True)

    # 2. Otherwise pick the sub-queue the interleave policy points to.
    if token is None:
        ratio = parse_ratio(session.clinic.standard_priority_ratio)
        preferred_tier = next_subqueue(session.call_counter, ratio)
        token = _next_waiting_token(db, session_id, tier=preferred_tier)

        # 3. Fallback: preferred sub-queue empty, pull from the other one instead
        #    of stalling the whole queue.
        if token is None:
            other_tier = "standard" if preferred_tier == "priority" else "priority"
            token = _next_waiting_token(db, session_id, tier=other_tier)

    if token is None:
        raise QueueEmptyError(session_id)

    token.status = "called"
    token.called_at = _now()
    session.call_counter += 1
    db.commit()
    return token


def handle_no_show(db: Session, token_id: uuid.UUID) -> dict:
    token = db.execute(select(Token).where(Token.id == token_id).with_for_update()).scalar_one()

    if token.status != "called":
        raise InvalidTransitionError(f"Token {token_id} is not in 'called' state")

    if not token.swap_used:
        partner = _next_waiting_token(db, token.session_id, tier=token.tier)

        if partner is not None:
            token.status = "waiting"
            token.swap_used = True
            token.sequence_no = _sequence_after(db, partner)
            partner.status = "called"
            partner.called_at = _now()
            db.commit()
            return {"action": "swapped", "new_called_token_id": partner.id}

    # No swap partner available, or swap already used once for this token —
    # cap reached, send to the back rather than cascading further.
    token.status = "waiting"
    token.sequence_no = _sequence_for_back_of_queue(db)
    db.commit()
    return {"action": "requeued", "new_called_token_id": None}


def trigger_emergency_override(db: Session, session_id: uuid.UUID, patient_contact: str) -> Token:
    """Doctor/admin-only: insert a walk-in that bypasses tier/position entirely (HLD §8)."""
    token = Token(
        session_id=session_id,
        patient_contact=patient_contact,
        tier="standard",
        emergency_override=True,
        status="waiting",
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


def get_or_create_active_session(db: Session, clinic_id: uuid.UUID) -> QueueSession:
    """Resolve today's queue session for a clinic, creating it on first use (v1: single doctor, one session/day)."""
    session = db.execute(
        select(QueueSession).where(
            QueueSession.clinic_id == clinic_id,
            QueueSession.session_date == date.today(),
        )
    ).scalars().first()
    if session is not None:
        return session

    doctor = db.execute(
        select(StaffAccount).where(StaffAccount.clinic_id == clinic_id, StaffAccount.role == "doctor")
    ).scalars().first()
    if doctor is None:
        raise NoDoctorConfiguredError(clinic_id)

    session = QueueSession(clinic_id=clinic_id, doctor_id=doctor.id, session_date=date.today())
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def join_queue(db: Session, session: QueueSession, patient_contact: str, tier: str) -> Token:
    if session.status == "closed":
        raise SessionClosedError(session.clinic_id)
    token = Token(session_id=session.id, patient_contact=patient_contact, tier=tier, status="waiting")
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
    token.served_at = _now()
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
    payment.collected_at = _now()
    db.commit()
    db.refresh(payment)
    return payment


def pause_session(db: Session, session_id: uuid.UUID) -> QueueSession:
    session = db.execute(select(QueueSession).where(QueueSession.id == session_id).with_for_update()).scalar_one()
    session.status = "paused"
    db.commit()
    return session


def resume_session(db: Session, session_id: uuid.UUID) -> QueueSession:
    session = db.execute(select(QueueSession).where(QueueSession.id == session_id).with_for_update()).scalar_one()
    session.status = "active"
    db.commit()
    return session


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
