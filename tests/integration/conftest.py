import pytest
from fastapi.testclient import TestClient

import main
from db.session import get_db
from tests.conftest import TestSessionLocal
from ws.gateway import manager


@pytest.fixture
def client(db):
    def _override_get_db():
        yield db

    main.app.dependency_overrides[get_db] = _override_get_db

    original_session_factory = manager._session_factory
    manager._session_factory = TestSessionLocal

    yield TestClient(main.app)

    main.app.dependency_overrides.clear()
    manager._session_factory = original_session_factory
