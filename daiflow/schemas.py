"""Pydantic response/request models for API endpoints."""

import json
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


def _serialize_dt(v):
    """Convert datetime objects to ISO strings for JSON serialization.

    Appends 'Z' for UTC datetimes so JavaScript parses them correctly
    (without 'Z', JS treats ISO strings as local time).
    """
    if v is None:
        return None
    if isinstance(v, datetime):
        s = v.isoformat()
        if s.endswith("+00:00"):
            return s[:-6] + "Z"
        if v.tzinfo is None:
            return s + "Z"
        return s
    return v


def _parse_json_str(v, default):
    """Parse a JSON string, returning default if empty."""
    if isinstance(v, str):
        return json.loads(v) if v else default
    return v


class _ORMBase(BaseModel):
    """Base for ORM-backed response models with automatic datetime serialization."""
    model_config = ConfigDict(from_attributes=True)


# ── Response Models ──


class RepoResponse(_ORMBase):
    id: str
    git_url: str
    local_path: str
    repo_type: str
    repo_type_label: str
    description: str


class ProjectResponse(_ORMBase):
    id: str
    name: str
    description: str
    skill_names: list[str] = []
    repos: list[RepoResponse] = []
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("skill_names", mode="before")
    @classmethod
    def parse_skill_names(cls, v):
        return _parse_json_str(v, [])

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def serialize_datetime(cls, v):
        return _serialize_dt(v)


class TaskResponse(_ORMBase):
    id: str
    name: str
    project_id: str
    description: str
    branch: str
    prd: str
    prd_images: list[str] = []
    tech_plan: str
    status: int
    mr_info: dict | list = {}
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("prd_images", mode="before")
    @classmethod
    def parse_prd_images(cls, v):
        return _parse_json_str(v, [])

    @field_validator("mr_info", mode="before")
    @classmethod
    def parse_mr_info(cls, v):
        return _parse_json_str(v, {})

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def serialize_datetime(cls, v):
        return _serialize_dt(v)


class TodoResponse(_ORMBase):
    id: str
    seq: int
    title: str
    description: str
    status: int
    cody_session_id: str | None = None


class SessionStatusResponse(_ORMBase):
    session_id: str
    cody_session_id: str | None = None
    type: str
    ref_id: str
    layer: int | None = None
    status: int
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    @field_validator("started_at", "finished_at", mode="before")
    @classmethod
    def serialize_datetime(cls, v):
        return _serialize_dt(v)


# ── Request Models ──


class RepoCreate(BaseModel):
    git_url: str = ""
    local_path: str = ""
    repo_type: str = "custom"
    repo_type_label: str = ""
    description: str = ""


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    repos: list[RepoCreate] = []
    skill_names: list[str] = []


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    repos: list[RepoCreate] | None = None
    skill_names: list[str] | None = None


# Valid git branch name: starts with word char, allows word chars, dots, slashes, hyphens
_BRANCH_RE = re.compile(r'^[\w][\w./-]*$')


class TaskCreate(BaseModel):
    name: str
    project_id: str
    description: str = ""
    branch: str = ""
    prd: str = ""
    tech_plan: str = ""

    @field_validator("branch")
    @classmethod
    def validate_branch(cls, v: str) -> str:
        if not v:
            return v  # Empty branch is allowed (optional)
        if not _BRANCH_RE.match(v) or '..' in v or v.endswith('.lock') or v.endswith('/'):
            raise ValueError(f"Invalid branch name: {v!r}")
        return v


class TaskUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    branch: str | None = None
    prd: str | None = None
    tech_plan: str | None = None

    @field_validator("branch")
    @classmethod
    def validate_branch(cls, v: str | None) -> str | None:
        if v is None or not v:
            return v
        if not _BRANCH_RE.match(v) or '..' in v or v.endswith('.lock') or v.endswith('/'):
            raise ValueError(f"Invalid branch name: {v!r}")
        return v


class SettingsUpdate(BaseModel):
    cody_model: str | None = None
    cody_base_url: str | None = None
    cody_api_key: str | None = None
    theme: str | None = None
    language: str | None = None


class ConnectionTest(BaseModel):
    cody_model: str
    cody_base_url: str
    cody_api_key: str


class SubmitMR(BaseModel):
    commit_message: str = ""
