"""fractional-rank ordering for tokens.sequence_no, replacing the O(n) shift-based no-show swap with O(1) midpoint inserts

Revision ID: fecdb83d4f23
Revises: 44480874f2c3
Create Date: 2026-09-03 01:59:24.663548

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fecdb83d4f23'
down_revision: Union[str, Sequence[str], None] = '44480874f2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Replaces the identity-column + shift-on-reorder approach with a fractional-rank
    NUMERIC column: a dedicated sequence generates back-of-queue ranks (spaced by
    1000, applied as the column's own DEFAULT), and re-ordering an existing row (the
    no-show swap) becomes a single-row midpoint write instead of an O(n) cascade
    across every row after the insertion point. See core/ranking.py.
    """
    op.execute("CREATE SEQUENCE tokens_sequence_no_seed")
    # Seed it past every rank already in the table, so newly-appended tokens are
    # always genuinely last -- existing rows' relative order is otherwise untouched.
    op.execute("""
        SELECT setval(
            'tokens_sequence_no_seed',
            GREATEST(1, (CEIL(COALESCE((SELECT MAX(sequence_no) FROM tokens), 0) / 1000.0) + 1)::bigint)
        )
    """)
    op.execute("ALTER TABLE tokens ALTER COLUMN sequence_no DROP IDENTITY IF EXISTS")
    op.execute("ALTER TABLE tokens ALTER COLUMN sequence_no TYPE NUMERIC USING sequence_no::numeric")
    op.execute("ALTER TABLE tokens ALTER COLUMN sequence_no SET DEFAULT (nextval('tokens_sequence_no_seed') * 1000)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE tokens ALTER COLUMN sequence_no DROP DEFAULT")
    op.execute("ALTER TABLE tokens ALTER COLUMN sequence_no TYPE bigint USING round(sequence_no)::bigint")
    op.execute("DROP SEQUENCE IF EXISTS tokens_sequence_no_seed")
