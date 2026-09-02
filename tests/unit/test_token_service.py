import uuid
from datetime import date

import pytest

from core.exceptions import DuplicateBookingError, InvalidTransitionError
from core.queue_engine import call_next
from core.token_service import (
    cancel_token,
    change_tier,
    fee_due_for,
    join_queue,
    mark_paid,
    mark_served,
    update_contact,
    upgrade_to_priority,
    void_payment,
)
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
        mark_paid(db, token.id, uuid.uuid4())


def test_mark_paid_charges_the_clinics_fixed_fee_for_the_tokens_tier(db):
    session = _make_clinic_session(db)
    token = join_queue(db, session, "telegram:12345", "standard")
    call_next(db, session.id)

    payment = mark_paid(db, token.id, session.doctor_id)

    assert payment.paid is True
    assert payment.fee_amount_paise == session.clinic.standard_fee_paise


def test_mark_paid_charges_the_emergency_fee_for_an_emergency_flagged_token(db):
    from core.queue_engine import trigger_emergency_override

    session = _make_clinic_session(db)
    token = trigger_emergency_override(db, session.id, "telegram:emergency")
    call_next(db, session.id)

    payment = mark_paid(db, token.id, session.doctor_id)

    assert payment.fee_amount_paise == session.clinic.emergency_fee_paise


def test_void_payment_reverses_a_paid_status(db):
    session = _make_clinic_session(db)
    token = join_queue(db, session, "telegram:12345", "standard")
    call_next(db, session.id)
    mark_paid(db, token.id, session.doctor_id)

    voided = void_payment(db, token.id)

    assert voided.paid is False
    assert voided.collected_by is None
    assert voided.collected_at is None


def test_void_payment_rejects_a_token_with_no_payment_recorded(db):
    session = _make_clinic_session(db)
    token = join_queue(db, session, "telegram:12345", "standard")
    call_next(db, session.id)

    with pytest.raises(InvalidTransitionError):
        void_payment(db, token.id)


def test_void_payment_rejects_voiding_an_already_voided_payment(db):
    session = _make_clinic_session(db)
    token = join_queue(db, session, "telegram:12345", "standard")
    call_next(db, session.id)
    mark_paid(db, token.id, session.doctor_id)
    void_payment(db, token.id)

    with pytest.raises(InvalidTransitionError):
        void_payment(db, token.id)


def test_fee_due_for_prefers_emergency_over_tier(db):
    session = _make_clinic_session(db)
    clinic = session.clinic

    assert fee_due_for(clinic, "standard", emergency_override=False) == clinic.standard_fee_paise
    assert fee_due_for(clinic, "priority", emergency_override=False) == clinic.priority_fee_paise
    # Emergency wins even if the token's tier field still says "standard" (see
    # trigger_emergency_override, which never touches tier).
    assert fee_due_for(clinic, "standard", emergency_override=True) == clinic.emergency_fee_paise
    assert fee_due_for(clinic, "priority", emergency_override=True) == clinic.emergency_fee_paise


def test_no_tier_is_ever_free_by_default(db):
    session = _make_clinic_session(db)
    clinic = session.clinic

    assert clinic.standard_fee_paise > 0
    assert clinic.priority_fee_paise > 0
    assert clinic.emergency_fee_paise > 0


def test_update_contact_fixes_a_mistyped_value(db):
    session = _make_clinic_session(db)
    token = join_queue(db, session, "telegram:1234", "standard")

    updated = update_contact(db, token.id, "telegram:12345")

    assert updated.patient_contact == "telegram:12345"


def test_update_contact_also_updates_the_fallback_email_when_given(db):
    session = _make_clinic_session(db)
    token = join_queue(db, session, "telegram:1234", "standard")

    updated = update_contact(db, token.id, "telegram:1234", "fixed@b.com")

    assert updated.patient_email == "fixed@b.com"


def test_update_contact_rejects_a_token_that_is_not_active(db):
    session = _make_clinic_session(db)
    token = join_queue(db, session, "telegram:1234", "standard")
    cancel_token(db, token.id)

    with pytest.raises(InvalidTransitionError):
        update_contact(db, token.id, "telegram:9999")


def test_update_contact_rejects_colliding_with_another_active_tokens_contact(db):
    session = _make_clinic_session(db)
    join_queue(db, session, "telegram:aaa", "standard")
    token_b = join_queue(db, session, "telegram:bbb", "standard")

    with pytest.raises(DuplicateBookingError):
        update_contact(db, token_b.id, "telegram:aaa")


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
