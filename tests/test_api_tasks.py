"""Tests for tasks API endpoints."""

from unittest.mock import AsyncMock, patch


async def _create_project(client):
    resp = await client.post("/api/projects", json={"name": "TestProj"})
    return resp.json()["id"]


# Mock init_task/generate_plan/generate_todos since they require Cody SDK
_mock_bg = patch("daiflow.routers.tasks.init_task", new_callable=AsyncMock)
_mock_bg2 = patch("daiflow.routers.tasks.generate_plan", new_callable=AsyncMock)
_mock_bg3 = patch("daiflow.routers.tasks.generate_todos", new_callable=AsyncMock)


class TestTasksCRUD:
    @_mock_bg
    async def test_list_tasks_empty(self, mock_init, client):
        resp = await client.get("/api/tasks")
        assert resp.status_code == 200
        assert resp.json() == []

    @_mock_bg
    async def test_create_task(self, mock_init, client):
        pid = await _create_project(client)
        resp = await client.post("/api/tasks", json={
            "name": "Task 1",
            "project_id": pid,
            "description": "Test task",
            "branch": "feature/test",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Task 1"
        assert data["project_id"] == pid
        assert data["branch"] == "feature/test"
        assert data["status"] == 0  # CREATED

    @_mock_bg
    async def test_get_task(self, mock_init, client):
        pid = await _create_project(client)
        create_resp = await client.post("/api/tasks", json={
            "name": "Task 1", "project_id": pid,
        })
        tid = create_resp.json()["id"]

        resp = await client.get(f"/api/tasks/{tid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Task 1"

    @_mock_bg
    async def test_get_task_not_found(self, mock_init, client):
        resp = await client.get("/api/tasks/nonexistent")
        assert resp.status_code == 404

    @_mock_bg
    async def test_update_task(self, mock_init, client):
        pid = await _create_project(client)
        create_resp = await client.post("/api/tasks", json={
            "name": "Task 1", "project_id": pid,
        })
        tid = create_resp.json()["id"]

        resp = await client.put(f"/api/tasks/{tid}", json={
            "name": "Updated Task",
            "description": "New description",
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Task"
        assert resp.json()["description"] == "New description"

    @_mock_bg
    async def test_update_task_not_found(self, mock_init, client):
        resp = await client.put("/api/tasks/nonexistent", json={"name": "x"})
        assert resp.status_code == 404

    @_mock_bg
    async def test_delete_task(self, mock_init, client):
        pid = await _create_project(client)
        create_resp = await client.post("/api/tasks", json={
            "name": "Task 1", "project_id": pid,
        })
        tid = create_resp.json()["id"]

        resp = await client.delete(f"/api/tasks/{tid}")
        assert resp.status_code == 200

        resp = await client.get(f"/api/tasks/{tid}")
        assert resp.status_code == 404

    @_mock_bg
    async def test_list_tasks_by_project(self, mock_init, client):
        pid1 = await _create_project(client)
        resp2 = await client.post("/api/projects", json={"name": "Proj2"})
        pid2 = resp2.json()["id"]

        await client.post("/api/tasks", json={"name": "T1", "project_id": pid1})
        await client.post("/api/tasks", json={"name": "T2", "project_id": pid2})

        resp = await client.get(f"/api/tasks?project_id={pid1}")
        tasks = resp.json()
        assert len(tasks) == 1
        assert tasks[0]["name"] == "T1"

    @_mock_bg
    async def test_get_todos_empty(self, mock_init, client):
        pid = await _create_project(client)
        create_resp = await client.post("/api/tasks", json={
            "name": "Task 1", "project_id": pid,
        })
        tid = create_resp.json()["id"]

        resp = await client.get(f"/api/tasks/{tid}/todos")
        assert resp.status_code == 200
        assert resp.json() == []

    @_mock_bg
    async def test_create_task_with_prd(self, mock_init, client):
        pid = await _create_project(client)
        resp = await client.post("/api/tasks", json={
            "name": "Task with PRD",
            "project_id": pid,
            "prd": "# Requirements\n- Feature A\n- Feature B",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["prd"] == "# Requirements\n- Feature A\n- Feature B"


class TestStageTransitions:
    @_mock_bg
    async def test_lock_plan_invalid_from_created(self, mock_init, client):
        """Cannot lock plan when task is in CREATED status."""
        pid = await _create_project(client)
        create_resp = await client.post("/api/tasks", json={
            "name": "Task 1", "project_id": pid,
        })
        tid = create_resp.json()["id"]

        # Task is in CREATED (0), lock-plan requires PLANNING (2)
        resp = await client.post(f"/api/tasks/{tid}/lock-plan")
        assert resp.status_code == 400
        assert "Cannot transition" in resp.json()["detail"]

    @_mock_bg
    async def test_lock_plan_invalid_from_initializing(self, mock_init, client, db_session):
        """Cannot lock plan when task is in INITIALIZING status."""
        pid = await _create_project(client)
        create_resp = await client.post("/api/tasks", json={
            "name": "Task 1", "project_id": pid,
        })
        tid = create_resp.json()["id"]

        from daiflow.models import Task, TaskStatus
        task = await db_session.get(Task, tid)
        task.status = TaskStatus.INITIALIZING
        await db_session.commit()

        resp = await client.post(f"/api/tasks/{tid}/lock-plan")
        assert resp.status_code == 400
        assert "Cannot transition" in resp.json()["detail"]

    async def test_start_review_not_found(self, client):
        resp = await client.post("/api/tasks/nonexistent/start-review")
        assert resp.status_code == 404

    async def test_start_coding_not_found(self, client):
        resp = await client.post("/api/tasks/nonexistent/start-coding")
        assert resp.status_code == 404

    @_mock_bg
    @_mock_bg3
    async def test_lock_plan_valid(self, mock_todos, mock_init, client, db_session):
        """Lock plan when task is in PLANNING status."""
        pid = await _create_project(client)
        create_resp = await client.post("/api/tasks", json={
            "name": "Task 1", "project_id": pid,
        })
        tid = create_resp.json()["id"]

        # Manually set task to PLANNING status
        from daiflow.models import Task, TaskStatus
        task = await db_session.get(Task, tid)
        task.status = TaskStatus.PLANNING
        await db_session.commit()

        resp = await client.post(f"/api/tasks/{tid}/lock-plan")
        assert resp.status_code == 200
        assert resp.json()["status"] == TaskStatus.PLAN_LOCKED


class TestGenerateCommitMessage:
    @_mock_bg
    async def test_not_found(self, mock_init, client):
        resp = await client.post("/api/tasks/nonexistent/generate-commit-message")
        assert resp.status_code == 404

    @_mock_bg
    async def test_no_diff_returns_fallback(self, mock_init, client):
        """When there are no diffs, return a fallback commit message."""
        pid = await _create_project(client)
        create_resp = await client.post("/api/tasks", json={
            "name": "My Feature", "project_id": pid,
        })
        tid = create_resp.json()["id"]

        resp = await client.post(f"/api/tasks/{tid}/generate-commit-message")
        assert resp.status_code == 200
        data = resp.json()
        assert "commit_message" in data
        assert "My Feature" in data["commit_message"]


class TestInitTaskTransition:
    async def test_init_task_sets_initializing_then_planning(self, db_session):
        """init_task should transition CREATED → INITIALIZING → PLANNING."""
        from daiflow.models import Project, ProjectRepo, Task, TaskStatus

        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="task", project_id=p.id, status=TaskStatus.CREATED, branch="main")
        db_session.add(t)
        await db_session.commit()
        task_id = t.id

        # Mock generate_plan since it requires Cody SDK
        with patch("daiflow.services.task_service.generate_plan", new_callable=AsyncMock) as mock_plan, \
             patch("daiflow.services.task_service.sync_skills_to_task"):
            from daiflow.services.task_service import init_task

            # We need to patch get_background_db to return our test session
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def mock_bg_db():
                yield db_session

            with patch("daiflow.services.task_service.get_background_db", mock_bg_db):
                await init_task(task_id)

            # After init_task, status should be PLANNING (set before generate_plan call)
            await db_session.refresh(t)
            assert t.status == TaskStatus.PLANNING

            # generate_plan should have been called
            mock_plan.assert_awaited_once_with(task_id)
