import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_ready_is_ok_when_database_is_reachable(db_client: TestClient) -> None:
    response = db_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}
