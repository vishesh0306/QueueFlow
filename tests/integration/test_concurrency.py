import threading
from datetime import date

from core.exceptions import QueueEmptyError
from core.queue_engine import call_next
from db.models import Clinic, QueueSession, StaffAccount, Token
from tests.conftest import TestSessionLocal


def _make_session_with_tokens(db, count: int) -> QueueSession:
    clinic = Clinic(name="Concurrency Test Clinic")
    db.add(clinic)
    db.flush()
    doctor = StaffAccount(
        clinic_id=clinic.id, name="Dr. Concurrency", role="doctor",
        contact="doc@concurrency.test", password_hash="x",
    )
    db.add(doctor)
    db.flush()
    session = QueueSession(clinic_id=clinic.id, doctor_id=doctor.id, session_date=date.today())
    db.add(session)
    db.flush()
    for i in range(count):
        db.add(Token(session_id=session.id, patient_contact=f"t:{i}", tier="standard"))
    db.commit()
    return session


def test_concurrent_call_next_never_double_assigns_a_token(db):
    """LLD §12: fire concurrent call_next calls against a real Postgres instance and
    assert no token is ever returned to two callers."""
    num_tokens = 8
    num_callers = 25  # deliberately more callers than tokens, to also exercise QueueEmptyError under contention

    session = _make_session_with_tokens(db, num_tokens)
    session_id = session.id

    results = []
    empty_count = 0
    lock = threading.Lock()

    def worker():
        nonlocal empty_count
        thread_db = TestSessionLocal()
        try:
            token = call_next(thread_db, session_id)
            with lock:
                results.append(token.id)
        except QueueEmptyError:
            with lock:
                empty_count += 1
        finally:
            thread_db.close()

    threads = [threading.Thread(target=worker) for _ in range(num_callers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == num_tokens, f"expected exactly {num_tokens} successful calls, got {len(results)}"
    assert len(set(results)) == num_tokens, "a token was handed to more than one caller under concurrency"
    assert empty_count == num_callers - num_tokens
