"""Tests for the agent registry and individual AgentConfig implementations."""

import json
import pytest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from daiflow.agents import (
    AgentConfig,
    AgentContext,
    get_agent_config,
    register_agent,
    _AGENT_REGISTRY,
)
from daiflow.models import (
    Project,
    Session,
    SessionStatus,
    Task,
    TaskStatus,
    Todo,
    TodoStatus,
)


# ── Registry Tests ──


class TestAgentRegistry:
    def test_all_agents_registered(self):
        """All 5 agent types should be registered on import."""
        expected = {"plan", "todo_split", "todo_exec", "review", "init"}
        assert expected.issubset(set(_AGENT_REGISTRY.keys()))

    def test_get_agent_config_returns_correct_type(self):
        config = get_agent_config("plan")
        assert config.agent_type == "plan"

    def test_get_agent_config_unknown_raises(self):
        with pytest.raises(KeyError, match="Unknown agent type"):
            get_agent_config("nonexistent_agent_xyz")

    def test_register_agent_replaces(self):
        """Registering with the same type replaces the existing config."""
        old = get_agent_config("plan")

        class FakePlan(AgentConfig):
            agent_type = "plan"
            chattable = False

        fake = FakePlan()
        register_agent(fake)
        assert get_agent_config("plan") is fake
        assert get_agent_config("plan").chattable is False

        # Restore original
        register_agent(old)

    def test_chattable_flags(self):
        """Verify chattable flag for each agent type."""
        assert get_agent_config("plan").chattable is True
        assert get_agent_config("todo_split").chattable is True
        assert get_agent_config("todo_exec").chattable is True
        assert get_agent_config("review").chattable is True
        assert get_agent_config("init").chattable is False


# ── AgentConfig Base Tests ──


class TestAgentConfigBase:
    async def test_build_prompt_not_implemented(self):
        base = AgentConfig()
        ctx = AgentContext(db=None, session_id="s1", entity_id="e1")
        with pytest.raises(NotImplementedError):
            await base.build_prompt(ctx)

    async def test_resolve_cody_session_id_default_none(self):
        base = AgentConfig()
        ctx = AgentContext(db=None, session_id="s1", entity_id="e1")
        assert await base.resolve_cody_session_id(ctx) is None

    def test_build_artifact_detector_default_none(self):
        base = AgentConfig()
        ctx = AgentContext(db=None, session_id="s1", entity_id="e1")
        assert base.build_artifact_detector(ctx) is None

    async def test_on_complete_default_noop(self):
        base = AgentConfig()
        ctx = AgentContext(db=None, session_id="s1", entity_id="e1")
        # Should not raise
        await base.on_complete(ctx)

    def test_chat_system_prefix_default_none(self):
        base = AgentConfig()
        ctx = AgentContext(db=None, session_id="s1", entity_id="e1")
        assert base.chat_system_prefix(ctx) is None


# ── PlanAgent Tests ──


