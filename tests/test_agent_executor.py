"""Tests for daiflow.agent_executor module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from daiflow.agent_executor import _reset_or_create_session, _build_context, run_agent, prepare_chat
from daiflow.exceptions import InvalidStateError
from daiflow.models import (
    Project,
    Session,
    SessionStatus,
    Task,
    TaskStatus,
    Todo,
    TodoStatus,
)


# ── _reset_or_create_session Tests ──


class TestResetOrCreateSession:
    async def test_creates_new_session(self, db_session):
        await _reset_or_create_session(db_session, "test:s1", "plan", "ref1", "task1")

        session = await db_session.get(Session, "test:s1")
        assert session is not None
        assert session.status == SessionStatus.WAITING
        assert session.type == "plan"
        assert session.ref_id == "ref1"
        assert session.task_id == "task1"

    async def test_resets_existing_session(self, db_session):
        # Create an existing DONE session
        db_session.add(Session(
            session_id="test:s2",
            type="plan",
            ref_id="ref1",
            task_id="task1",
            status=SessionStatus.DONE,
            error="old error",
            cody_session_id="old_cody_id",
        ))
        await db_session.commit()

        await _reset_or_create_session(db_session, "test:s2", "plan", "ref1", "task1")

        session = await db_session.get(Session, "test:s2")
        assert session.status == SessionStatus.WAITING
        assert session.error is None
        assert session.cody_session_id is None
        assert session.started_at is None
        assert session.finished_at is None

    async def test_resets_failed_session(self, db_session):
        db_session.add(Session(
            session_id="test:s3",
            type="todo_exec",
            ref_id="ref1",
            task_id="task1",
            status=SessionStatus.FAILED,
            error="previous error",
        ))
        await db_session.commit()

        await _reset_or_create_session(db_session, "test:s3", "todo_exec", "ref1", "task1")

        session = await db_session.get(Session, "test:s3")
        assert session.status == SessionStatus.WAITING
        assert session.error is None


# ── _build_context Tests ──


class TestBuildContext:
    async def test_builds_context_for_plan(self, db_session):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="task", project_id=p.id)
        db_session.add(t)
        await db_session.commit()

        with patch("daiflow.agent_executor.get_task_context", new_callable=AsyncMock, return_value=(None, ["/repo"])):
            ctx = await _build_context(db_session, t.id, "plan")

        assert ctx.task is not None
        assert ctx.task.id == t.id
        assert ctx.project_id == p.id
        assert ctx.allowed_roots == ["/repo"]

    async def test_builds_context_for_todo_exec(self, db_session):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="task", project_id=p.id)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="T1")
        db_session.add(todo)
        await db_session.commit()

        with patch("daiflow.agent_executor.get_task_context", new_callable=AsyncMock, return_value=(None, ["/repo"])):
            ctx = await _build_context(db_session, todo.id, "todo_exec")

        assert ctx.todo is not None
        assert ctx.todo.id == todo.id
        assert ctx.task is not None
        assert ctx.task.id == t.id

    async def test_raises_on_missing_task(self, db_session):
        with pytest.raises(ValueError, match="Task .* not found"):
            with patch("daiflow.agent_executor.get_task_context", new_callable=AsyncMock):
                await _build_context(db_session, "nonexistent", "plan")

    async def test_raises_on_missing_todo(self, db_session):
        with pytest.raises(ValueError, match="Todo .* not found"):
            with patch("daiflow.agent_executor.get_task_context", new_callable=AsyncMock):
                await _build_context(db_session, "nonexistent_todo", "todo_exec")


# ── run_agent Tests ──


class TestRunAgent:
    async def test_creates_session_before_context_build(self, db_session):
        """Session should be created even if _build_context fails."""
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()

        # run_agent with nonexistent entity — context build will fail
        # but session should still be created
        await run_agent(
            db_session,
            agent_type="plan",
            entity_id="nonexistent",
            session_id="test:fail_ctx",
        )

        session = await db_session.get(Session, "test:fail_ctx")
        assert session is not None
        # Should be FAILED since context build raises ValueError
        assert session.status == SessionStatus.FAILED

    async def test_marks_session_failed_on_error(self, db_session):
        """When execution fails, session should be marked FAILED."""
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="task", project_id=p.id)
        db_session.add(t)
        await db_session.commit()

        with (
            patch("daiflow.agent_executor.get_task_context", new_callable=AsyncMock, return_value=(None, ["/repo"])),
            patch("daiflow.agent_executor.build_task_cody_client", side_effect=Exception("cody build failed")),
        ):
            await run_agent(
                db_session,
                agent_type="plan",
                entity_id=t.id,
                session_id="test:fail_exec",
            )

        session = await db_session.get(Session, "test:fail_exec")
        assert session is not None
        assert session.status == SessionStatus.FAILED
        assert "cody build failed" in session.error

    async def test_ref_id_for_todo_exec(self, db_session):
        """For todo_exec, ref_id should be the task_id, not entity_id (todo_id)."""
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="task", project_id=p.id)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="T1")
        db_session.add(todo)
        await db_session.commit()

        with (
            patch("daiflow.agent_executor.get_task_context", new_callable=AsyncMock, return_value=(None, [])),
            patch("daiflow.agent_executor.build_task_cody_client", side_effect=Exception("stop")),
        ):
            await run_agent(
                db_session,
                agent_type="todo_exec",
                entity_id=todo.id,
                session_id="test:todo_ref",
                task_id=t.id,
            )

        session = await db_session.get(Session, "test:todo_ref")
        assert session.ref_id == t.id  # ref_id should be task_id
        assert session.task_id == t.id

    async def test_full_successful_run(self, db_session):
        """Full run_agent execution with mocked Cody client."""
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="task", project_id=p.id, description="Test task")
        db_session.add(t)
        await db_session.commit()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_runner = AsyncMock()

        with (
            patch("daiflow.agent_executor.get_task_context", new_callable=AsyncMock, return_value=(None, ["/repo"])),
            patch("daiflow.agent_executor.build_task_cody_client", new_callable=AsyncMock, return_value=mock_client),
            patch("daiflow.agent_executor.get_language_setting", new_callable=AsyncMock, return_value="en"),
            patch("daiflow.agent_executor.SessionRunner") as MockRunner,
        ):
            mock_runner_instance = AsyncMock()
            MockRunner.return_value = mock_runner_instance

            await run_agent(
                db_session,
                agent_type="plan",
                entity_id=t.id,
                session_id="test:success",
            )

            # SessionRunner.run should have been called
            mock_runner_instance.run.assert_awaited_once()
            call_kwargs = mock_runner_instance.run.call_args
            assert call_kwargs[1].get("language") == "en" or call_kwargs[0][2] is not None  # prompt passed


# ── prepare_chat Tests ──


class TestPrepareChat:
    async def test_chattable_agent(self, db_session):
        """prepare_chat should succeed for chattable agents."""
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="task", project_id=p.id)
        db_session.add(t)
        await db_session.commit()

        mock_client = AsyncMock()

        with (
            patch("daiflow.agent_executor.get_task_context", new_callable=AsyncMock, return_value=(None, ["/repo"])),
            patch("daiflow.agent_executor.build_task_cody_client", new_callable=AsyncMock, return_value=mock_client),
            patch("daiflow.agent_executor.get_language_setting", new_callable=AsyncMock, return_value="en"),
        ):
            ctx = await prepare_chat(
                db_session,
                agent_type="plan",
                entity_id=t.id,
                session_id="task:t1:plan",
            )

        assert ctx.session_id == "task:t1:plan"
        assert ctx.cody_client is mock_client
        assert ctx.language == "en"

    async def test_non_chattable_agent_raises(self, db_session):
        """prepare_chat should raise InvalidStateError for non-chattable agents."""
        with pytest.raises(InvalidStateError, match="does not support chat"):
            await prepare_chat(
                db_session,
                agent_type="init",
                entity_id="e1",
                session_id="s1",
            )

    async def test_todo_exec_uses_stored_cody_session_id(self, db_session):
        """For todo_exec, prepare_chat should use todo's stored cody_session_id."""
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="task", project_id=p.id)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(
            task_id=t.id,
            seq=1,
            title="T1",
            cody_session_id="todo_cody_id_stored",
        )
        db_session.add(todo)
        await db_session.commit()

        mock_client = AsyncMock()

        with (
            patch("daiflow.agent_executor.get_task_context", new_callable=AsyncMock, return_value=(None, [])),
            patch("daiflow.agent_executor.build_task_cody_client", new_callable=AsyncMock, return_value=mock_client),
            patch("daiflow.agent_executor.get_language_setting", new_callable=AsyncMock, return_value="en"),
        ):
            ctx = await prepare_chat(
                db_session,
                agent_type="todo_exec",
                entity_id=todo.id,
                session_id="task:t1:todo:todo1",
            )

        assert ctx.cody_session_id == "todo_cody_id_stored"

    async def test_returns_system_prefix(self, db_session):
        """prepare_chat should include the agent's system prefix."""
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="task", project_id=p.id)
        db_session.add(t)
        await db_session.commit()

        mock_client = AsyncMock()

        with (
            patch("daiflow.agent_executor.get_task_context", new_callable=AsyncMock, return_value=(None, [])),
            patch("daiflow.agent_executor.build_task_cody_client", new_callable=AsyncMock, return_value=mock_client),
            patch("daiflow.agent_executor.get_language_setting", new_callable=AsyncMock, return_value="en"),
        ):
            ctx = await prepare_chat(
                db_session,
                agent_type="plan",
                entity_id=t.id,
                session_id="task:t1:plan",
            )

        # Plan agent has a system prefix that includes "plan.md"
        assert ctx.system_prefix is not None
        assert "plan.md" in ctx.system_prefix

    async def test_raises_on_missing_entity(self, db_session):
        """prepare_chat should raise ValueError when entity doesn't exist."""
        with pytest.raises(ValueError, match="not found"):
            with patch("daiflow.agent_executor.get_task_context", new_callable=AsyncMock):
                await prepare_chat(
                    db_session,
                    agent_type="plan",
                    entity_id="nonexistent",
                    session_id="s1",
                )
