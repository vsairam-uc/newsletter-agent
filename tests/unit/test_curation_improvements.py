from unittest.mock import MagicMock, patch
import pytest
from google.adk.agents.context import Context
from app.agent import relevance_filter
from app.app_utils.scraper import search_classic_arxiv_papers


def test_search_classic_arxiv_papers():
    """Verify that search_classic_arxiv_papers retrieves papers and tags them with is_classic=True."""
    with patch("arxiv.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # Mock result returned by arXiv client
        mock_result = MagicMock()
        mock_result.entry_id = "https://export.arxiv.org/abs/1706.03762v5"
        mock_result.title = "Attention Is All You Need"
        mock_result.summary = "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks..."
        mock_result.authors = [MagicMock(name="Vaswani")]
        mock_result.pdf_url = "https://arxiv.org/pdf/1706.03762v5"
        mock_result.published = MagicMock()
        mock_result.published.isoformat.return_value = "2017-06-12T00:00:00"
        
        mock_client.results.return_value = [mock_result]
        
        papers = search_classic_arxiv_papers(max_results=1)
        
        assert len(papers) == 1
        assert papers[0]["arxiv_id"] == "1706.03762"
        assert papers[0]["title"] == "Attention Is All You Need"
        assert papers[0]["is_classic"] is True


@patch("app.agent.is_paper_processed", return_value=False)
@patch("app.agent.search_arxiv_papers")
@patch("app.agent.search_classic_arxiv_papers")
@patch("app.agent.score_paper_relevance")
def test_relevance_filter_fallback_mechanism(
    mock_score, mock_classic, mock_recent, mock_processed
):
    """Test that relevance_filter uses the fallback mechanism to return at least 3 papers."""
    # 1. Setup mock recent papers (2 papers)
    mock_recent.return_value = [
        {"arxiv_id": "recent-1", "title": "Recent Paper 1", "summary": "Summary 1", "authors": ["A"], "pdf_url": "url", "published": "2026-06-20"},
        {"arxiv_id": "recent-2", "title": "Recent Paper 2", "summary": "Summary 2", "authors": ["B"], "pdf_url": "url", "published": "2026-06-21"},
    ]
    
    # 2. Setup mock classic papers (1 paper)
    mock_classic.return_value = [
        {"arxiv_id": "classic-1", "title": "Classic Paper 1", "summary": "Summary 3", "authors": ["C"], "pdf_url": "url", "published": "2017-06-12", "is_classic": True}
    ]
    
    # 3. Setup mock scoring:
    # Let's say none of the recent papers meet the 0.65 threshold (scores: 0.50, 0.40)
    # The classic paper does not meet the 0.60 threshold either (score: 0.55)
    
    class MockScoreResult:
        def __init__(self, score, reason=""):
            self.relevance_score = score
            self.reason = reason

    def side_effect_score(title, abstract, profile):
        if "Recent Paper 1" in title:
            return MockScoreResult(0.50)
        elif "Recent Paper 2" in title:
            return MockScoreResult(0.40)
        elif "Classic Paper 1" in title:
            return MockScoreResult(0.55)
        return MockScoreResult(0.0)
        
    mock_score.side_effect = side_effect_score
    
    # Create mock context
    mock_ctx = MagicMock(spec=Context)
    mock_ctx.state = {"interest_profile": "AI topics"}
    
    # Run relevance filter
    result_papers = relevance_filter._func(mock_ctx, None)
    
    # The filter must fallback and include all 3 papers to satisfy minimum 3 papers rule
    assert len(result_papers) == 3
    # Check that they are sorted/included properly
    titles = [p["title"] for p in result_papers]
    assert "Recent Paper 1" in titles
    assert "Recent Paper 2" in titles
    assert "Classic Paper 1" in titles
