import uuid
from datetime import date

import pytest

from core.exceptions import DuplicateBookingError, InvalidTransitionError
from core.queue_engine import call_next
from core.token_service import cancel_token, change_tier, join_queue, mark_paid, mark_served, upgrade_to_priority
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


def test_mark_paid_rejects_a_cancelled_token(db):
    """A cancelled token never gets served, so recording a payment against it would be a
    receptionist mistake (or a stale UI action) -- there's nothing to collect fees for."""
    session = _make_clinic_session(db)
    token = join_queue(db, session, "telegram:12345", "standard")
    cancel_token(db, token.id)

    with pytest.raises(InvalidTransitionError):
        mark_paid(db, token.id, uuid.uuid4(), 20000)


def test_mark_paid_succeeds_for_a_called_token(db):
    session = _make_clinic_session(db)
    token = join_queue(db, session, "telegram:12345", "standard")
    call_next(db, session.id)

    payment = mark_paid(db, token.id, session.doctor_id, 20000)

    assert payment.paid is True
    assert payment.fee_amount_paise == 20000


def test_change_tier_moves_a_waiting_token_between_tiers(db):
    session = _make_clinic_session(db)
    token = join_queue(db, session, "telegram:12345", "standard")

    updated = change_tier(db, token.id, "priority")

    assert updated.tier == "priority"


def test_change_tier_rejects_a_token_that_is_not_waiting(db):
    session = _make_clinic_session(db)
    token = join_queue(db, session, "telegram:12345", "standard")
    call_next(db, session.id)

    with pytest.raises(InvalidTransitionError):
        change_tier(db, token.id, "priority")


def test_upgrade_to_priority_moves_a_standard_token_to_priority(db):
    session = _make_clinic_session(db)
    token = join_queue(db, session, "telegram:12345", "standard")

    updated = upgrade_to_priority(db, token.id)

    assert updated.tier == "priority"


def test_upgrade_to_priority_rejects_a_token_already_at_priority(db):
    session = _make_clinic_session(db)
    token = join_queue(db, session, "telegram:12345", "priority")

    with pytest.raises(InvalidTransitionError):
        upgrade_to_priority(db, token.id)


def test_upgrade_to_priority_rejects_a_token_that_is_not_waiting(db):
    session = _make_clinic_session(db)
    token = join_queue(db, session, "telegram:12345", "standard")
    call_next(db, session.id)

    with pytest.raises(InvalidTransitionError):
        upgrade_to_priority(db, token.id)


def test_upgrade_to_priority_rejects_a_token_that_already_has_emergency_priority(db):
    """A patient can self-escalate standard -> priority, but emergency status is a
    staff clinical judgment call, not something a patient can request for themselves --
    so a token staff already flagged emergency can't be touched by this endpoint."""
    session = _make_clinic_session(db)
    token = join_queue(db, session, "telegram:12345", "standard")
    token.emergency_override = True
    db.commit()

    with pytest.raises(InvalidTransitionError):
        upgrade_to_priority(db, token.id)
