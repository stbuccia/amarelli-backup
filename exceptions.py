class BackupError(Exception):
    """Base exception for backup operations."""


class TransientError(BackupError):
    """Recoverable error - the operation will be retried automatically."""


class PermanentError(BackupError):
    """Non-recoverable error - requires user intervention."""
