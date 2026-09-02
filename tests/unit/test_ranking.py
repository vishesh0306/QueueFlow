from datetime import date
from decimal import Decimal

from core.ranking import RANK_GAP, next_back_rank, rank_after
from db.models import Clinic, QueueSession, StaffAccount, Token


def _make_session(db):
    clinic = Clinic(name="Ranking Test Clinic")
    db.add(clinic)
    db.flush()
    doctor = StaffAccount(
        clinic_id=clinic.id, name="Dr. Ranking", role="doctor", contact="doc@ranking.test", password_hash="x",
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
    db.refresh(token)
    return token


def test_new_tokens_get_increasing_ranks_from_the_shared_default(db):
    session = _make_session(db)
    a = _join(db, session, "t:a")
    b = _join(db, session, "t:b")

    assert isinstance(a.sequence_no, Decimal)
    assert b.sequence_no > a.sequence_no


def test_rank_after_lands_strictly_between_two_neighbors(db):
    session = _make_session(db)
    a = _join(db, session, "t:a")
    b = _join(db, session, "t:b")

    mid = rank_after(db, session.id, a.sequence_no)

    assert a.sequence_no < mid < b.sequence_no


def test_rank_after_steps_past_the_end_when_partner_is_last(db):
    session = _make_session(db)
    a = _join(db, session, "t:a")

    rank = rank_after(db, session.id, a.sequence_no)

    assert rank == a.sequence_no + RANK_GAP


def test_rank_after_never_touches_any_other_rows_sequence_no(db):
    """The whole point of fractional ranking: inserting between two tokens is a
    single-row write, not a cascade -- every other token's rank must be untouched."""
    session = _make_session(db)
    a = _join(db, session, "t:a")
    b = _join(db, session, "t:b")
    c = _join(db, session, "t:c")
    b_rank_before, c_rank_before = b.sequence_no, c.sequence_no

    new_rank = rank_after(db, session.id, a.sequence_no)
    a.sequence_no = new_rank
    db.commit()

    db.refresh(b)
    db.refresh(c)
    assert b.sequence_no == b_rank_before
    assert c.sequence_no == c_rank_before


def test_repeated_bisection_between_the_same_neighbors_stays_ordered_and_unique(db):
    """Simulates many no-show swaps landing between the same two tokens in a row --
    exactly the pathological case fractional ranking has to survive."""
    session = _make_session(db)
    a = _join(db, session, "t:a")
    b = _join(db, session, "t:b")

    ranks = [a.sequence_no]
    current = a.sequence_no
    for _ in range(30):
        current = rank_after(db, session.id, current)
        ranks.append(current)
        # Insert a real row at this rank so the next bisection has a genuine neighbor.
        db.add(Token(session_id=session.id, patient_contact=f"t:mid-{len(ranks)}", tier="standard",
                      sequence_no=current))
        db.commit()

    assert all(r < b.sequence_no for r in ranks)
    assert len(ranks) == len(set(ranks))  # every bisection produced a distinct value
    assert ranks == sorted(ranks)


def test_next_back_rank_never_collides_with_the_columns_own_default(db):
    """next_back_rank and the column's server_default draw from the same underlying
    Postgres sequence, so an explicit call and a plain insert can never collide."""
    session = _make_session(db)
    explicit_rank = next_back_rank(db)
    token = _join(db, session, "t:a")

    assert token.sequence_no != explicit_rank
