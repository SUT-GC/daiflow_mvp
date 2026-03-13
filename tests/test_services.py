"""Tests for service layer logic."""

import pytest
import json
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from daiflow.models import Project, ProjectRepo, Session, Task, TaskStatus, Todo, TodoStatus
from daiflow.services.project_service import LAYER_2_TYPES, LAYER_3_TYPES, compute_init_sessions
from daiflow.services.task_service import start_coding, sync_todos_from_file


class TestComputeInitSessions:
    def test_single_frontend_repo(self):
        repos = [SimpleNamespace(repo_type="frontend")]
        sessions = compute_init_sessions("proj_1", repos)

        session_ids = [s["session_id"] for s in sessions]

        # Layer 1: skill_fetch + repo_clone
        assert "init:proj_1:skill_fetch" in session_ids
        assert "init:proj_1:repo_clone" in session_ids

        # Layer 2: frontend types
        for kt in LAYER_2_TYPES["frontend"]:
            assert f"init:proj_1:{kt}" in session_ids

        # Layer 3: cross-repo
        for kt in LAYER_3_TYPES:
            assert f"init:proj_1:{kt}" in session_ids

        # Layer 4: project.md
        assert "init:proj_1:project_md" in session_ids

    def test_backend_repo(self):
        repos = [SimpleNamespace(repo_type="backend")]
        sessions = compute_init_sessions("proj_1", repos)
        session_ids = [s["session_id"] for s in sessions]
        assert "init:proj_1:backend-structure" in session_ids

    def test_custom_repo(self):
        repos = [SimpleNamespace(repo_type="custom")]
        sessions = compute_init_sessions("proj_1", repos)
        session_ids = [s["session_id"] for s in sessions]
        # Custom should get backend-structure + business-flow
        assert "init:proj_1:backend-structure" in session_ids
        assert "init:proj_1:business-flow" in session_ids

    def test_multiple_repos(self):
        repos = [
            SimpleNamespace(repo_type="frontend"),
            SimpleNamespace(repo_type="backend"),
        ]
        sessions = compute_init_sessions("proj_1", repos)
        # Should have Layer 2 sessions for both repo types
        session_ids = [s["session_id"] for s in sessions]
        assert "init:proj_1:frontend-structure" in session_ids
        assert "init:proj_1:backend-structure" in session_ids

    def test_unknown_repo_type_no_layer2(self):
        repos = [SimpleNamespace(repo_type="unknown")]
        sessions = compute_init_sessions("proj_1", repos)
        # Should still have Layer 1, 3, 4 but no Layer 2
        layers = {s["layer"] for s in sessions}
        assert 1 in layers
        assert 3 in layers
        assert 4 in layers
        layer2 = [s for s in sessions if s["layer"] == 2]
        assert len(layer2) == 0

    def test_session_metadata(self):
        repos = [SimpleNamespace(repo_type="frontend")]
        sessions = compute_init_sessions("proj_1", repos)
        for s in sessions:
            assert s["type"] == "init"
            assert s["ref_id"] == "proj_1"
            assert "layer" in s
            assert "session_id" in s


class TestSyncTodosFromFile:
    async def test_basic_sync(self, db_session):
        # Create project + task
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="task", project_id=p.id)
        db_session.add(t)
        await db_session.commit()

        content = json.dumps([
            {"seq": 1, "title": "T1", "description": "Do 1"},
            {"seq": 2, "title": "T2", "description": "Do 2"},
        ])
        await sync_todos_from_file(db_session, t.id, content)

        result = await db_session.execute(select(Todo).where(Todo.task_id == t.id).order_by(Todo.seq))
        todos = result.scalars().all()
        assert len(todos) == 2
        assert todos[0].title == "T1"
        assert todos[1].title == "T2"

    async def test_preserves_running_done(self, db_session):
        """Sync should preserve running/done todos."""
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="task", project_id=p.id)
        db_session.add(t)
        await db_session.flush()

        # Create existing todos with various statuses
        todo_done = Todo(task_id=t.id, seq=1, title="Done", status=TodoStatus.DONE)
        todo_running = Todo(task_id=t.id, seq=2, title="Running", status=TodoStatus.RUNNING)
        todo_pending = Todo(task_id=t.id, seq=3, title="Pending", status=TodoStatus.PENDING)
        db_session.add_all([todo_done, todo_running, todo_pending])
        await db_session.commit()

        done_id = todo_done.id
        running_id = todo_running.id
        pending_id = todo_pending.id

        # Sync with new content that includes seq 1, 2, 3
        content = json.dumps([
            {"seq": 1, "title": "New T1", "description": "New 1"},
            {"seq": 2, "title": "New T2", "description": "New 2"},
            {"seq": 3, "title": "New T3", "description": "New 3"},
        ])
        await sync_todos_from_file(db_session, t.id, content)

        # Done and running should be preserved (same ID)
        assert await db_session.get(Todo, done_id) is not None
        assert await db_session.get(Todo, running_id) is not None
        # Pending should be deleted and recreated
        assert await db_session.get(Todo, pending_id) is None

        # New seq=3 todo should exist
        result = await db_session.execute(
            select(Todo).where(Todo.task_id == t.id, Todo.seq == 3)
        )
        new_t3 = result.scalars().first()
        assert new_t3 is not None
        assert new_t3.title == "New T3"

    async def test_invalid_json(self, db_session):
        """Invalid JSON should not crash."""
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="task", project_id=p.id)
        db_session.add(t)
        await db_session.commit()

        # C1 fix: invalid JSON now raises ValueError instead of silently returning
        with pytest.raises(ValueError):
            await sync_todos_from_file(db_session, t.id, "not json")


class TestStartCoding:
    async def test_sets_status_to_coding(self, db_session):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="task", project_id=p.id, status=TaskStatus.TODO_READY)
        db_session.add(t)
        await db_session.commit()

        await start_coding(t.id, db_session)

        await db_session.refresh(t)
        assert t.status == TaskStatus.CODING

    async def test_nonexistent_task(self, db_session):
        # Should not raise
        await start_coding("nonexistent", db_session)


class TestSkillService:
    def test_sync_skills_no_source(self):
        """When project skills don't exist, create empty directory."""
        from daiflow.services.skill_service import get_task_dir, sync_skills_to_task

        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            old = os.environ.get("DAIFLOW_HOME")
            os.environ["DAIFLOW_HOME"] = tmpdir

            import importlib
            import daiflow.config as cfg
            importlib.reload(cfg)
            cfg.init_daiflow_dir()

            import daiflow.services.skill_service as ss
            importlib.reload(ss)

            ss.sync_skills_to_task("proj_1", "task_1")

            task_skills = ss.get_task_skills_dir("task_1")
            assert task_skills.exists()

            if old:
                os.environ["DAIFLOW_HOME"] = old
            importlib.reload(cfg)
            importlib.reload(ss)

    def test_get_task_dir_creates(self):
        """get_task_dir should create the directory."""
        from daiflow.services.skill_service import get_task_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            old = os.environ.get("DAIFLOW_HOME")
            os.environ["DAIFLOW_HOME"] = tmpdir

            import importlib
            import daiflow.config as cfg
            importlib.reload(cfg)
            cfg.init_daiflow_dir()

            import daiflow.services.skill_service as ss
            importlib.reload(ss)

            d = ss.get_task_dir("task_42")
            assert d.exists()

            if old:
                os.environ["DAIFLOW_HOME"] = old
            importlib.reload(cfg)
            importlib.reload(ss)
