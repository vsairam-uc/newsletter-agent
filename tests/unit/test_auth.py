import os
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.fast_api_app import app

client = TestClient(app)


def test_subscribers_endpoint_auth_missing():
    """Verify that calling /api/subscribers without a token returns 401 Unauthorized."""
    response = client.get("/api/subscribers")
    assert response.status_code == 401
    assert "Not authenticated" in response.text


def test_subscribers_endpoint_auth_invalid():
    """Verify that calling /api/subscribers with an invalid token returns 401 Unauthorized."""
    with patch.dict(os.environ, {"ADMIN_API_KEY": "supersecret"}):
        response = client.get(
            "/api/subscribers",
            headers={"Authorization": "Bearer wrongtoken"}
        )
        assert response.status_code == 401
        assert "Unauthorized" in response.text


def test_subscribers_endpoint_auth_valid():
    """Verify that calling /api/subscribers with a valid token returns 200 OK."""
    with patch.dict(os.environ, {"ADMIN_API_KEY": "supersecret"}):
        with patch("app.fast_api_app.get_active_subscribers", return_value=["test@example.com"]):
            response = client.get(
                "/api/subscribers",
                headers={"Authorization": "Bearer supersecret"}
            )
            assert response.status_code == 200
            assert response.json() == {
                "status": "success",
                "subscribers": ["test@example.com"]
            }


def test_trigger_endpoint_auth_missing():
    """Verify that calling /api/trigger without a token returns 401 Unauthorized."""
    response = client.post("/api/trigger")
    assert response.status_code == 401
    assert "Not authenticated" in response.text


def test_trigger_endpoint_auth_invalid():
    """Verify that calling /api/trigger with an invalid token returns 401 Unauthorized."""
    with patch.dict(os.environ, {"ADMIN_API_KEY": "supersecret"}):
        response = client.post(
            "/api/trigger",
            headers={"Authorization": "Bearer wrongtoken"}
        )
        assert response.status_code == 401
        assert "Unauthorized" in response.text
