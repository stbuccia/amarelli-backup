class BackupError(Exception):
    pass


class TransientError(BackupError):
    """Recoverable error, retried automatically."""


class PermanentError(BackupError):
    """Needs user intervention, no point retrying."""
