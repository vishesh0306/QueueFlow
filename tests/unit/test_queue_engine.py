import uuid
from datetime import date

import pytest

from core.exceptions import InvalidTransitionError, QueueEmptyError
from core.queue_engine import call_next, handle_no_show, trigger_emergency_override
from db.models import Clinic, QueueSession, StaffAccount, Token


def _make_clinic_session(db, ratio="2:1"):
    clinic = Clinic(name="Test Clinic", standard_priority_ratio=ratio)
    db.add(clinic)
    db.flush()
    doctor = StaffAccount(
        clinic_id=clinic.id, name="Dr. Test", role="doctor", contact="doc@test", password_hash="x"
    )
    db.add(doctor)
    db.flush()
    session = QueueSession(clinic_id=clinic.id, doctor_id=doctor.id, session_date=date.today())
    db.add(session)
    db.commit()
    return session


def _join(db, session, tier="standard", contact=None):
    token = Token(session_id=session.id, patient_contact=contact or f"t:{uuid.uuid4()}", tier=tier)
    db.add(token)
    db.commit()
    return token


def test_call_next_on_empty_queue_raises(db):
    session = _make_clinic_session(db)
    with pytest.raises(QueueEmptyError):
        call_next(db, session.id)


def test_call_next_follows_interleave_ratio(db):
    session = _make_clinic_session(db, ratio="2:1")
    for _ in range(4):
        _join(db, session, "standard")
    for _ in range(2):
        _join(db, session, "priority")

    order = [call_next(db, session.id).tier for _ in range(6)]

    assert order == ["priority", "standard", "standard", "priority", "standard", "standard"]


def test_call_next_falls_back_when_preferred_tier_empty(db):
    session = _make_clinic_session(db, ratio="2:1")
    session.call_counter = 1  # position 1 in a 2:1 cycle prefers "standard"
    db.commit()
    only_priority = _join(db, session, "priority")

    called = call_next(db, session.id)  # no standard tokens waiting -> falls back to priority

    assert called.id == only_priority.id


def test_emergency_override_bypasses_interleave(db):
    session = _make_clinic_session(db)
    _join(db, session, "priority")
    _join(db, session, "standard")
    trigger_emergency_override(db, session.id, "t:urgent")

    called = call_next(db, session.id)
    assert called.emergency_override is True


def test_no_show_swaps_with_next_same_tier(db):
    session = _make_clinic_session(db)
    a = _join(db, session, "standard", "t:a")
    b = _join(db, session, "standard", "t:b")

    called = call_next(db, session.id)
    assert called.id == a.id

    result = handle_no_show(db, a.id)
    assert result == {"action": "swapped", "new_called_token_id": b.id}

    db.refresh(a)
    db.refresh(b)
    assert a.status == "waiting"
    assert a.swap_used is True
    assert b.status == "called"


def test_no_show_increments_session_no_show_count(db):
    session = _make_clinic_session(db)
    a = _join(db, session, "standard", "t:a")
    _join(db, session, "standard", "t:b")

    call_next(db, session.id)
    handle_no_show(db, a.id)

    db.refresh(session)
    assert session.no_show_count == 1


def test_swapped_token_reinserted_immediately_behind_partner(db):
    session = _make_clinic_session(db)
    a = _join(db, session, "standard", "t:a")
    _join(db, session, "standard", "t:b")
    c = _join(db, session, "standard", "t:c")

    call_next(db, session.id)       # calls a
    handle_no_show(db, a.id)        # a<->b swap: a goes back to waiting, right behind b's old slot

    next_called = call_next(db, session.id)
    assert next_called.id == a.id   # a is picked again, ahead of c
    assert c.status == "waiting"


def test_no_show_with_no_partner_requeues_to_back(db):
    session = _make_clinic_session(db)
    a = _join(db, session, "standard", "t:a")
    call_next(db, session.id)

    result = handle_no_show(db, a.id)

    assert result == {"action": "requeued", "new_called_token_id": None}
    db.refresh(a)
    assert a.status == "waiting"

    db.refresh(session)
    assert session.no_show_count == 1  # counted even though there was no swap partner


def test_swap_used_token_falls_back_to_requeue_on_second_noshow(db):
    session = _make_clinic_session(db)
    a = _join(db, session, "standard", "t:a")
    _join(db, session, "standard", "t:b")

    call_next(db, session.id)         # calls a
    handle_no_show(db, a.id)          # a<->b swap; a.swap_used=True now

    db.refresh(a)
    assert a.swap_used is True

    a.status = "called"               # simulate a being re-called later in the day
    db.commit()

    result = handle_no_show(db, a.id)  # a no-shows again; its swap is already spent

    assert result == {"action": "requeued", "new_called_token_id": None}


def test_handle_no_show_rejects_non_called_token(db):
    session = _make_clinic_session(db)
    a = _join(db, session, "standard", "t:a")

    with pytest.raises(InvalidTransitionError):
        handle_no_show(db, a.id)
