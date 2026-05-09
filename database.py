import sqlite3
import time
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    file_hash TEXT UNIQUE NOT NULL,
    sd_path TEXT NOT NULL,
    cache_path TEXT,
    remote_path TEXT,
    size_bytes INTEGER NOT NULL,
    mtime REAL NOT NULL,
    cached_at REAL,
    uploaded_at REAL,
    pruned_at REAL,
    upload_error TEXT,
    upload_attempts INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, db_path=Path("files.db")):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, autocommit=True)
        self._create_schema()

    def _create_schema(self):
        self.conn.execute(SCHEMA)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_files_uploaded ON files(uploaded_at);"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_files_pruned ON files(pruned_at);"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_files_copied ON files(copied_at);"
        )

    def close(self):
        self.conn.close()

    def is_cached(self, file_file_hash):
        cursor = self.conn.execute(
            "SELECT 1 FROM files WHERE file_hash = ? AND cache_path is not NULL",
            (file_file_hash,),
        )
        return cursor.fetchone() is not None

    def insert_file(self, file_file_hash, sd_path, cache_path, size_bytes, mtime):
        cursor = self.conn.execute(
            """INSERT INTO files (file_hash, sd_path, cache_path, size_bytes, mtime)
               VALUES (?, ?, ?, ?, ?)""",
            (file_file_hash, sd_path, cache_path, size_bytes, mtime),
        )
        return cursor.lastrowid

    def update_cache_path(self, file_id, cache_path):
        self.conn.execute(
            "UPDATE files SET cache_path = ?, cached_at = ? WHERE id = ?",
            (cache_path, time.time(), file_id),
        )

    def mark_uploaded(self, file_id, remote_path):
        self.conn.execute(
            "UPDATE files SET uploaded_at = ?, remote_path = ?, upload_error=NULL WHERE id = ?",
            (time.time(), remote_path, file_id),
        )

    def mark_upload_error(self, file_id, error):
        self.conn.execute(
            """UPDATE files SET upload_error = ?, upload_attempts = upload_attempts + 1
               WHERE id = ?""",
            (error, file_id),
        )

    def get_files_to_upload(self):
        cursor = self.conn.execute(
            """SELECT id, file_hash, sd_path, cache_path, size_bytes
               FROM files
               WHERE cache_path IS NOT NULL
                 AND uploaded_at IS NULL
                 AND upload_error IS NULL
               ORDER BY cached_at"""
        )
        # Restituisco le righe in una lista di dizionari
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def increment_upload_attempts(self, file_id):
        self.conn.execute(
            "UPDATE files SET upload_attempts = upload_attempts + 1 WHERE id = ?",
            (file_id,),
        )

    def get_files_to_be_pruned(self, min_date=None):
        if min_date:
            cursor = self.conn.execute(
                """SELECT id, cache_path FROM files
                   WHERE uploaded_at IS NOT NULL AND pruned_at IS NULL AND uploaded_at < ?""",
                (min_date,),
            )
        else:
            cursor = self.conn.execute(
                """SELECT id, cache_path FROM files WHERE uploaded_at IS NOT NULL AND pruned_at IS NULL"""
            )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def mark_pruned(self, file_id):
        self.conn.execute(
            "UPDATE files SET pruned_at = ? WHERE id = ?",
            (time.time(), file_id),
        )
