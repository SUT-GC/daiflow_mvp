from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from daiflow.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    from daiflow.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with async_session() as session:
        yield session


@asynccontextmanager
async def get_background_db():
    """Create an independent DB session for background tasks.

    Background tasks must NOT use the request-scoped session from get_db()
    because it is closed after the request completes.
    """
    async with async_session() as session:
        yield session
