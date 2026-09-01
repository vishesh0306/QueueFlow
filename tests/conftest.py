import os

import pytest
import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://queueflow:queueflow@localhost:5432/queueflow_test"
)
# A different Redis DB index than dev/prod (db 0) — tests must never share a queue with a
# real running worker process, or the two BLPOP/queue consumers race for the same jobs.
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1")

engine = create_engine(TEST_DATABASE_URL)
TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="session", autouse=True)
def _isolated_notification_queue():
    import notifications.service as notification_service

    original_client = notification_service._redis_client
    test_client = redis.Redis.from_url(TEST_REDIS_URL, socket_timeout=30)
    notification_service._redis_client = test_client
    yield
    test_client.flushdb()
    notification_service._redis_client = original_client


@pytest.fixture
def db():
    session = TestSessionLocal()
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    yield session
    session.close()
