import threading
from datetime import date

from core.exceptions import PatientAlreadyCalledError
from core.queue_engine import call_next
from core.session_service import get_or_create_active_session
from core.token_service import mark_served
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
    assert no token is ever returned to two callers. v1 assumes a single doctor, so
    exactly one caller should win the race and everyone else should cleanly get
    PatientAlreadyCalledError -- never a duplicate token, never a silent double-win."""
    num_tokens = 8
    num_callers = 25  # deliberately more callers than tokens

    session = _make_session_with_tokens(db, num_tokens)
    session_id = session.id

    results = []
    rejected_count = 0
    lock = threading.Lock()

    def worker():
        nonlocal rejected_count
        thread_db = TestSessionLocal()
        try:
            token = call_next(thread_db, session_id)
            with lock:
                results.append(token.id)
        except PatientAlreadyCalledError:
            with lock:
                rejected_count += 1
        finally:
            thread_db.close()

    threads = [threading.Thread(target=worker) for _ in range(num_callers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 1, f"expected exactly one winner (single-doctor v1), got {len(results)}"
    assert rejected_count == num_callers - 1


def test_concurrent_racing_never_double_assigns_a_token_across_a_full_session(db):
    """Same property as above, but across the whole session's lifecycle: repeatedly race
    N concurrent callers for the currently-callable token, resolve the winner, and race
    again -- proving no token is EVER handed to two callers across the full queue, not
    just the first one."""
    num_tokens = 6
    num_callers_per_round = 6

    session = _make_session_with_tokens(db, num_tokens)
    session_id = session.id

    all_winners = []

    for _ in range(num_tokens):
        round_results = []
        lock = threading.Lock()

        def worker():
            thread_db = TestSessionLocal()
            try:
                token = call_next(thread_db, session_id)
                with lock:
                    round_results.append(token.id)
            except PatientAlreadyCalledError:
                pass
            finally:
                thread_db.close()

        threads = [threading.Thread(target=worker) for _ in range(num_callers_per_round)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(round_results) == 1, f"expected exactly one winner this round, got {len(round_results)}"
        winner_id = round_results[0]
        all_winners.append(winner_id)
        mark_served(db, winner_id)

    assert len(all_winners) == num_tokens
    assert len(set(all_winners)) == num_tokens, "a token was won more than once across the session"


def test_concurrent_get_or_create_active_session_never_crashes_or_duplicates(db):
    """Found via a real load simulation: two concurrent requests (e.g. a patient joining
    and staff calling next) that both land before today's session exists would both see
    "no session yet" and both try to INSERT, and the loser crashed with an unhandled
    UniqueViolation instead of picking up the winner's session. Fire many concurrent
    callers at a clinic with zero sessions yet and assert they all succeed and agree on
    exactly one session."""
    clinic = Clinic(name="Session Race Test Clinic")
    db.add(clinic)
    db.flush()
    doctor = StaffAccount(
        clinic_id=clinic.id, name="Dr. Race", role="doctor",
        contact="doc@race.test", password_hash="x",
    )
    db.add(doctor)
    db.commit()
    clinic_id = clinic.id

    session_ids = []
    errors = []
    lock = threading.Lock()

    def worker():
        thread_db = TestSessionLocal()
        try:
            session = get_or_create_active_session(thread_db, clinic_id)
            with lock:
                session_ids.append(session.id)
        except Exception as exc:  # noqa: BLE001 -- deliberately broad, this is exactly what crashed before
            with lock:
                errors.append(exc)
        finally:
            thread_db.close()

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"get_or_create_active_session raised under concurrency: {errors}"
    assert len(session_ids) == 20
    assert len(set(session_ids)) == 1, "concurrent callers disagreed on which session is today's"
