"""add master_hash to project_repos and monitor_logs table

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

    op.create_table(
        'monitor_logs',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('project_id', sa.String(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('project_name', sa.String(), server_default=''),
        sa.Column('status', sa.Integer(), server_default='0'),
        sa.Column('repos_changed', sa.Text(), server_default='[]'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_monitor_logs_project_id', 'monitor_logs', ['project_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_monitor_logs_project_id')
    op.drop_table('monitor_logs')

    with op.batch_alter_table('project_repos', schema=None) as batch_op:
        batch_op.drop_column('master_hash')
