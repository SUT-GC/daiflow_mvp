"""workflow refactor: sessions add task_id, tasks drop cody session ids

Revision ID: a3f7c2e91d04
Revises: 2d6b509ea8c0
Create Date: 2026-03-13 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f7c2e91d04'
down_revision: Union[str, Sequence[str], None] = '2d6b509ea8c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add task_id column to sessions table
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('task_id', sa.String(), nullable=True))
        batch_op.create_index('ix_sessions_task_id', ['task_id'])
        batch_op.create_foreign_key(
            'fk_sessions_task_id', 'tasks', ['task_id'], ['id'],
            ondelete='SET NULL',
        )

    # Backfill task_id from session_id for task-related sessions
    # session_id format: "task:{task_id}:plan", "task:{task_id}:todo_split", etc.
    conn = op.get_bind()
    sessions = conn.execute(
        sa.text("SELECT session_id FROM sessions WHERE session_id LIKE 'task:%' AND task_id IS NULL")
    ).fetchall()
    for (session_id,) in sessions:
        parts = session_id.split(':')
        if len(parts) >= 3:
            task_id = parts[1]
            conn.execute(
                sa.text("UPDATE sessions SET task_id = :tid WHERE session_id = :sid"),
                {"tid": task_id, "sid": session_id},
            )

    # Remove cody session id columns from tasks table
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_column('plan_cody_session_id')
        batch_op.drop_column('review_cody_session_id')


def downgrade() -> None:
    # Re-add cody session id columns to tasks table
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('plan_cody_session_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('review_cody_session_id', sa.String(), nullable=True))

    # Remove task_id from sessions table
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_sessions_task_id', type_='foreignkey')
        batch_op.drop_index('ix_sessions_task_id')
        batch_op.drop_column('task_id')
