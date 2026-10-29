"""Exception hierarchy.

Everything the application raises on purpose derives from ``TrellisError``;
the CLI prints those as ``error: <message>`` and exits with status 1.
"""


class TrellisError(Exception):
    """Base class for expected, user-facing errors."""


class ValidationError(TrellisError):
    """Input that breaks a business rule (bad title, unknown status, ...)."""


class NotFoundError(TrellisError):
    """A user, project, issue or comment that does not exist."""


class ConflictError(TrellisError):
    """A change that clashes with existing state (duplicate key, ...)."""


class PermissionDenied(TrellisError):
    """The acting user's role does not allow the operation."""


class StorageError(TrellisError):
    """The data file or database cannot be read, written or upgraded."""


class QueryError(TrellisError):
    """A malformed --where query.  ``pos`` is the 0-based offset of the
    offending token, or None when the problem has no single location."""

    def __init__(self, message, pos=None):
        self.pos = pos
        if pos is not None:
            message = f"{message} (at offset {pos})"
        super().__init__(message)
