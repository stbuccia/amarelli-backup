from dataclasses import dataclass


@dataclass
class FileRecord:
    id: int
    file_hash: str
    sd_path: str
    cache_path: str | None = None
    remote_path: str | None = None
    size_bytes: int = 0
    mtime: float = 0.0
    cached_at: float | None = None
    uploaded_at: float | None = None
    pruned_at: float | None = None
    upload_error: str | None = None
    upload_attempts: int = 0
