"""Tests for daiflow.models module."""

from daiflow.models import (
    Base,
    Project,
    ProjectRepo,
    Session,
    SessionStatus,
    Setting,
    Task,
    TaskStatus,
    Todo,
    TodoStatus,
    _now,
    _uuid,
)


class TestEnums:
    def test_task_status_values(self):
        assert TaskStatus.CREATED == 0
        assert TaskStatus.INITIALIZING == 1
        assert TaskStatus.PLANNING == 2
        assert TaskStatus.PLAN_LOCKED == 3
        assert TaskStatus.TODO_READY == 4
        assert TaskStatus.CODING == 5
        assert TaskStatus.REVIEWING == 6
        assert TaskStatus.DONE == 7

    def test_todo_status_values(self):
        assert TodoStatus.PENDING == 0
        assert TodoStatus.RUNNING == 1
        assert TodoStatus.DONE == 2
        assert TodoStatus.FAILED == 3

    def test_session_status_values(self):
        assert SessionStatus.WAITING == 0
        assert SessionStatus.RUNNING == 1
        assert SessionStatus.DONE == 2
        assert SessionStatus.FAILED == 3


class TestHelpers:
    def test_uuid_uniqueness(self):
        ids = {_uuid() for _ in range(100)}
        assert len(ids) == 100

    def test_uuid_is_hex(self):
        uid = _uuid()
        assert len(uid) == 32
        int(uid, 16)  # Should not raise

    def test_now_has_timezone(self):
        dt = _now()
        assert dt.tzinfo is not None


class TestModelCreation:
    async def test_create_project(self, db_session):
        p = Project(name="test", description="desc")
        db_session.add(p)
        await db_session.commit()

        loaded = await db_session.get(Project, p.id)
        assert loaded is not None
        assert loaded.name == "test"
        assert loaded.description == "desc"
        assert loaded.created_at is not None

    async def test_create_task_with_defaults(self, db_session):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()

        t = Task(name="task1", project_id=p.id)
        db_session.add(t)
        await db_session.commit()

        loaded = await db_session.get(Task, t.id)
        assert loaded.status == 0
        assert loaded.description == ""
        assert loaded.branch == ""

    async def test_create_todo(self, db_session):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()
        t = Task(name="task1", project_id=p.id)
        db_session.add(t)
        await db_session.flush()

        todo = Todo(task_id=t.id, seq=1, title="First", description="Do first thing")
        db_session.add(todo)
        await db_session.commit()

        loaded = await db_session.get(Todo, todo.id)
        assert loaded.seq == 1
        assert loaded.title == "First"
        assert loaded.status == 0  # PENDING

    async def test_create_session(self, db_session):
        s = Session(session_id="task:1:plan", type="plan", ref_id="1")
        db_session.add(s)
        await db_session.commit()

        loaded = await db_session.get(Session, "task:1:plan")
        assert loaded is not None
        assert loaded.type == "plan"
        assert loaded.status == 0  # WAITING
        assert loaded.layer is None

    async def test_cascade_delete_project(self, db_session):
        p = Project(name="proj")
        db_session.add(p)
        await db_session.flush()

        repo = ProjectRepo(project_id=p.id, git_url="https://github.com/test/repo", repo_type="backend")
        db_session.add(repo)
        t = Task(name="task1", project_id=p.id)
        db_session.add(t)
        await db_session.commit()

        repo_id = repo.id
        task_id = t.id

        await db_session.delete(p)
        await db_session.commit()

        assert await db_session.get(ProjectRepo, repo_id) is None
        assert await db_session.get(Task, task_id) is None

    async def test_setting_key_value(self, db_session):
        s = Setting(key="cody_model", value="claude-opus-4-6")
        db_session.add(s)
        await db_session.commit()

        loaded = await db_session.get(Setting, "cody_model")
        assert loaded.value == "claude-opus-4-6"
