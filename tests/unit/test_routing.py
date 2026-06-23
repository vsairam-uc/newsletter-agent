from unittest.mock import patch
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


def test_pagination_logic():
    """Verify that the / and /test routes paginate their results correctly."""
    # Mocking get_newsletters to return 12 dummy newsletters
    mock_newsletters = [
        {
            "id": i,
            "date": f"2026-06-{i:02d} 10:00:00",
            "title": f"Newsletter {i}",
            "html_content": "<p>Content</p>",
            "papers": [{"title": f"Paper {i}.{j}", "arxiv_id": f"id-{i}-{j}"} for j in range(3)],
        }
        for i in range(1, 13)
    ]

    with patch("app.fast_api_app.get_newsletters", return_value=mock_newsletters):
        # 1. Request first page of / (should return newsletters 1 to 5)
        response = client.get("/")
        assert response.status_code == 200
        # Check that page 1 has Newsletter 1 and 5, but not 6 or 12
        assert "Newsletter 1" in response.text
        assert "Newsletter 5" in response.text
        assert "Newsletter 6" not in response.text
        # Check that pagination controls show "Page 1 of 3"
        assert "Page 1 of 3" in response.text
        # Check that "Previous" is disabled and "Next" is enabled
        assert "Previous" in response.text
        assert "class=\"btn-pagination disabled\">&larr; Previous" in response.text
        assert "class=\"btn-pagination\">Next &rarr;" in response.text

        # 2. Request second page (should return newsletters 6 to 10)
        response = client.get("/?page=2")
        assert response.status_code == 200
        assert "Newsletter 5" not in response.text
        assert "Newsletter 6" in response.text
        assert "Newsletter 10" in response.text
        assert "Newsletter 11" not in response.text
        assert "Page 2 of 3" in response.text
        # "Previous" and "Next" should both be enabled
        assert "class=\"btn-pagination\">&larr; Previous" in response.text
        assert "class=\"btn-pagination\">Next &rarr;" in response.text

        # 3. Request third page (should return newsletters 11 and 12)
        response = client.get("/?page=3")
        assert response.status_code == 200
        assert "Newsletter 10" not in response.text
        assert "Newsletter 11" in response.text
        assert "Newsletter 12" in response.text
        assert "Page 3 of 3" in response.text
        # "Previous" is enabled, "Next" is disabled
        assert "class=\"btn-pagination\">&larr; Previous" in response.text
        assert "class=\"btn-pagination disabled\">Next &rarr;" in response.text
        
        # 4. Verify same functionality on /test
        response_test = client.get("/test?page=2")
        assert response_test.status_code == 200
        assert 'id="trigger-curation-btn"' in response_test.text
        assert "Page 2 of 3" in response_test.text
