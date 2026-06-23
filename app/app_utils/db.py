import json
import os
import sqlite3
from datetime import datetime

from google.cloud import storage

# Local SQLite DB location
DB_PATH = os.path.join(os.path.dirname(__file__), "newsletter.db")

_db_downloaded = False


def download_db_from_gcs(bucket_name: str):
    """Download newsletter.db from GCS to local DB_PATH."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob("database/newsletter.db")
    if blob.exists():
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        blob.download_to_filename(DB_PATH)
        print(f"Downloaded database from GCS to {DB_PATH}")


def upload_db_to_gcs(bucket_name: str):
    """Upload local newsletter.db to GCS."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob("database/newsletter.db")
    if os.path.exists(DB_PATH):
        blob.upload_from_filename(DB_PATH)
        print(f"Uploaded database to GCS from {DB_PATH}")



def get_db_connection():
    """Create a connection to the local SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the SQLite database schema."""
    global _db_downloaded
    bucket_name = os.environ.get("LOGS_BUCKET_NAME")
    if bucket_name and not _db_downloaded:
        try:
            download_db_from_gcs(bucket_name)
            _db_downloaded = True
        except Exception as e:
            print(f"Warning: Failed to download database from GCS: {e}")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Newsletters table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS newsletters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            title TEXT NOT NULL,
            html_content TEXT NOT NULL,
            papers_json TEXT NOT NULL
        )
    """)

    # Processed papers table to prevent duplicate curation
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_papers (
            arxiv_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            relevance_score REAL NOT NULL,
            added_at TEXT NOT NULL
        )
    """)

    # Subscribers table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            email TEXT PRIMARY KEY,
            subscribed_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active'
        )
    """)

    conn.commit()
    conn.close()


def save_newsletter(title: str, html_content: str, papers: list[dict]) -> int:
    """Save newsletter run to SQLite and optionally sync to GCS if configured."""
    init_db()
    date_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    papers_json = json.dumps(papers)

    # 1. Save locally to SQLite
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO newsletters (date, title, html_content, papers_json) VALUES (?, ?, ?, ?)",
        (date_str, title, html_content, papers_json),
    )
    newsletter_id = cursor.lastrowid

    # Mark papers as processed
    for paper in papers:
        cursor.execute(
            "INSERT OR IGNORE INTO processed_papers (arxiv_id, title, relevance_score, added_at) VALUES (?, ?, ?, ?)",
            (
                paper["arxiv_id"],
                paper["title"],
                paper.get("relevance_score", 0.0),
                date_str,
            ),
        )

    conn.commit()
    conn.close()

    # 2. Upload to GCS if running in production/GCP with bucket configured
    bucket_name = os.environ.get("LOGS_BUCKET_NAME")
    if bucket_name:
        try:
            upload_db_to_gcs(bucket_name)
            upload_newsletter_to_gcs(
                bucket_name, newsletter_id, date_str, title, html_content, papers
            )
        except Exception as e:
            print(f"Warning: Failed to sync newsletter {newsletter_id} or DB to GCS: {e}")

    return newsletter_id


def is_paper_processed(arxiv_id: str) -> bool:
    """Check if a paper has already been processed and curated."""
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM processed_papers WHERE arxiv_id = ?", (arxiv_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None


def clear_processed_papers_for_today():
    """Clear papers processed today (within the last 12 hours) to allow re-running."""
    init_db()
    from datetime import timedelta
    limit_str = (datetime.utcnow() - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM processed_papers WHERE added_at >= ?",
        (limit_str,),
    )
    conn.commit()
    conn.close()

    bucket_name = os.environ.get("LOGS_BUCKET_NAME")
    if bucket_name:
        try:
            upload_db_to_gcs(bucket_name)
        except Exception as e:
            print(f"Warning: Failed to upload database to GCS after clearing papers: {e}")


def add_subscriber(email: str) -> bool:
    """Add a new subscriber or reactivate an unsubscribed one."""
    init_db()
    date_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO subscribers (email, subscribed_at, status) VALUES (?, ?, 'active') "
            "ON CONFLICT(email) DO UPDATE SET status='active', subscribed_at=?",
            (email.strip().lower(), date_str, date_str),
        )
        conn.commit()
        bucket_name = os.environ.get("LOGS_BUCKET_NAME")
        if bucket_name:
            upload_db_to_gcs(bucket_name)
        return True
    except Exception as e:
        print(f"Error adding subscriber {email}: {e}")
        return False
    finally:
        conn.close()


def remove_subscriber(email: str) -> bool:
    """Mark a subscriber as unsubscribed."""
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE subscribers SET status='unsubscribed' WHERE email = ?",
            (email.strip().lower(),),
        )
        conn.commit()
        bucket_name = os.environ.get("LOGS_BUCKET_NAME")
        if bucket_name:
            upload_db_to_gcs(bucket_name)
        return True
    except Exception as e:
        print(f"Error removing subscriber {email}: {e}")
        return False
    finally:
        conn.close()


def get_active_subscribers() -> list[str]:
    """Retrieve all active subscriber email addresses."""
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT email FROM subscribers WHERE status = 'active'")
        rows = cursor.fetchall()
        return [row["email"] for row in rows]
    except Exception as e:
        print(f"Error listing subscribers: {e}")
        return []
    finally:
        conn.close()


def get_newsletters() -> list[dict]:
    """Retrieve all newsletters from local SQLite or fall back to GCS if SQLite is empty/not present."""
    # First check GCS if LOGS_BUCKET_NAME is set and SQLite is empty
    bucket_name = os.environ.get("LOGS_BUCKET_NAME")
    if bucket_name and not os.path.exists(DB_PATH):
        try:
            return get_newsletters_from_gcs(bucket_name)
        except Exception as e:
            print(f"Warning: Failed to load newsletters from GCS: {e}")

    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, date, title, html_content, papers_json FROM newsletters ORDER BY date DESC"
    )
    rows = cursor.fetchall()
    conn.close()

    newsletters = []
    for row in rows:
        newsletters.append(
            {
                "id": row["id"],
                "date": row["date"],
                "title": row["title"],
                "html_content": row["html_content"],
                "papers": json.loads(row["papers_json"]),
            }
        )
    return newsletters


def get_newsletter(newsletter_id: int) -> dict | None:
    """Get detailed view of a single newsletter."""
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, date, title, html_content, papers_json FROM newsletters WHERE id = ?",
        (newsletter_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "id": row["id"],
            "date": row["date"],
            "title": row["title"],
            "html_content": row["html_content"],
            "papers": json.loads(row["papers_json"]),
        }

    # Fallback to GCS
    bucket_name = os.environ.get("LOGS_BUCKET_NAME")
    if bucket_name:
        try:
            return get_newsletter_from_gcs(bucket_name, newsletter_id)
        except Exception as e:
            print(f"Warning: Failed to load newsletter {newsletter_id} from GCS: {e}")

    return None


# --- GCS Helper functions for Serverless / stateless deployment ---


def upload_newsletter_to_gcs(
    bucket_name: str,
    newsletter_id: int,
    date_str: str,
    title: str,
    html_content: str,
    papers: list[dict],
):
    """Sync newsletter assets and a metadata index file to Google Cloud Storage."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    # Save the rendered HTML file
    html_blob = bucket.blob(f"newsletters/{newsletter_id}.html")
    html_blob.upload_from_string(html_content, content_type="text/html")

    # Save paper metadata
    meta_blob = bucket.blob(f"newsletters/{newsletter_id}.json")
    metadata = {"id": newsletter_id, "date": date_str, "title": title, "papers": papers}
    meta_blob.upload_from_string(json.dumps(metadata), content_type="application/json")

    # Update GCS newsletters index
    index_blob = bucket.blob("newsletters/index.json")
    index_data = []
    if index_blob.exists():
        try:
            index_data = json.loads(index_blob.download_as_text())
        except Exception:
            pass

    index_data.insert(0, {"id": newsletter_id, "date": date_str, "title": title})
    index_blob.upload_from_string(
        json.dumps(index_data), content_type="application/json"
    )


