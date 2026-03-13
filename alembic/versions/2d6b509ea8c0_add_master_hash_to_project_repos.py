"""add master_hash to project_repos

Revision ID: 2d6b509ea8c0
Revises: 1067fba48e84
Create Date: 2026-03-13 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2d6b509ea8c0'
down_revision: Union[str, Sequence[str], None] = '1067fba48e84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('project_repos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('master_hash', sa.String(), server_default='', nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('project_repos', schema=None) as batch_op:
        batch_op.drop_column('master_hash')
