"""Exception hierarchy. The CLI turns any StockroomError into ``error: <msg>``."""


class StockroomError(Exception):
    """Base class for every error this package raises on purpose."""


class ValidationError(StockroomError):
    """Input broke a business rule (bad SKU, negative stock, ...)."""


class NotFoundError(StockroomError):
    """An item or order that does not exist was referenced."""


class ConflictError(StockroomError):
    """The operation is not allowed in the current state."""


class StorageError(StockroomError):
    """The backing store could not be read or written."""


class QueryError(StockroomError):
    """A ``--where`` query could not be parsed or does not type-check.

    ``position`` is the 0-based character offset of the offending token,
    or None when the problem is not tied to one place.
    """

    def __init__(self, message, position=None):
        if position is not None:
            message = f"{message} (at position {position})"
        super().__init__(message)
        self.position = position
