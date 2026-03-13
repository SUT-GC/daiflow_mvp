"""Tests for todo API endpoints and task guard failure paths."""

from unittest.mock import AsyncMock, patch

from daiflow.models import Task, TaskStatus, Todo, TodoStatus


async def _create_project(client):
    resp = await client.post("/api/projects", json={"name": "TestProj"})
    return resp.json()["id"]


_mock_bg = patch("daiflow.routers.tasks.init_task", new_callable=AsyncMock)
_mock_execute = patch("daiflow.routers.todos.execute_todo", new_callable=AsyncMock)


# ── Todo Execute Route ──


class TestTodoExecute:
    @_mock_bg
    @_mock_execute
    async def test_execute_pending_todo(self, mock_exec, mock_init, client, db_session):
        """Execute a PENDING todo (seq=1) should succeed."""
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.CODING)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.PENDING)
        db_session.add(todo)
        await db_session.commit()

        resp = await client.post(f"/api/todos/{todo.id}/execute")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Todo should now be RUNNING (transition happened in router)
        await db_session.refresh(todo)
        assert todo.status == TodoStatus.RUNNING

    @_mock_bg
    @_mock_execute
    async def test_execute_blocked_by_prev_todo(self, mock_exec, mock_init, client, db_session):
        """Execute seq=2 when seq=1 is PENDING should return 400."""
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.CODING)
        db_session.add(t)
        await db_session.flush()
        todo1 = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.PENDING)
        todo2 = Todo(task_id=t.id, seq=2, title="second", status=TodoStatus.PENDING)
        db_session.add_all([todo1, todo2])
        await db_session.commit()

        resp = await client.post(f"/api/todos/{todo2.id}/execute")
        assert resp.status_code == 400
        assert "Previous todo" in resp.json()["detail"]

    @_mock_bg
    @_mock_execute
    async def test_execute_allowed_when_prev_done(self, mock_exec, mock_init, client, db_session):
        """Execute seq=2 when seq=1 is DONE should succeed."""
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.CODING)
        db_session.add(t)
        await db_session.flush()
        todo1 = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.DONE)
        todo2 = Todo(task_id=t.id, seq=2, title="second", status=TodoStatus.PENDING)
        db_session.add_all([todo1, todo2])
        await db_session.commit()

        resp = await client.post(f"/api/todos/{todo2.id}/execute")
        assert resp.status_code == 200

    @_mock_bg
    @_mock_execute
    async def test_execute_failed_todo_retry(self, mock_exec, mock_init, client, db_session):
        """Execute a FAILED todo (retry) should succeed."""
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.CODING)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.FAILED)
        db_session.add(todo)
        await db_session.commit()

        resp = await client.post(f"/api/todos/{todo.id}/execute")
        assert resp.status_code == 200
        await db_session.refresh(todo)
        assert todo.status == TodoStatus.RUNNING

    @_mock_bg
    async def test_execute_done_todo_rejected(self, mock_init, client, db_session):
        """Cannot execute a DONE todo."""
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.CODING)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.DONE)
        db_session.add(todo)
        await db_session.commit()

        resp = await client.post(f"/api/todos/{todo.id}/execute")
        assert resp.status_code == 400

    @_mock_bg
    async def test_execute_running_todo_rejected(self, mock_init, client, db_session):
        """Cannot execute a RUNNING todo (prevents double execution)."""
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.CODING)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.RUNNING)
        db_session.add(todo)
        await db_session.commit()

        resp = await client.post(f"/api/todos/{todo.id}/execute")
        assert resp.status_code == 400

    @_mock_bg
    async def test_execute_not_in_coding_stage(self, mock_init, client, db_session):
        """Cannot execute todo if task is not in CODING stage."""
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.PLANNING)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.PENDING)
        db_session.add(todo)
        await db_session.commit()

        resp = await client.post(f"/api/todos/{todo.id}/execute")
        assert resp.status_code == 400
        assert "not in coding stage" in resp.json()["detail"]

    async def test_execute_not_found(self, client):
        resp = await client.post("/api/todos/nonexistent/execute")
        assert resp.status_code == 404


# ── Todo Skip Route ──