def get_newsletters_from_gcs(bucket_name: str) -> list[dict]:
    """Retrieve newsletter index from GCS."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    index_blob = bucket.blob("newsletters/index.json")

    if not index_blob.exists():
        return []

    index_data = json.loads(index_blob.download_as_text())
    newsletters = []
    for item in index_data:
        # Load the HTML content
        html_blob = bucket.blob(f"newsletters/{item['id']}.html")
        html_content = html_blob.download_as_text() if html_blob.exists() else ""

        # Load papers list
        meta_blob = bucket.blob(f"newsletters/{item['id']}.json")
        papers = []
        if meta_blob.exists():
            try:
                papers = json.loads(meta_blob.download_as_text()).get("papers", [])
            except Exception:
                pass

        newsletters.append(
            {
                "id": item["id"],
                "date": item["date"],
                "title": item["title"],
                "html_content": html_content,
                "papers": papers,
            }
        )
    return newsletters


def get_newsletter_from_gcs(bucket_name: str, newsletter_id: int) -> dict | None:
    """Retrieve a single newsletter from GCS."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    meta_blob = bucket.blob(f"newsletters/{newsletter_id}.json")
    html_blob = bucket.blob(f"newsletters/{newsletter_id}.html")

    if not meta_blob.exists() or not html_blob.exists():
        return None

    meta = json.loads(meta_blob.download_as_text())
    html_content = html_blob.download_as_text()

    return {
        "id": newsletter_id,
        "date": meta["date"],
        "title": meta["title"],
        "html_content": html_content,
        "papers": meta.get("papers", []),
    }
