"""Task lifecycle orchestrator.

Centralizes state transitions + side-effect scheduling so routers stay thin
and services don't mix concerns. All user-facing stage transitions should go
through this module.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession
from transitions.core import MachineError

from daiflow.models import Session, SessionStatus, Task, TaskStatus
from daiflow.session_ids import task_review as _review_sid
from daiflow.workflow.task_machine import TaskWorkflow

logger = logging.getLogger(__name__)


class TransitionError(Exception):
    """Raised when a state transition is invalid."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


async def lock_plan_and_generate_todos(db: AsyncSession, task: Task) -> None:
    """Transition PLANNING → PLAN_LOCKED and schedule todo generation.

    Raises TransitionError if the transition is invalid.
    """
    wf = TaskWorkflow(task, db)
    try:
        await wf.lock_plan()
    except MachineError:
        raise TransitionError(
            f"Cannot transition from {TaskStatus(task.status).name} to PLAN_LOCKED"
        )
    await db.commit()


async def start_coding_stage(db: AsyncSession, task: Task) -> None:
    """Ensure todos are loaded and transition TODO_READY → CODING.

    Raises TransitionError if the transition is invalid or no todos exist.
    """
    from daiflow.services.task_service import start_coding

    await start_coding(task.id, db)

    wf = TaskWorkflow(task, db)
    try:
        result = await wf.start_coding()
    except MachineError:
        raise TransitionError(
            f"Cannot transition from {TaskStatus(task.status).name} to CODING"
        )
    if not result:
        raise TransitionError("Task has no todos")
    await db.commit()


async def start_review_stage(db: AsyncSession, task: Task) -> None:
    """Transition CODING → REVIEWING.

    Creates a review session record if not exists.
    Raises TransitionError if the transition is invalid or todos incomplete.
    """
    wf = TaskWorkflow(task, db)
    try:
        result = await wf.start_review()
    except MachineError:
        raise TransitionError(
            f"Cannot transition from {TaskStatus(task.status).name} to REVIEWING"
        )
    if not result:
        raise TransitionError("All todos must be done or skipped before review")

    session_id = _review_sid(task.id)
    existing = await db.get(Session, session_id)
    if not existing:
        session = Session(
            session_id=session_id, type="review", ref_id=task.id,
            task_id=task.id, status=SessionStatus.WAITING,
        )
        db.add(session)

    await db.commit()


async def finish_task(db: AsyncSession, task: Task) -> bool:
    """Transition REVIEWING → DONE. Returns True if transition succeeded."""
    wf = TaskWorkflow(task, db)
    try:
        await wf.finish()
        return True
    except MachineError:
        logger.warning("Could not transition task %s to DONE", task.id)
        return False
