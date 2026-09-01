import json
from datetime import date

import notifications.service as notification_service
from core.queue_engine import call_next, handle_no_show
from db.models import Clinic, QueueSession, StaffAccount, Token


def _make_session(db):
    clinic = Clinic(name="Enqueue Test Clinic")
    db.add(clinic)
    db.flush()
    doctor = StaffAccount(
        clinic_id=clinic.id, name="Dr. Enqueue", role="doctor", contact="doc@enqueue.local", password_hash="x"
    )
    db.add(doctor)
    db.flush()
    session = QueueSession(clinic_id=clinic.id, doctor_id=doctor.id, session_date=date.today())
    db.add(session)
    db.commit()
    return clinic, session


def _join(db, session, contact="telegram:1"):
    token = Token(session_id=session.id, patient_contact=contact, tier="standard")
    db.add(token)
    db.commit()
    return token


def _flush_queue():
    notification_service._redis_client.delete(notification_service.QUEUE_KEY)


def _pop_all_jobs():
    jobs = []
    while True:
        raw = notification_service._redis_client.rpop(notification_service.QUEUE_KEY)
        if raw is None:
            break
        jobs.append(json.loads(raw))
    return jobs


def test_call_next_enqueues_a_your_turn_job(db):
    _flush_queue()
    clinic, session = _make_session(db)
    token = _join(db, session)

    called = call_next(db, session.id)

    jobs = _pop_all_jobs()
    assert len(jobs) == 1
    assert jobs[0]["token_id"] == str(called.id)
    assert jobs[0]["event"] == "your_turn"
    assert jobs[0]["patient_contact"] == token.patient_contact
    assert jobs[0]["clinic_name"] == clinic.name


def test_no_show_swap_enqueues_a_job_for_the_partner(db):
    _flush_queue()
    _clinic, session = _make_session(db)
    a = _join(db, session, "telegram:a")
    b = _join(db, session, "telegram:b")

    call_next(db, session.id)  # calls a, enqueues a job for a
    _pop_all_jobs()  # drain it, not what we're testing here

    handle_no_show(db, a.id)  # b gets swapped in and called

    jobs = _pop_all_jobs()
    assert len(jobs) == 1
    assert jobs[0]["token_id"] == str(b.id)
