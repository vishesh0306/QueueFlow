"""add optional patient_email for notification fallback

Revision ID: 8ce91b29134a
Revises: 0db6aaa83c15
Create Date: 2026-09-02 01:05:17.852886

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8ce91b29134a'
down_revision: Union[str, Sequence[str], None] = '0db6aaa83c15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('tokens', sa.Column('patient_email', sa.String(length=120), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tokens', 'patient_email')
