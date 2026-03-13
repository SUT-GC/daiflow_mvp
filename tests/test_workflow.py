"""Tests for workflow state machines (TaskWorkflow and TodoWorkflow)."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from transitions.core import MachineError

from daiflow.models import Project, Task, TaskStatus, Todo, TodoStatus
from daiflow.workflow import TaskWorkflow, TodoWorkflow


# ── TaskWorkflow ──


class TestTaskWorkflow:
    async def test_initial_state_from_task(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id, status=TaskStatus.PLANNING)
        db_session.add(t)
        await db_session.flush()

        wf = TaskWorkflow(t, db_session)
        assert wf.state == "planning"

    async def test_lock_plan_transitions(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id, status=TaskStatus.PLANNING)
        db_session.add(t)
        await db_session.flush()

        wf = TaskWorkflow(t, db_session)
        await wf.lock_plan()
        assert wf.state == "plan_locked"
        assert t.status == TaskStatus.PLAN_LOCKED

    async def test_lock_plan_from_wrong_state_raises(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id, status=TaskStatus.CREATED)
        db_session.add(t)
        await db_session.flush()

        wf = TaskWorkflow(t, db_session)
        with pytest.raises(MachineError):
            await wf.lock_plan()

    async def test_start_coding_requires_todos(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id, status=TaskStatus.TODO_READY)
        db_session.add(t)
        await db_session.flush()

        wf = TaskWorkflow(t, db_session)
        # No todos exist — should not transition
        result = await wf.start_coding()
        assert not result
        assert wf.state == "todo_ready"

    async def test_start_coding_with_todos(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id, status=TaskStatus.TODO_READY)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="do something", status=TodoStatus.PENDING)
        db_session.add(todo)
        await db_session.flush()

        wf = TaskWorkflow(t, db_session)
        await wf.start_coding()
        assert wf.state == "coding"
        assert t.status == TaskStatus.CODING

    async def test_start_review_requires_all_todos_done(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id, status=TaskStatus.CODING)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="do something", status=TodoStatus.PENDING)
        db_session.add(todo)
        await db_session.flush()

        wf = TaskWorkflow(t, db_session)
        result = await wf.start_review()
        assert not result
        assert wf.state == "coding"

    async def test_start_review_when_all_done(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id, status=TaskStatus.CODING)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="do something", status=TodoStatus.DONE)
        db_session.add(todo)
        await db_session.flush()

        wf = TaskWorkflow(t, db_session)
        await wf.start_review()
        assert wf.state == "reviewing"
        assert t.status == TaskStatus.REVIEWING

    async def test_full_lifecycle(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id, status=TaskStatus.CREATED)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="do something", status=TodoStatus.DONE)
        db_session.add(todo)
        await db_session.flush()

        wf = TaskWorkflow(t, db_session)
        await wf.initialize()
        assert t.status == TaskStatus.INITIALIZING
        await wf.plan_ready()
        assert t.status == TaskStatus.PLANNING
        await wf.lock_plan()
        assert t.status == TaskStatus.PLAN_LOCKED
        await wf.todos_ready()
        assert t.status == TaskStatus.TODO_READY
        await wf.start_coding()
        assert t.status == TaskStatus.CODING
        await wf.start_review()
        assert t.status == TaskStatus.REVIEWING
        await wf.finish()
        assert t.status == TaskStatus.DONE

    async def test_reset_from_initializing(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id, status=TaskStatus.INITIALIZING)
        db_session.add(t)
        await db_session.flush()

        wf = TaskWorkflow(t, db_session)
        await wf.reset()
        assert t.status == TaskStatus.CREATED

    async def test_reset_from_planning(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id, status=TaskStatus.PLANNING)
        db_session.add(t)
        await db_session.flush()

        wf = TaskWorkflow(t, db_session)
        await wf.reset()
        assert t.status == TaskStatus.CREATED

    async def test_regenerate_plan(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id, status=TaskStatus.PLANNING)
        db_session.add(t)
        await db_session.flush()

        wf = TaskWorkflow(t, db_session)
        await wf.regenerate_plan()
        assert wf.state == "planning"
        assert t.status == TaskStatus.PLANNING

    async def test_regenerate_plan_from_wrong_state_raises(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id, status=TaskStatus.PLAN_LOCKED)
        db_session.add(t)
        await db_session.flush()

        wf = TaskWorkflow(t, db_session)
        with pytest.raises(MachineError):
            await wf.regenerate_plan()

    async def test_start_review_with_mixed_done_skipped(self, db_session: AsyncSession):
        """Review allowed when todos are a mix of DONE and SKIPPED."""
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id, status=TaskStatus.CODING)
        db_session.add(t)
        await db_session.flush()
        db_session.add_all([
            Todo(task_id=t.id, seq=1, title="a", status=TodoStatus.DONE),
            Todo(task_id=t.id, seq=2, title="b", status=TodoStatus.SKIPPED),
        ])
        await db_session.flush()

        wf = TaskWorkflow(t, db_session)
        await wf.start_review()
        assert t.status == TaskStatus.REVIEWING


# ── TodoWorkflow ──


class TestTodoWorkflow:
    async def test_execute_first_todo(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.PENDING)
        db_session.add(todo)
        await db_session.flush()

        wf = TodoWorkflow(todo, db_session)
        await wf.execute()
        assert wf.state == "running"
        assert todo.status == TodoStatus.RUNNING

    async def test_execute_blocked_by_prev(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id)
        db_session.add(t)
        await db_session.flush()
        todo1 = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.PENDING)
        todo2 = Todo(task_id=t.id, seq=2, title="second", status=TodoStatus.PENDING)
        db_session.add_all([todo1, todo2])
        await db_session.flush()

        wf = TodoWorkflow(todo2, db_session)
        result = await wf.execute()
        assert not result
        assert wf.state == "pending"

    async def test_execute_allowed_when_prev_done(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id)
        db_session.add(t)
        await db_session.flush()
        todo1 = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.DONE)
        todo2 = Todo(task_id=t.id, seq=2, title="second", status=TodoStatus.PENDING)
        db_session.add_all([todo1, todo2])
        await db_session.flush()

        wf = TodoWorkflow(todo2, db_session)
        await wf.execute()
        assert wf.state == "running"

    async def test_complete_and_fail(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.RUNNING)
        db_session.add(todo)
        await db_session.flush()

        wf = TodoWorkflow(todo, db_session)
        await wf.complete()
        assert todo.status == TodoStatus.DONE

    async def test_fail_and_retry(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.RUNNING)
        db_session.add(todo)
        await db_session.flush()

        wf = TodoWorkflow(todo, db_session)
        await wf.fail()
        assert todo.status == TodoStatus.FAILED
        await wf.retry()
        assert todo.status == TodoStatus.RUNNING

    async def test_skip_from_pending(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.PENDING)
        db_session.add(todo)
        await db_session.flush()

        wf = TodoWorkflow(todo, db_session)
        await wf.skip()
        assert todo.status == TodoStatus.SKIPPED

    async def test_skip_from_done_raises(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.DONE)
        db_session.add(todo)
        await db_session.flush()

        wf = TodoWorkflow(todo, db_session)
        with pytest.raises(MachineError):
            await wf.skip()

    async def test_prev_skipped_allows_next(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id)
        db_session.add(t)
        await db_session.flush()
        todo1 = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.SKIPPED)
        todo2 = Todo(task_id=t.id, seq=2, title="second", status=TodoStatus.PENDING)
        db_session.add_all([todo1, todo2])
        await db_session.flush()

        wf = TodoWorkflow(todo2, db_session)
        await wf.execute()
        assert wf.state == "running"

    async def test_retry_blocked_by_prev(self, db_session: AsyncSession):
        """Retry should also check _prev_todo_completed."""
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id)
        db_session.add(t)
        await db_session.flush()
        todo1 = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.PENDING)
        todo2 = Todo(task_id=t.id, seq=2, title="second", status=TodoStatus.FAILED)
        db_session.add_all([todo1, todo2])
        await db_session.flush()

        wf = TodoWorkflow(todo2, db_session)
        result = await wf.retry()
        assert not result
        assert wf.state == "failed"

    async def test_skip_from_failed(self, db_session: AsyncSession):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.FAILED)
        db_session.add(todo)
        await db_session.flush()

        wf = TodoWorkflow(todo, db_session)
        await wf.skip()
        assert todo.status == TodoStatus.SKIPPED

    async def test_missing_prev_seq_blocks_execute(self, db_session: AsyncSession):
        """If seq=2 exists but seq=1 does not, execute should be blocked."""
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="t", project_id=p.id)
        db_session.add(t)
        await db_session.flush()
        # Only seq=2, no seq=1
        todo = Todo(task_id=t.id, seq=2, title="second", status=TodoStatus.PENDING)
        db_session.add(todo)
        await db_session.flush()

        wf = TodoWorkflow(todo, db_session)
        result = await wf.execute()
        assert not result
        assert wf.state == "pending"
