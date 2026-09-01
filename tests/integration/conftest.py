import pytest
from fastapi.testclient import TestClient

import main
from db.session import get_db


@pytest.fixture
def client(db):
    def _override_get_db():
        yield db

    main.app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()
