import uuid

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from core.clock import utcnow
from core.exceptions import (
    InvalidTransitionError,
    PatientAlreadyCalledError,
    QueueEmptyError,
    SessionNotActiveError,
)
from core.interleave import next_subqueue, parse_ratio
from core.session_service import next_display_number
from db.models import QueueSession, Token
from notifications.service import enqueue_notification


def _notify_your_turn(token: Token, clinic_name: str) -> None:
    enqueue_notification({
        "token_id": str(token.id),
        "event": "your_turn",
        "patient_contact": token.patient_contact,
        "patient_email": token.patient_email,
        "clinic_name": clinic_name,
        "display_number": token.display_number,
    })


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
    """Make room for a value immediately after `partner`.

    sequence_no is a single global ordering key shared by the whole tokens table, not
    one scoped per tier or per status -- so the shift must consider every row in the
    session, not just other currently-waiting same-tier ones. Restricting it to
    tier+waiting (as this used to) left already-called/served rows invisible to the
    shift: a later swap could silently reassign a value a served row already froze
    on, producing duplicate sequence_no values that corrupted no live ordering query
    directly (those all filter by tier already) but broke the column's invariant and
    could still tie-break unpredictably between rows that do share a tier.

    Shifting the whole session's rows uniformly by +1 preserves every row's relative
    order to every other row, called/served/cancelled included, so this is always
    safe -- it just costs a few more touched rows than the old narrower shift.
    """
    db.execute(
        update(Token)
        .where(
            Token.session_id == partner.session_id,
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

    # v1 assumes a single doctor: at most one token can be 'called' at a time. Without
    # this, a no-show swap's silently-promoted partner (see handle_no_show) could be
    # abandoned forever by a call-next that ignores it and calls someone else entirely.
    already_called = db.execute(
        select(Token).where(Token.session_id == session_id, Token.status == "called")
    ).scalars().first()
    if already_called is not None:
        raise PatientAlreadyCalledError(session_id, already_called.id)

    # 1. Emergency override always wins, regardless of interleave state OR pause —
    #    a genuine urgent case shouldn't have to wait on an administrative pause.
    token = _next_waiting_token(db, session_id, emergency_override=True)
    is_emergency_pick = token is not None

    # 2. Otherwise pick the sub-queue the interleave policy points to — but only if
    #    the session is actually active; a pause should stop ordinary calling.
    if token is None:
        if session.status != "active":
            raise SessionNotActiveError(session_id, session.status)
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
    token.called_at = utcnow()
    # Emergency picks never consult call_counter to begin with (HLD: "processed
    # immediately regardless of the interleave counter") -- advancing it for them
    # anyway would silently burn real standard/priority patients' fair-share slots
    # on calls that were never actually decided by the interleave in the first place.
    if not is_emergency_pick:
        session.call_counter += 1
    db.commit()
    _notify_your_turn(token, session.clinic.name)
    return token


def handle_no_show(db: Session, token_id: uuid.UUID) -> dict:
    token = db.execute(select(Token).where(Token.id == token_id).with_for_update()).scalar_one()

    if token.status != "called":
        raise InvalidTransitionError(f"Token {token_id} is not in 'called' state")

    session = db.execute(
        select(QueueSession).where(QueueSession.id == token.session_id).with_for_update()
    ).scalar_one()
    session.no_show_count += 1

    if not token.swap_used:
        partner = _next_waiting_token(db, token.session_id, tier=token.tier)

        if partner is not None:
            token.status = "waiting"
            token.swap_used = True
            token.sequence_no = _sequence_after(db, partner)
            partner.status = "called"
            partner.called_at = utcnow()
            db.commit()
            _notify_your_turn(partner, partner.session.clinic.name)
            return {"action": "swapped", "new_called_token_id": partner.id}

    # No swap partner available, or swap already used once for this token —
    # cap reached, send to the back rather than cascading further.
    token.status = "waiting"
    token.sequence_no = _sequence_for_back_of_queue(db)
    db.commit()
    return {"action": "requeued", "new_called_token_id": None}


def trigger_emergency_override(db: Session, session_id: uuid.UUID, patient_contact: str) -> Token:
    """Doctor/admin-only: insert a walk-in that bypasses tier/position entirely (HLD §8)."""
    session = db.execute(select(QueueSession).where(QueueSession.id == session_id).with_for_update()).scalar_one()
    token = Token(
        session_id=session_id,
        patient_contact=patient_contact,
        tier="standard",
        emergency_override=True,
        status="waiting",
        display_number=next_display_number(session, tier="standard", emergency=True),
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token
