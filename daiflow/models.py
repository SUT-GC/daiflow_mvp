import uuid
from datetime import datetime, timezone
from enum import IntEnum

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class TaskStatus(IntEnum):
    CREATED = 0
    INITIALIZING = 1
    PLANNING = 2
    PLAN_LOCKED = 3
    TODO_READY = 4
    CODING = 5
    REVIEWING = 6
    DONE = 7


class TodoStatus(IntEnum):
    PENDING = 0
    RUNNING = 1
    DONE = 2
    FAILED = 3


class SessionStatus(IntEnum):
    WAITING = 0
    RUNNING = 1
    DONE = 2
    FAILED = 3


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    skill_names = Column(Text, default="[]")  # JSON array
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    repos = relationship("ProjectRepo", back_populates="project", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="project", cascade="all, delete-orphan")


class ProjectRepo(Base):
    __tablename__ = "project_repos"

    id = Column(String, primary_key=True, default=_uuid)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    git_url = Column(String, default="")
    local_path = Column(String, default="")
    repo_type = Column(String, default="custom")  # frontend / backend / custom
    repo_type_label = Column(String, default="")
    description = Column(Text, default="")
    created_at = Column(DateTime, default=_now)

    project = relationship("Project", back_populates="repos")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    description = Column(Text, default="")
    branch = Column(String, default="")
    prd = Column(Text, default="")
    tech_plan = Column(Text, default="")
    status = Column(Integer, default=0)  # 0=created..7=done
    plan_cody_session_id = Column(String, nullable=True)
    review_cody_session_id = Column(String, nullable=True)
    mr_info = Column(Text, default="{}")  # JSON
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    project = relationship("Project", back_populates="tasks")
    todos = relationship("Todo", back_populates="task", cascade="all, delete-orphan")


class Todo(Base):
    __tablename__ = "todos"

    id = Column(String, primary_key=True, default=_uuid)
    task_id = Column(String, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    title = Column(String, default="")
    description = Column(Text, default="")
    status = Column(Integer, default=0)  # 0=pending,1=running,2=done,3=failed
    cody_session_id = Column(String, nullable=True)
    result = Column(Text, default="")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    task = relationship("Task", back_populates="todos")


class Session(Base):
    __tablename__ = "sessions"

    session_id = Column(String, primary_key=True)  # business ID like task:42:plan
    cody_session_id = Column(String, nullable=True)
    type = Column(String, nullable=False)  # init/plan/todo_split/todo_exec/review
    ref_id = Column(String, default="", index=True)
    layer = Column(Integer, nullable=True)  # 1-4 for init, NULL otherwise
    status = Column(Integer, default=0)  # 0=waiting,1=running,2=done,3=failed
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(Text, default="")
    updated_at = Column(DateTime, default=_now, onupdate=_now)
