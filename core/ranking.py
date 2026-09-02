import uuid
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from db.models import Token

# Tokens are ordered within a session by sequence_no, a NUMERIC (arbitrary-precision)
# column rather than a tight sequential integer. New tokens get their rank from the
# column's own DEFAULT (a dedicated Postgres sequence, spaced by RANK_GAP) so a plain
# INSERT is O(1) and collision-free under concurrent joins -- see the migration that
# introduced tokens_sequence_no_seed.
#
# Re-ordering an EXISTING token (the no-show swap) used to shift every row after the
# insertion point by +1 -- an O(n) write across the whole session on every swap. Here
# it instead computes the midpoint between two neighboring ranks: a single-row write,
# O(log n) to find the neighbor via the sequence_no index, no cascade. Repeatedly
# bisecting the exact same gap does erode headroom over time, but NUMERIC's precision
# is arbitrary (not float64-bounded), and RANK_GAP=1000 leaves room for thousands of
# bisections between any two adjacent tokens before that's a practical concern --
# nowhere close to what a single day's no-show swaps would ever produce.

RANK_GAP = Decimal(1000)


def next_back_rank(db: Session) -> Decimal:
    """A fresh rank past every existing token in the table -- used when an existing
    row needs to move to the true back of the queue (the no-show requeue fallback),
    since column DEFAULTs only apply on INSERT, not on this kind of UPDATE."""
    seed = db.execute(text("SELECT nextval('tokens_sequence_no_seed')")).scalar_one()
    return Decimal(seed) * RANK_GAP


def rank_after(db: Session, session_id: uuid.UUID, partner_rank: Decimal) -> Decimal:
    """A rank sitting immediately after `partner_rank` in session_id's ordering: the
    midpoint between it and whatever token currently comes next, so inserting here
    never touches any other row. Falls back to a step past the end if `partner_rank`
    is already the session's last one."""
    next_rank = db.execute(
        select(Token.sequence_no)
        .where(Token.session_id == session_id, Token.sequence_no > partner_rank)
        .order_by(Token.sequence_no)
        .limit(1)
    ).scalar_one_or_none()
    if next_rank is None:
        return partner_rank + RANK_GAP
    return (partner_rank + next_rank) / 2
