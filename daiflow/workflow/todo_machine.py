"""Todo state machine using transitions library.

Manages individual todo execution lifecycle with sequential ordering guard:
  pending → running → done / failed
  failed → running (retry)
  pending / failed → skipped

The _prev_todo_completed condition enforces sequential execution at the backend level.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from transitions.extensions.asyncio import AsyncMachine

from daiflow.models import Todo, TodoStatus

logger = logging.getLogger(__name__)

_STATUS_TO_NAME = {s.value: s.name.lower() for s in TodoStatus}
_NAME_TO_STATUS = {s.name.lower(): s.value for s in TodoStatus}


class TodoWorkflow:
    """Single todo execution state machine.

    State diagram:
        pending → running → done
                     ↓
                   failed → running (retry)

        pending → skipped
        failed  → skipped

    Usage:
        wf = TodoWorkflow(todo, db)
        await wf.execute()    # validates prev_todo_completed + transitions
        await wf.complete()   # running → done
        await wf.fail()       # running → failed
        await wf.skip()       # pending/failed → skipped
    """

    states = ['pending', 'running', 'done', 'failed', 'skipped']

    transitions = [
        {
            'trigger': 'execute',
            'source': 'pending',
            'dest': 'running',
            'conditions': ['_prev_todo_completed'],
        },
        {
            'trigger': 'complete',
            'source': 'running',
            'dest': 'done',
        },
        {
            'trigger': 'fail',
            'source': 'running',
            'dest': 'failed',
        },
        {
            'trigger': 'retry',
            'source': 'failed',
            'dest': 'running',
            'conditions': ['_prev_todo_completed'],
        },
        {
            'trigger': 'skip',
            'source': ['pending', 'failed'],
            'dest': 'skipped',
        },
    ]

    def __init__(self, todo: Todo, db: AsyncSession):
        self.todo = todo
        self.db = db
        initial = _STATUS_TO_NAME.get(todo.status, 'pending')
        self.machine = AsyncMachine(
            model=self,
            states=self.states,
            transitions=self.transitions,
            initial=initial,
            after_state_change='_sync_status',
        )

    async def _prev_todo_completed(self):
        """Guard: previous todo (seq-1) must be done or skipped.

        First todo (seq=1) always passes.
        """
        if self.todo.seq <= 1:
            return True
        result = await self.db.execute(
            select(Todo).where(
                Todo.task_id == self.todo.task_id,
                Todo.seq == self.todo.seq - 1,
            )
        )
        prev = result.scalar()
        return prev is not None and prev.status in (TodoStatus.DONE, TodoStatus.SKIPPED)

    def _sync_status(self):
        """Sync todo.status to DB model whenever state changes."""
        new_status = _NAME_TO_STATUS.get(self.state)
        if new_status is not None:
            self.todo.status = new_status
