from datetime import date

import pytest

from core.exceptions import InvalidTransitionError, SessionNotActiveError
from core.queue_engine import call_next, handle_no_show, trigger_emergency_override
from core.session_service import pause_session, resume_session
from core.token_service import cancel_token, join_queue, mark_paid, mark_served
from db.models import Clinic, QueueSession, StaffAccount, Token


def _make_session(db):
    clinic = Clinic(name="Adversarial Test Clinic")
    db.add(clinic)
    db.flush()
    doctor = StaffAccount(
        clinic_id=clinic.id, name="Dr. Adversarial", role="doctor",
        contact="doc@adversarial.test", password_hash="x",
    )
    db.add(doctor)
    db.flush()
    session = QueueSession(clinic_id=clinic.id, doctor_id=doctor.id, session_date=date.today())
    db.add(session)
    db.commit()
    return session


def _join(db, session, contact):
    token = Token(session_id=session.id, patient_contact=contact, tier="standard")
    db.add(token)
    db.commit()
    return token


# ---- Both patients no-show back to back --------------------------------

def test_two_consecutive_no_shows_swaps_back_with_the_same_reinserted_patient(db):
    """A no-shows -> swaps with B (A.swap_used=True; A is reinserted immediately behind
    B's old slot, per the "single-cascade" reinsertion policy from Phase 2). B then
    ALSO no-shows -> the next waiting token in that tier is A again (that's exactly
    where the reinsertion put it), not C. swap_used only caps how many times a token
    can itself benefit from a swap as the no-show party -- it doesn't stop that token
    from being picked as someone else's rescue partner. So A gets called a second
    time, C is untouched. If A no-shows again afterwards, A.swap_used is already
    True, so that third no-show sends A to the back rather than cascading further --
    the real, per-LLD-spec bound on this chain (see core/queue_engine.py's
    handle_no_show and the Phase 2 discussion of the HLD's looser "single cascade"
    prose vs. the LLD's literal per-token swap_used check)."""
    session = _make_session(db)
    a = _join(db, session, "t:a")
    b = _join(db, session, "t:b")
    c = _join(db, session, "t:c")

    called = call_next(db, session.id)
    assert called.id == a.id

    result1 = handle_no_show(db, a.id)
    assert result1 == {"action": "swapped", "new_called_token_id": b.id}

    result2 = handle_no_show(db, b.id)
    assert result2 == {"action": "swapped", "new_called_token_id": a.id}

    db.refresh(a)
    db.refresh(b)
    db.refresh(c)
    assert a.status == "called"
    assert b.status == "waiting" and b.swap_used is True
    assert c.status == "waiting"  # never touched by either swap

    # A no-shows a second time: its swap is already spent, so it's requeued to the
    # back rather than bumping anyone else -- the chain actually terminates here.
    result3 = handle_no_show(db, a.id)
    assert result3 == {"action": "requeued", "new_called_token_id": None}


# ---- Cancel while called -------------------------------------------------

def test_cancel_while_called_succeeds(db):
    session = _make_session(db)
    a = _join(db, session, "t:a")
    call_next(db, session.id)

    cancelled = cancel_token(db, a.id)

    assert cancelled.status == "cancelled"


def test_no_show_on_a_cancelled_token_is_rejected(db):
    """Staff double-clicking no-show right after a patient cancels their own called token."""
    session = _make_session(db)
    a = _join(db, session, "t:a")
    call_next(db, session.id)
    cancel_token(db, a.id)

    with pytest.raises(InvalidTransitionError):
        handle_no_show(db, a.id)


def test_cancelled_token_is_never_called_again(db):
    session = _make_session(db)
    a = _join(db, session, "t:a")
    b = _join(db, session, "t:b")
    cancel_token(db, a.id)

    called = call_next(db, session.id)

    assert called.id == b.id


# ---- Idempotency of terminal actions --------------------------------------

def test_mark_served_twice_is_rejected(db):
    session = _make_session(db)
    a = _join(db, session, "t:a")
    call_next(db, session.id)
    mark_served(db, a.id)

    with pytest.raises(InvalidTransitionError):
        mark_served(db, a.id)


def test_mark_paid_twice_does_not_duplicate_or_error(db):
    session = _make_session(db)
    a = _join(db, session, "t:a")
    call_next(db, session.id)

    first = mark_paid(db, a.id, collected_by=None, fee_amount_paise=20000)
    second = mark_paid(db, a.id, collected_by=None, fee_amount_paise=20000)

    assert first.token_id == second.token_id
    assert second.paid is True


def test_cancel_twice_is_rejected(db):
    session = _make_session(db)
    a = _join(db, session, "t:a")
    cancel_token(db, a.id)

    with pytest.raises(InvalidTransitionError):
        cancel_token(db, a.id)


# ---- Emergency override cutting into an in-progress cascade ---------------

def test_emergency_override_inserted_mid_cascade_takes_priority_next(db):
    session = _make_session(db)
    a = _join(db, session, "t:a")
    b = _join(db, session, "t:b")

    call_next(db, session.id)          # calls a
    handle_no_show(db, a.id)           # a<->b swap, b now called

    emergency = trigger_emergency_override(db, session.id, "t:urgent")
    mark_served(db, b.id)              # b's visit finishes

    called = call_next(db, session.id)

    assert called.id == emergency.id


# ---- Pause actually stops ordinary calling, but not emergencies -----------

def test_call_next_blocked_while_paused(db):
    session = _make_session(db)
    _join(db, session, "t:a")
    pause_session(db, session.id)

    with pytest.raises(SessionNotActiveError):
        call_next(db, session.id)


def test_call_next_works_again_after_resume(db):
    session = _make_session(db)
    a = _join(db, session, "t:a")
    pause_session(db, session.id)
    resume_session(db, session.id)

    called = call_next(db, session.id)

    assert called.id == a.id


def test_emergency_override_bypasses_pause(db):
    session = _make_session(db)
    pause_session(db, session.id)
    emergency = trigger_emergency_override(db, session.id, "t:urgent")

    called = call_next(db, session.id)

    assert called.id == emergency.id


def test_join_still_works_while_paused(db):
    """Pausing stops new calls, but the queue itself should keep accepting joiners --
    only SessionClosedError (a different, currently-unreachable state) blocks joining."""
    session = _make_session(db)
    pause_session(db, session.id)

    token = join_queue(db, session, "t:a", "standard")

    assert token.status == "waiting"
