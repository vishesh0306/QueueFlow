"""track no-show count per session for daily stats

Revision ID: abbf084b09db
Revises: 8ce91b29134a
Create Date: 2026-09-02 01:30:42.913314

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'abbf084b09db'
down_revision: Union[str, Sequence[str], None] = '8ce91b29134a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('queue_sessions', sa.Column('no_show_count', sa.Integer(), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('queue_sessions', 'no_show_count')
