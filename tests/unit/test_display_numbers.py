import uuid
from datetime import date

from core.queue_engine import trigger_emergency_override
from core.token_service import join_queue
from db.models import Clinic, QueueSession, StaffAccount


def _make_clinic_session(db):
    clinic = Clinic(name="Test Clinic")
    db.add(clinic)
    db.flush()
    doctor = StaffAccount(
        clinic_id=clinic.id, name="Dr. Test", role="doctor",
        contact=f"doc-{uuid.uuid4()}@test", password_hash="x",
    )
    db.add(doctor)
    db.flush()
    session = QueueSession(clinic_id=clinic.id, doctor_id=doctor.id, session_date=date.today())
    db.add(session)
    db.commit()
    return session


def test_display_numbers_increment_independently_per_tier(db):
    session = _make_clinic_session(db)

    s1 = join_queue(db, session, "t:1", "standard")
    p1 = join_queue(db, session, "t:2", "priority")
    s2 = join_queue(db, session, "t:3", "standard")
    p2 = join_queue(db, session, "t:4", "priority")

    assert s1.display_number == "S-1"
    assert s2.display_number == "S-2"
    assert p1.display_number == "P-1"
    assert p2.display_number == "P-2"


def test_emergency_override_gets_its_own_counter(db):
    session = _make_clinic_session(db)

    join_queue(db, session, "t:1", "standard")
    e1 = trigger_emergency_override(db, session.id, "t:urgent-1")
    e2 = trigger_emergency_override(db, session.id, "t:urgent-2")

    assert e1.display_number == "E-1"
    assert e2.display_number == "E-2"


def test_display_numbers_dont_collide_across_sessions(db):
    session_a = _make_clinic_session(db)
    session_b = _make_clinic_session(db)

    a1 = join_queue(db, session_a, "t:a1", "standard")
    b1 = join_queue(db, session_b, "t:b1", "standard")

    assert a1.display_number == "S-1"
    assert b1.display_number == "S-1"  # independent per-session counters, not a bug
