"""add per-tier fixed fees (standard, priority, emergency)

Revision ID: 44480874f2c3
Revises: 499e58abd4e0
Create Date: 2026-09-03 01:07:20.554751

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '44480874f2c3'
down_revision: Union[str, Sequence[str], None] = '499e58abd4e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('clinics', sa.Column('standard_fee_paise', sa.Integer(), nullable=False, server_default='50000'))
    op.add_column('clinics', sa.Column('emergency_fee_paise', sa.Integer(), nullable=False, server_default='120000'))
    op.alter_column('clinics', 'priority_fee_paise', server_default='80000')
    # Roll out the new hardcoded defaults (₹500 / ₹800 / ₹1200) to clinics that already
    # exist -- there's no real per-clinic customization yet for anyone to preserve.
    op.execute("UPDATE clinics SET standard_fee_paise = 50000, priority_fee_paise = 80000, emergency_fee_paise = 120000")


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('clinics', 'priority_fee_paise', server_default='0')
    op.drop_column('clinics', 'emergency_fee_paise')
    op.drop_column('clinics', 'standard_fee_paise')
