"""Exception hierarchy for tsarc.

Every error raised on purpose by the library derives from :class:`TsarcError`,
so callers that only want to report failures can catch that one class.
"""


class TsarcError(Exception):
    """Base class of every tsarc error."""


class SchemaError(TsarcError, ValueError):
    """A schema, column definition or value does not satisfy the schema rules."""


class FormatError(TsarcError):
    """A file is not a well-formed archive (bad magic, bad structure, ...)."""


class ChecksumError(FormatError):
    """A stored checksum does not match the bytes it protects."""


class UnsupportedVersionError(TsarcError):
    """The file has the right magic but a format version this library cannot handle,
    or a caller asked to write a version that does not exist."""

    def __init__(self, version):
        self.version = version
        super().__init__(f"unsupported archive format version {version}")


class NotRepresentableError(TsarcError, ValueError):
    """Data cannot be stored exactly in the requested format version.

    Attributes:
        column -- the column name involved, or None for an archive-level field
        row    -- 0-based row index, or None when the problem is not tied to a row
        reason -- short human-readable reason
    """

    def __init__(self, reason, column=None, row=None):
        self.reason = reason
        self.column = column
        self.row = row
        where = []
        if column is not None:
            where.append(f"column '{column}'")
        if row is not None:
            where.append(f"row {row}")
        prefix = ", ".join(where)
        super().__init__(f"{prefix}: {reason}" if prefix else reason)


class ExpressionError(TsarcError, ValueError):
    """A filter expression could not be parsed or evaluated.

    ``position`` is the 0-based character offset of the problem, or None.
    """

    def __init__(self, message, position=None):
        self.message = message
        self.position = position
        if position is None:
            super().__init__(message)
        else:
            super().__init__(f"{message} (at position {position})")


class CsvImportError(TsarcError, ValueError):
    """A CSV file could not be imported.  ``line`` is the 1-based line number, or None."""

    def __init__(self, message, line=None):
        self.message = message
        self.line = line
        super().__init__(f"line {line}: {message}" if line is not None else message)


class QueryError(TsarcError, ValueError):
    """A query was given arguments that do not make sense for the archive."""
