"""Shared test fixtures for DaiFlow backend tests."""

import os
import tempfile
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Override DAIFLOW_HOME before any daiflow import to use a temp directory
_tmpdir = tempfile.mkdtemp(prefix="daiflow_test_")
os.environ["DAIFLOW_HOME"] = _tmpdir

from daiflow.models import Base  # noqa: E402


@pytest_asyncio.fixture
async def db_engine():
    """Create an in-memory async SQLite engine with all tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Create an async DB session for testing."""
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_engine):
    """Create an HTTPX AsyncClient connected to the FastAPI app with test DB."""
    from daiflow.database import get_db
    from daiflow.main import app

    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    @asynccontextmanager
    async def override_get_background_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # Patch get_background_db so background tasks also use the test DB
    with patch("daiflow.database.get_background_db", override_get_background_db), \
         patch("daiflow.services.task_service.get_background_db", override_get_background_db), \
         patch("daiflow.services.project_service.get_background_db", override_get_background_db):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()
