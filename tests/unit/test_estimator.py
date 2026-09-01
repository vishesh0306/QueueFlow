from datetime import date, datetime, timedelta, timezone

from core.estimator import DEFAULT_ESTIMATE_SECONDS, estimated_wait_seconds
from db.models import Clinic, QueueSession, ServiceTimeSample, StaffAccount, Token


def _make_session(db):
    clinic = Clinic(name="Test Clinic")
    db.add(clinic)
    db.flush()
    doctor = StaffAccount(
        clinic_id=clinic.id, name="Dr. Test", role="doctor", contact="doc@test", password_hash="x"
    )
    db.add(doctor)
    db.flush()
    session = QueueSession(clinic_id=clinic.id, doctor_id=doctor.id, session_date=date.today())
    db.add(session)
    db.flush()
    return session


def test_default_estimate_when_no_samples(db):
    session = _make_session(db)
    db.commit()

    assert estimated_wait_seconds(db, session.id, position=3) == 3 * DEFAULT_ESTIMATE_SECONDS


def test_rolling_average_of_samples(db):
    session = _make_session(db)
    token = Token(session_id=session.id, patient_contact="t:1", tier="standard")
    db.add(token)
    db.flush()
    for duration in (100, 200, 300):
        db.add(ServiceTimeSample(session_id=session.id, token_id=token.id, duration_seconds=duration))
    db.commit()

    assert estimated_wait_seconds(db, session.id, position=2) == 2 * 200


def test_rolling_window_only_considers_last_n_samples(db):
    session = _make_session(db)
    token = Token(session_id=session.id, patient_contact="t:1", tier="standard")
    db.add(token)
    db.flush()
    # recorded_at is explicit here because Postgres' now() is transaction-scoped,
    # so same-transaction inserts would otherwise tie on timestamp.
    base = datetime.now(timezone.utc)
    db.add(ServiceTimeSample(
        session_id=session.id, token_id=token.id, duration_seconds=1,
        recorded_at=base - timedelta(hours=1),
    ))
    for i in range(10):
        db.add(ServiceTimeSample(
            session_id=session.id, token_id=token.id, duration_seconds=1000,
            recorded_at=base + timedelta(seconds=i),
        ))
    db.commit()

    assert estimated_wait_seconds(db, session.id, position=1) == 1000