class TestTodoSkip:
    @_mock_bg
    async def test_skip_pending_todo(self, mock_init, client, db_session):
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.CODING)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.PENDING)
        db_session.add(todo)
        await db_session.commit()

        resp = await client.post(f"/api/todos/{todo.id}/skip")
        assert resp.status_code == 200
        await db_session.refresh(todo)
        assert todo.status == TodoStatus.SKIPPED

    @_mock_bg
    async def test_skip_failed_todo(self, mock_init, client, db_session):
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.CODING)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.FAILED)
        db_session.add(todo)
        await db_session.commit()

        resp = await client.post(f"/api/todos/{todo.id}/skip")
        assert resp.status_code == 200
        await db_session.refresh(todo)
        assert todo.status == TodoStatus.SKIPPED

    @_mock_bg
    async def test_skip_running_todo_rejected(self, mock_init, client, db_session):
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.CODING)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.RUNNING)
        db_session.add(todo)
        await db_session.commit()

        resp = await client.post(f"/api/todos/{todo.id}/skip")
        assert resp.status_code == 400

    @_mock_bg
    async def test_skip_done_todo_rejected(self, mock_init, client, db_session):
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.CODING)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.DONE)
        db_session.add(todo)
        await db_session.commit()

        resp = await client.post(f"/api/todos/{todo.id}/skip")
        assert resp.status_code == 400

    async def test_skip_not_found(self, client):
        resp = await client.post("/api/todos/nonexistent/skip")
        assert resp.status_code == 404


# ── Task Guard Failure Paths ──


_mock_bg3 = patch("daiflow.routers.tasks.generate_todos", new_callable=AsyncMock)


class TestTaskGuardFailures:
    @_mock_bg
    async def test_start_coding_no_todos_returns_400(self, mock_init, client, db_session):
        """start-coding with no todos should return 400."""
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.TODO_READY)
        db_session.add(t)
        await db_session.commit()

        resp = await client.post(f"/api/tasks/{t.id}/start-coding")
        assert resp.status_code == 400
        assert "no todos" in resp.json()["detail"]

    @_mock_bg
    async def test_start_coding_with_todos_succeeds(self, mock_init, client, db_session):
        """start-coding with todos should transition to CODING."""
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.TODO_READY)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.PENDING)
        db_session.add(todo)
        await db_session.commit()

        resp = await client.post(f"/api/tasks/{t.id}/start-coding")
        assert resp.status_code == 200
        assert resp.json()["status"] == TaskStatus.CODING

    @_mock_bg
    async def test_start_coding_from_wrong_state(self, mock_init, client, db_session):
        """start-coding from PLANNING should return 400."""
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.PLANNING)
        db_session.add(t)
        await db_session.commit()

        resp = await client.post(f"/api/tasks/{t.id}/start-coding")
        assert resp.status_code == 400

    @_mock_bg
    async def test_start_review_incomplete_todos_returns_400(self, mock_init, client, db_session):
        """start-review with incomplete todos should return 400."""
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.CODING)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.PENDING)
        db_session.add(todo)
        await db_session.commit()

        resp = await client.post(f"/api/tasks/{t.id}/start-review")
        assert resp.status_code == 400
        assert "todos must be done" in resp.json()["detail"]

    @_mock_bg
    async def test_start_review_all_done_succeeds(self, mock_init, client, db_session):
        """start-review with all todos done should transition to REVIEWING."""
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.CODING)
        db_session.add(t)
        await db_session.flush()
        todo = Todo(task_id=t.id, seq=1, title="first", status=TodoStatus.DONE)
        db_session.add(todo)
        await db_session.commit()

        resp = await client.post(f"/api/tasks/{t.id}/start-review")
        assert resp.status_code == 200
        assert resp.json()["status"] == TaskStatus.REVIEWING

    @_mock_bg
    async def test_start_review_from_wrong_state(self, mock_init, client, db_session):
        """start-review from TODO_READY should return 400."""
        pid = await _create_project(client)
        t = Task(name="t", project_id=pid, status=TaskStatus.TODO_READY)
        db_session.add(t)
        await db_session.commit()

        resp = await client.post(f"/api/tasks/{t.id}/start-review")
        assert resp.status_code == 400
