import sqlite3
import time
import logging
from pathlib import Path

from models import FileRecord

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    file_hash TEXT NOT NULL,
    sd_path TEXT UNIQUE NOT NULL,
    cache_path TEXT,
    remote_path TEXT,
    size_bytes INTEGER NOT NULL,
    mtime REAL NOT NULL,
    cached_at REAL,
    uploaded_at REAL,
    pruned_at REAL,
    upload_error TEXT,
    upload_attempts INTEGER NOT NULL DEFAULT 0,
    mark_delete INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, db_path: Path = Path("files.db")):
        self.db_path = db_path
        self.conn = sqlite3.connect(
            str(db_path), autocommit=True, check_same_thread=False
        )
        self._create_schema()

    def _create_schema(self):
        self.conn.execute(SCHEMA)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_files_uploaded ON files(uploaded_at);"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_files_pruned ON files(pruned_at);"
        )
        self._migrate()

    def _migrate(self):
        try:
            self.conn.execute(
                "ALTER TABLE files ADD COLUMN mark_delete INTEGER NOT NULL DEFAULT 0"
            )
        except Exception:
            pass
        try:
            cursor = self.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='files'"
            )
            sql = cursor.fetchone()[0]
            if "file_hash TEXT UNIQUE" in sql:
                logger.info("Migrating database schema: UNIQUE(file_hash) -> UNIQUE(sd_path)")
                self.conn.executescript("""
                    CREATE TABLE files_new (
                        id INTEGER PRIMARY KEY,
                        file_hash TEXT NOT NULL,
                        sd_path TEXT UNIQUE NOT NULL,
                        cache_path TEXT,
                        remote_path TEXT,
                        size_bytes INTEGER NOT NULL,
                        mtime REAL NOT NULL,
                        cached_at REAL,
                        uploaded_at REAL,
                        pruned_at REAL,
                        upload_error TEXT,
                        upload_attempts INTEGER NOT NULL DEFAULT 0,
                        mark_delete INTEGER NOT NULL DEFAULT 0
                    );
                    INSERT INTO files_new SELECT * FROM files;
                    DROP TABLE files;
                    ALTER TABLE files_new RENAME TO files;
                """)
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_files_uploaded ON files(uploaded_at);"
                )
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_files_pruned ON files(pruned_at);"
                )
                logger.info("Database migration complete")
        except Exception as e:
            logger.warning("Schema migration skipped: %s", e)

    def close(self):
        self.conn.close()

    def _row_to_record(self, row) -> FileRecord:
        return FileRecord(*row)

    def find_by_sd_path(self, sd_path: str) -> FileRecord | None:
        cursor = self.conn.execute(
            "SELECT * FROM files WHERE sd_path = ?", (sd_path,)
        )
        row = cursor.fetchone()
        return self._row_to_record(row) if row else None

    def find_by_hash(self, file_hash: str) -> list[FileRecord]:
        cursor = self.conn.execute(
            "SELECT * FROM files WHERE file_hash = ?", (file_hash,)
        )
        return [self._row_to_record(row) for row in cursor.fetchall()]

    def create(
        self,
        file_hash: str,
        sd_path: str,
        cache_path: str,
        size_bytes: int,
        mtime: float,
    ) -> FileRecord:
        now = time.time()
        self.conn.execute(
            """INSERT INTO files (file_hash, sd_path, cache_path, size_bytes, mtime, cached_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (file_hash, sd_path, cache_path, size_bytes, mtime, now),
        )
        return self.find_by_sd_path(sd_path)

    def re_cache(
        self, file_hash: str, sd_path: str, cache_path: str, size_bytes: int, mtime: float
    ) -> FileRecord:
        now = time.time()
        self.conn.execute(
            """UPDATE files SET file_hash = ?, cache_path = ?, size_bytes = ?, mtime = ?,
               cached_at = ?, uploaded_at = NULL, remote_path = NULL,
               upload_error = NULL, upload_attempts = 0, pruned_at = NULL, mark_delete = 0
               WHERE sd_path = ?""",
            (file_hash, cache_path, size_bytes, mtime, now, sd_path),
        )
        return self.find_by_sd_path(sd_path)

    def mark_uploaded(self, file_id: int, remote_path: str) -> None:
        self.conn.execute(
            "UPDATE files SET uploaded_at = ?, remote_path = ?, upload_error = NULL WHERE id = ?",
            (time.time(), remote_path, file_id),
        )

    def mark_upload_error(self, file_id: int, error: str) -> None:
        self.conn.execute(
            "UPDATE files SET upload_error = ?, upload_attempts = upload_attempts + 1 WHERE id = ?",
            (error, file_id),
        )

    def find_pending_uploads(self) -> list[FileRecord]:
        cursor = self.conn.execute(
            """SELECT * FROM files
               WHERE cache_path IS NOT NULL
                 AND uploaded_at IS NULL
                 AND upload_error IS NULL
               ORDER BY cached_at"""
        )
        return [self._row_to_record(row) for row in cursor.fetchall()]

    def find_uploaded_not_pruned(
        self, min_date: float | None = None
    ) -> list[FileRecord]:
        if min_date is not None:
            cursor = self.conn.execute(
                """SELECT * FROM files
                   WHERE uploaded_at IS NOT NULL AND pruned_at IS NULL AND uploaded_at < ?""",
                (min_date,),
            )
        else:
            cursor = self.conn.execute(
                """SELECT * FROM files
                   WHERE uploaded_at IS NOT NULL AND pruned_at IS NULL"""
            )
        return [self._row_to_record(row) for row in cursor.fetchall()]

    def mark_pruned(self, file_id: int) -> None:
        self.conn.execute(
            "UPDATE files SET pruned_at = ? WHERE id = ?",
            (time.time(), file_id),
        )

    def mark_deleted_files(
        self, seen_paths: set[str], remote_prefix: str
    ) -> None:
        pattern = remote_prefix + "%"
        if seen_paths:
            placeholders = ",".join("?" for _ in seen_paths)
            self.conn.execute(
                f"UPDATE files SET mark_delete = 0 WHERE sd_path IN ({placeholders})",
                list(seen_paths),
            )
            self.conn.execute(
                f"UPDATE files SET mark_delete = 1 "
                "WHERE uploaded_at IS NOT NULL "
                "AND remote_path LIKE ? "
                f"AND sd_path NOT IN ({placeholders})",
                [pattern] + list(seen_paths),
            )
        else:
            self.conn.execute(
                "UPDATE files SET mark_delete = 1 "
                "WHERE uploaded_at IS NOT NULL AND remote_path LIKE ?",
                (pattern,),
            )

    def find_marked_for_deletion(self) -> list[FileRecord]:
        cursor = self.conn.execute(
            """SELECT * FROM files
               WHERE mark_delete = 1 AND remote_path IS NOT NULL
               ORDER BY id"""
        )
        return [self._row_to_record(row) for row in cursor.fetchall()]

    def clear_deletion_mark(self, file_id: int) -> None:
        self.conn.execute(
            "UPDATE files SET mark_delete = 0, uploaded_at = NULL, remote_path = NULL, cache_path = NULL WHERE id = ?",
            (file_id,),
        )

    def count_marked_for_deletion(self, remote_prefix: str) -> int:
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM files WHERE mark_delete = 1 AND remote_path LIKE ?",
            (remote_prefix + "%",),
        )
        return cursor.fetchone()[0]

    def count_uploaded_for_prefix(self, remote_prefix: str) -> int:
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM files WHERE uploaded_at IS NOT NULL AND remote_path LIKE ?",
            (remote_prefix + "%",),
        )
        return cursor.fetchone()[0]

    def clear_deletion_marks_for_prefix(self, remote_prefix: str) -> None:
        self.conn.execute(
            "UPDATE files SET mark_delete = 0 WHERE mark_delete = 1 AND remote_path LIKE ?",
            (remote_prefix + "%",),
        )

    def count_cached(self) -> int:
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM files WHERE cache_path IS NOT NULL"
        )
        return cursor.fetchone()[0]

    def count_pending_uploads(self) -> int:
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM files WHERE cache_path IS NOT NULL AND uploaded_at IS NULL AND upload_error IS NULL"
        )
        return cursor.fetchone()[0]

    def count_uploaded(self) -> int:
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM files WHERE uploaded_at IS NOT NULL"
        )
        return cursor.fetchone()[0]
