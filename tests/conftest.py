"""
Test configuration and fixtures.

Unit/integration tests use SQLite in-memory database and stub out
RabbitMQ, Kafka, and Redis so tests run without Docker.
"""
import asyncio
import os
import sys
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

# Add api directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

# Override settings BEFORE importing any app modules
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_tin4.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["RABBITMQ_URL"] = "amqp://guest:guest@localhost:5672/"
os.environ["REDPANDA_BROKERS"] = "localhost:9092"
os.environ["JWT_SECRET"] = "test_secret_key"
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ["JWT_EXPIRE_MINUTES"] = "60"


def _make_redis_mock():
    m = AsyncMock()
    m.exists = AsyncMock(return_value=0)
    m.setex = AsyncMock(return_value=True)
    m.delete = AsyncMock(return_value=1)
    m.publish = AsyncMock(return_value=1)
    return m


@pytest_asyncio.fixture(scope="function")
async def app_client() -> AsyncGenerator:
    """Create a test FastAPI client with a fresh SQLite database."""
    redis_mock = _make_redis_mock()

    with (
        patch("rabbitmq_client.publish", new=AsyncMock(return_value=None)),
        patch("kafka_client.produce", new=AsyncMock(return_value=None)),
        patch("ws_manager.redis_pubsub_listener", new=AsyncMock(return_value=None)),
        patch("ws_manager.send_to_user", new=AsyncMock(return_value=None)),
    ):
        # Import app and db modules inside patch context
        from main import app
        from database import get_db
        from models import Base
        from redis_client import get_redis

        # Build a fresh SQLite engine per test
        test_engine = create_async_engine(
            "sqlite+aiosqlite:///./test_tin4_func.db",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

        async def override_get_db():
            async with test_session_factory() as session:
                yield session

        async def override_get_redis():
            return redis_mock

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_redis] = override_get_redis

        # Patch the module-level session factory used by GraphQL resolvers
        import graphql_schema
        original_session_factory = graphql_schema.AsyncSessionLocal
        graphql_schema.AsyncSessionLocal = test_session_factory

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client

        graphql_schema.AsyncSessionLocal = original_session_factory
        app.dependency_overrides.clear()
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await test_engine.dispose()

    # Clean up test db files
    for f in ["test_tin4_func.db", "test_tin4.db"]:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass
