"""Exception hierarchy for senslog."""


class SenslogError(Exception):
    """Base class for every error raised by senslog."""


class UnsupportedVersionError(SenslogError):
    """The file has a valid magic number but a format version we cannot read."""

    def __init__(self, version):
        super().__init__(f"unsupported format version {version}")
        self.version = version


class CorruptFileError(SenslogError):
    """The file is not a well-formed SLOG file.

    ``record_index`` is the 0-based index of the offending record when the
    problem is attributable to one record, else ``None``.
    """

    def __init__(self, message, record_index=None):
        super().__init__(message)
        self.record_index = record_index
