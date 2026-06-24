import os
import sqlite3
import shutil
import sys

# Ensure absolute imports work by adding project root
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.append(project_root)

from google.cloud import storage
from app.app_utils.db import DB_PATH, upload_db_to_gcs


def reset_local_archives():
    archives_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "archives"
    )
    print(f"Clearing local archives in: {archives_dir}")
    if os.path.exists(archives_dir):
        for filename in os.listdir(archives_dir):
            file_path = os.path.join(archives_dir, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    if filename.endswith(".html"):
                        os.unlink(file_path)
                        print(f"Deleted local file: {filename}")
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                    print(f"Deleted local dir: {filename}")
            except Exception as e:
                print(f"Failed to delete {file_path}. Reason: {e}")


def reset_sqlite_db():
    print(f"Clearing SQLite tables in: {DB_PATH}")
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()

            # Truncate tables
            cursor.execute("DELETE FROM newsletters")
            cursor.execute("DELETE FROM processed_papers")
            conn.commit()

            # Set autocommit mode to run VACUUM
            conn.isolation_level = None
            cursor.execute("VACUUM")

            print("SQLite tables cleared and vacuumed successfully.")
        except Exception as e:
            print(f"Error resetting database tables: {e}")
        finally:
            conn.close()
    else:
        print("Database file does not exist locally.")


def reset_gcs_archives(bucket_name: str):
    print(f"Clearing GCS blobs in bucket: {bucket_name}")
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)

        # List and delete all blobs under newsletters/
        blobs = bucket.list_blobs(prefix="newsletters/")
        count = 0
        for blob in blobs:
            print(f"Deleting GCS blob: {blob.name}")
            blob.delete()
            count += 1
        print(f"Deleted {count} blobs from GCS.")

        # Upload the cleared SQLite DB file
        upload_db_to_gcs(bucket_name)
    except Exception as e:
        print(f"Error clearing GCS archives: {e}")


if __name__ == "__main__":
    reset_local_archives()
    reset_sqlite_db()

    bucket_name = os.environ.get("LOGS_BUCKET_NAME")
    if bucket_name:
        reset_gcs_archives(bucket_name)
    else:
        print("LOGS_BUCKET_NAME environment variable not set. Skipping GCS cleanup.")
