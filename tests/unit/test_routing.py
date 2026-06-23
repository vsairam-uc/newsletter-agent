from fastapi.testclient import TestClient
from app.fast_api_app import app

client = TestClient(app)


def test_routes_trigger_button_visibility():
    """Verify that the trigger button is hidden on / and visible on /test."""
    # 1. Landing page route /
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="trigger-curation-btn"' not in response.text

    # 2. Test page route /test
    response = client.get("/test")
    assert response.status_code == 200
    assert 'id="trigger-curation-btn"' in response.text
