"""make staff contact globally unique for unambiguous login lookup

Revision ID: 8cb2383bb7c5
Revises: abbf084b09db
Create Date: 2026-09-02 18:07:23.763845

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8cb2383bb7c5'
down_revision: Union[str, Sequence[str], None] = 'abbf084b09db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(op.f('staff_accounts_clinic_id_contact_key'), 'staff_accounts', type_='unique')
    op.create_unique_constraint('uq_staff_accounts_contact', 'staff_accounts', ['contact'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_staff_accounts_contact', 'staff_accounts', type_='unique')
    op.create_unique_constraint(
        op.f('staff_accounts_clinic_id_contact_key'), 'staff_accounts', ['clinic_id', 'contact']
    )
