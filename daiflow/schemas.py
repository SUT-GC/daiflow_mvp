"""Pydantic response models for API endpoints."""

import json

from pydantic import BaseModel, ConfigDict, field_validator


class RepoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    git_url: str
    local_path: str
    repo_type: str
    repo_type_label: str
    description: str


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
        if isinstance(v, str):
            return json.loads(v) if v else []
        return v

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def serialize_datetime(cls, v):
        if v is None:
            return None
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return v


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    project_id: str
    description: str
    branch: str
    prd: str
    tech_plan: str
    status: int
    mr_info: dict = {}
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("mr_info", mode="before")
    @classmethod
    def parse_mr_info(cls, v):
        if isinstance(v, str):
            return json.loads(v) if v else {}
        return v

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def serialize_datetime(cls, v):
        if v is None:
            return None
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return v


class TodoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    seq: int
    title: str
    description: str
    status: int
    cody_session_id: str | None = None


class SessionStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
        if v is None:
            return None
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return v
