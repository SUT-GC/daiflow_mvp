"""Task state machine using transitions library.

Manages the 4-stage task lifecycle:
  created → initializing → planning → plan_locked → todo_ready → coding → reviewing → done

All stage transitions are user-triggered (button), except:
  - lock_plan triggers background todo generation (handled by router)
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from transitions.extensions.asyncio import AsyncMachine

from daiflow.models import Task, TaskStatus, Todo, TodoStatus

logger = logging.getLogger(__name__)

# Map TaskStatus int values to state names
_STATUS_TO_NAME = {s.value: s.name.lower() for s in TaskStatus}
_NAME_TO_STATUS = {s.name.lower(): s.value for s in TaskStatus}


class TaskWorkflow:
    """Task lifecycle state machine.

    State diagram:
        created → initializing → planning ⇄ (regenerate)
                                    ↓
                               plan_locked → todo_ready → coding → reviewing → done

    Usage:
        wf = TaskWorkflow(task, db)
        await wf.lock_plan()       # validates + transitions
        await wf.start_coding()    # validates conditions + transitions
    """

    states = [
        'created',
        'initializing',
        'planning',
        'plan_locked',
        'todo_ready',
        'coding',
        'reviewing',
        'done',
    ]

    transitions = [
        # Init flow (triggered by create_task background task)
        {'trigger': 'initialize',      'source': 'created',       'dest': 'initializing'},
        {'trigger': 'plan_ready',      'source': 'initializing',  'dest': 'planning'},

        # Plan stage
        {'trigger': 'lock_plan',       'source': 'planning',      'dest': 'plan_locked'},
        {'trigger': 'regenerate_plan', 'source': 'planning',      'dest': 'planning'},

        # Todo decomposition (automatic after lock_plan completes)
        {'trigger': 'todos_ready',     'source': 'plan_locked',   'dest': 'todo_ready'},

        # Coding stage
        {
            'trigger': 'start_coding',
            'source': 'todo_ready',
            'dest': 'coding',
            'conditions': ['_has_todos'],
        },

        # Review stage
        {
            'trigger': 'start_review',
            'source': 'coding',
            'dest': 'reviewing',
            'conditions': ['_all_todos_done'],
        },

        # Completion
        {'trigger': 'finish',  'source': 'reviewing', 'dest': 'done'},

        # Failure recovery
        {'trigger': 'reset',   'source': ['initializing', 'planning'], 'dest': 'created'},
    ]

    def __init__(self, task: Task, db: AsyncSession):
        self.task = task
        self.db = db
        initial = _STATUS_TO_NAME.get(task.status, 'created')
        self.machine = AsyncMachine(
            model=self,
            states=self.states,
            transitions=self.transitions,
            initial=initial,
            after_state_change='_sync_status',
        )

    # ── Conditions ──

    async def _has_todos(self):
        """Guard: task must have at least one todo."""
        result = await self.db.execute(
            select(Todo.id).where(Todo.task_id == self.task.id).limit(1)
        )
        return result.scalar() is not None

    async def _all_todos_done(self):
        """Guard: all todos must be done or skipped."""
        result = await self.db.execute(
            select(Todo.id).where(
                Todo.task_id == self.task.id,
                Todo.status.notin_([TodoStatus.DONE, TodoStatus.SKIPPED]),
            ).limit(1)
        )
        return result.scalar() is None

    # ── State persistence ──

    def _sync_status(self):
        """Sync task.status to DB model whenever state changes."""
        new_status = _NAME_TO_STATUS.get(self.state)
        if new_status is not None:
            self.task.status = new_status
