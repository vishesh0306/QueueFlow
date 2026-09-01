import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.exceptions import NoDoctorConfiguredError
from db.models import QueueSession, StaffAccount


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


def next_display_number(session: QueueSession, *, tier: str, emergency: bool) -> str:
    """Session+tier-scoped, human-friendly counter (e.g. "S-14", "P-3", "E-1") — cosmetic only,
    doesn't touch sequence_no or queue ordering. Caller must hold a lock on `session`."""
    if emergency:
        session.emergency_token_counter += 1
        return f"E-{session.emergency_token_counter}"
    if tier == "priority":
        session.priority_token_counter += 1
        return f"P-{session.priority_token_counter}"
    session.standard_token_counter += 1
    return f"S-{session.standard_token_counter}"
