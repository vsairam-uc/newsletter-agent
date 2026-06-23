import sqlite3
from datetime import datetime, timedelta
from app.app_utils.db import (
    get_db_connection,
    init_db,
    is_paper_processed,
    clear_processed_papers_for_today,
)


def test_clear_processed_papers_for_today():
    """Test that clear_processed_papers_for_today correctly removes today's papers but leaves older ones."""
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()

    # Clear everything first for clean test
    cursor.execute("DELETE FROM processed_papers")
    conn.commit()

    # Insert a paper processed today
    today_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO processed_papers (arxiv_id, title, relevance_score, added_at) VALUES (?, ?, ?, ?)",
        ("arxiv-today-1", "Today Paper", 0.9, today_str),
    )

    # Insert a paper processed yesterday
    yesterday_str = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO processed_papers (arxiv_id, title, relevance_score, added_at) VALUES (?, ?, ?, ?)",
        ("arxiv-yesterday-1", "Yesterday Paper", 0.8, yesterday_str),
    )
    conn.commit()
    conn.close()

    # Verify both exist
    assert is_paper_processed("arxiv-today-1") is True
    assert is_paper_processed("arxiv-yesterday-1") is True

    # Call clear today's papers
    clear_processed_papers_for_today()

    # Verify today's is cleared, but yesterday's is still there
    assert is_paper_processed("arxiv-today-1") is False
    assert is_paper_processed("arxiv-yesterday-1") is True

    # Clean up
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM processed_papers WHERE arxiv_id = ?", ("arxiv-yesterday-1",))
    conn.commit()
    conn.close()
