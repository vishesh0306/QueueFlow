"""track no-show count per token for emergency demotion

Revision ID: 499e58abd4e0
Revises: 8cb2383bb7c5
Create Date: 2026-09-03 00:19:47.829391

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '499e58abd4e0'
down_revision: Union[str, Sequence[str], None] = '8cb2383bb7c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('tokens', sa.Column('no_show_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tokens', 'no_show_count')