class TestPlanAgent:
    async def test_build_prompt(self):
        config = get_agent_config("plan")
        task = SimpleNamespace(
            id="t1",
            description="Build feature X",
            prd="PRD content",
            tech_plan="Existing plan",
            project_id="p1",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = AgentContext(
                db=None,
                session_id="s1",
                entity_id="t1",
                task=task,
                task_dir=tmpdir,
                allowed_roots=[tmpdir],
            )
            prompt = await config.build_prompt(ctx)
            assert "Build feature X" in prompt
            assert "plan.md" in prompt

    def test_build_artifact_detector(self):
        config = get_agent_config("plan")
        with tempfile.TemporaryDirectory() as tmpdir:
            task = SimpleNamespace(id="t1", tech_plan="")
            ctx = AgentContext(
                db=AsyncMock(),
                session_id="s1",
                entity_id="t1",
                task=task,
                task_dir=tmpdir,
            )
            detector = config.build_artifact_detector(ctx)
            assert detector is not None
            assert callable(detector)

    async def test_artifact_detector_matches_plan_md(self):
        config = get_agent_config("plan")
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write a plan.md file
            plan_path = Path(tmpdir) / "plan.md"
            plan_path.write_text("# My Plan\n\nDetails here.", encoding="utf-8")

            db = AsyncMock()
            task = SimpleNamespace(id="t1", tech_plan="")
            ctx = AgentContext(
                db=db,
                session_id="s1",
                entity_id="t1",
                task=task,
                task_dir=tmpdir,
            )
            detector = config.build_artifact_detector(ctx)
            result = await detector({
                "tool_name": "write_file",
                "args": {"path": str(plan_path)},
            })
            assert result is not None
            assert result["type"] == "plan_updated"
            assert "My Plan" in result["content"]

    async def test_on_complete_syncs_plan(self):
        config = get_agent_config("plan")
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = Path(tmpdir) / "plan.md"
            plan_path.write_text("# Final Plan", encoding="utf-8")

            # Mock task and db
            task = SimpleNamespace(id="t1", tech_plan="")
            mock_task_obj = SimpleNamespace(id="t1", tech_plan="")
            db = AsyncMock()
            db.get = AsyncMock(return_value=mock_task_obj)

            ctx = AgentContext(
                db=db,
                session_id="s1",
                entity_id="t1",
                task=task,
                task_dir=tmpdir,
            )
            await config.on_complete(ctx)
            assert mock_task_obj.tech_plan == "# Final Plan"
            db.commit.assert_awaited()

    async def test_on_complete_noop_when_task_deleted(self):
        config = get_agent_config("plan")
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = Path(tmpdir) / "plan.md"
            plan_path.write_text("# Final Plan", encoding="utf-8")

            task = SimpleNamespace(id="t1", tech_plan="")
            db = AsyncMock()
            db.get = AsyncMock(return_value=None)  # Task deleted

            ctx = AgentContext(
                db=db,
                session_id="s1",
                entity_id="t1",
                task=task,
                task_dir=tmpdir,
            )
            # Should not raise
            await config.on_complete(ctx)
            db.commit.assert_not_awaited()

    def test_chat_system_prefix(self):
        config = get_agent_config("plan")
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = AgentContext(
                db=None,
                session_id="s1",
                entity_id="t1",
                task_dir=tmpdir,
            )
            prefix = config.chat_system_prefix(ctx)
            assert prefix is not None
            assert "plan.md" in prefix


# ── TodoSplitAgent Tests ──


class TestTodoSplitAgent:
    async def test_build_prompt(self):
        config = get_agent_config("todo_split")
        with tempfile.TemporaryDirectory() as tmpdir:
            task = SimpleNamespace(id="t1", project_id="p1")
            ctx = AgentContext(
                db=None,
                session_id="s1",
                entity_id="t1",
                task=task,
                task_dir=tmpdir,
                allowed_roots=[tmpdir],
            )
            prompt = await config.build_prompt(ctx)
            assert "todo.json" in prompt

    async def test_resolve_cody_session_id(self, db_session):
        """Should reuse plan's cody_session_id."""
        # Create a plan session with a cody_session_id
        plan_session = Session(
            session_id="task:t1:plan",
            type="plan",
            task_id="t1",
            cody_session_id="cody_abc123",
        )
        db_session.add(plan_session)
        await db_session.commit()

        config = get_agent_config("todo_split")
        ctx = AgentContext(
            db=db_session,
            session_id="task:t1:todo_split",
            entity_id="t1",
        )
        result = await config.resolve_cody_session_id(ctx)
        assert result == "cody_abc123"

    async def test_resolve_cody_session_id_no_plan(self, db_session):
        config = get_agent_config("todo_split")
        ctx = AgentContext(
            db=db_session,
            session_id="task:t1:todo_split",
            entity_id="t1",
        )
        result = await config.resolve_cody_session_id(ctx)
        assert result is None

    def test_chat_system_prefix(self):
        config = get_agent_config("todo_split")
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = AgentContext(
                db=None,
                session_id="s1",
                entity_id="t1",
                task_dir=tmpdir,
            )
            prefix = config.chat_system_prefix(ctx)
            assert prefix is not None
            assert "todo.json" in prefix


# ── TodoExecAgent Tests ──


class TestTodoExecAgent:
    async def test_build_prompt(self):
        config = get_agent_config("todo_exec")
        with tempfile.TemporaryDirectory() as tmpdir:
            todo = SimpleNamespace(seq=1, title="Add login", description="Add login page")
            ctx = AgentContext(
                db=None,
                session_id="s1",
                entity_id="todo1",
                todo=todo,
                task_dir=tmpdir,
                allowed_roots=[tmpdir],
            )
            prompt = await config.build_prompt(ctx)
            assert "Add login" in prompt

    def test_build_artifact_detector_matches_any_write(self):
        config = get_agent_config("todo_exec")
        ctx = AgentContext(db=None, session_id="s1", entity_id="todo1")
        detector = config.build_artifact_detector(ctx)
        assert detector is not None

    async def test_artifact_detector_any_file(self):
        config = get_agent_config("todo_exec")
        ctx = AgentContext(db=None, session_id="s1", entity_id="todo1")
        detector = config.build_artifact_detector(ctx)
        result = await detector({
            "tool_name": "write_file",
            "args": {"path": "/any/file.py"},
        })
        assert result is not None
        assert result["type"] == "code_updated"

    async def test_on_complete_success(self, db_session):
        """on_complete should transition todo to DONE when session succeeded."""
        config = get_agent_config("todo_exec")

        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()

        t = Task(name="task", project_id=p.id, status=TaskStatus.CODING)
        db_session.add(t)
        await db_session.flush()

        todo = Todo(task_id=t.id, seq=1, title="T1", status=TodoStatus.RUNNING)
        db_session.add(todo)
        await db_session.flush()

        # Create a DONE session
        session = Session(
            session_id="task:t1:todo:todo1",
            type="todo_exec",
            task_id=t.id,
            status=SessionStatus.DONE,
            cody_session_id="cody_xyz",
        )
        db_session.add(session)
        await db_session.commit()

        ctx = AgentContext(
            db=db_session,
            session_id=session.session_id,
            entity_id=todo.id,
            task=t,
            todo=todo,
            task_dir="/tmp/test",
            allowed_roots=[],
        )

        with patch("daiflow.services.git_service.get_head_hash", new_callable=AsyncMock, return_value="abc123"):
            await config.on_complete(ctx)

        await db_session.refresh(todo)
        assert todo.status == TodoStatus.DONE
        assert todo.cody_session_id == "cody_xyz"

    async def test_on_complete_noop_when_deleted(self, db_session):
        """on_complete should be a no-op when todo was deleted during execution."""
        config = get_agent_config("todo_exec")

        # Create a context with a non-existent todo
        ctx = AgentContext(
            db=db_session,
            session_id="s1",
            entity_id="nonexistent_todo",
            todo=SimpleNamespace(id="nonexistent_todo"),
            task_dir="/tmp/test",
            allowed_roots=[],
        )
        # Should not raise
        await config.on_complete(ctx)


# ── ReviewAgent Tests ──


class TestReviewAgent:
    def test_not_runnable(self):
        """Review agent's build_prompt should raise NotImplementedError."""
        config = get_agent_config("review")
        ctx = AgentContext(db=None, session_id="s1", entity_id="t1")
        with pytest.raises(NotImplementedError):
            import asyncio
            asyncio.get_event_loop().run_until_complete(config.build_prompt(ctx))

    async def test_resolve_cody_session_id(self, db_session):
        """Should look up review session's cody_session_id."""
        review_session = Session(
            session_id="task:t1:review",
            type="review",
            task_id="t1",
            cody_session_id="cody_review_123",
        )
        db_session.add(review_session)
        await db_session.commit()

        config = get_agent_config("review")
        ctx = AgentContext(
            db=db_session,
            session_id="task:t1:review",
            entity_id="t1",
        )
        result = await config.resolve_cody_session_id(ctx)
        assert result == "cody_review_123"

    def test_build_artifact_detector(self):
        config = get_agent_config("review")
        ctx = AgentContext(db=None, session_id="s1", entity_id="t1")
        detector = config.build_artifact_detector(ctx)
        assert detector is not None


# ── InitAgent Tests ──


class TestInitAgent:
    def test_not_chattable(self):
        config = get_agent_config("init")
        assert config.chattable is False

    async def test_build_prompt_raises(self):
        config = get_agent_config("init")
        ctx = AgentContext(db=None, session_id="s1", entity_id="e1")
        with pytest.raises(NotImplementedError):
            await config.build_prompt(ctx)
