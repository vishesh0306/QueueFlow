from datetime import date

import pytest

from core.exceptions import DuplicateBookingError
from core.token_service import cancel_token, join_queue, mark_served
from db.models import Clinic, QueueSession, StaffAccount


def _make_clinic_session(db):
    clinic = Clinic(name="Token Service Test Clinic")
    db.add(clinic)
    db.flush()
    doctor = StaffAccount(
        clinic_id=clinic.id, name="Dr. Test", role="doctor", contact="doc@tokenservice.test", password_hash="x",
    )
    db.add(doctor)
    db.flush()
    session = QueueSession(clinic_id=clinic.id, doctor_id=doctor.id, session_date=date.today())
    db.add(session)
    db.commit()
    return session


def test_join_queue_rejects_a_second_active_booking_from_the_same_contact(db):
    session = _make_clinic_session(db)
    join_queue(db, session, "telegram:12345", "standard")

    with pytest.raises(DuplicateBookingError):
        join_queue(db, session, "telegram:12345", "standard")


def test_join_queue_allows_rejoining_after_the_first_token_is_resolved(db):
    """Duplicate detection only blocks an ACTIVE second booking -- once the first one
    is served/cancelled, the same contact can legitimately join again (a follow-up
    visit, or the same patient queueing for a second time that day)."""
    session = _make_clinic_session(db)
    first = join_queue(db, session, "telegram:12345", "standard")
    cancel_token(db, first.id)

    second = join_queue(db, session, "telegram:12345", "standard")

    assert second.id != first.id


def test_join_queue_allows_rejoining_after_being_served(db):
    session = _make_clinic_session(db)
    from core.queue_engine import call_next

    first = join_queue(db, session, "telegram:12345", "standard")
    call_next(db, session.id)
    mark_served(db, first.id)

    second = join_queue(db, session, "telegram:12345", "standard")

    assert second.id != first.id


def test_join_queue_allows_the_same_contact_in_different_tiers_to_still_collide(db):
    """The duplicate check is purely per-contact, not per-(contact, tier) -- a patient
    can't dodge it by picking a different tier for the second attempt."""
    session = _make_clinic_session(db)
    join_queue(db, session, "telegram:12345", "standard")

    with pytest.raises(DuplicateBookingError):
        join_queue(db, session, "telegram:12345", "priority")


def test_join_queue_allows_different_contacts_freely(db):
    session = _make_clinic_session(db)
    a = join_queue(db, session, "telegram:aaa", "standard")
    b = join_queue(db, session, "telegram:bbb", "standard")

    assert a.id != b.id
