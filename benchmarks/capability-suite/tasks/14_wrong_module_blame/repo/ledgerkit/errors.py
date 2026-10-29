"""Exception hierarchy for ledgerkit.

Every error raised on purpose by the pipeline derives from LedgerError so that
callers (the CLI in particular) can catch one type and report the line number.
"""


class LedgerError(Exception):
    """Base class for all ledgerkit errors."""

    def __init__(self, message, *, line=None, source=None):
        self.line = line
        self.source = source
        prefix = ""
        if source is not None and line is not None:
            prefix = f"{source}:{line}: "
        elif line is not None:
            prefix = f"line {line}: "
        super().__init__(prefix + message)
        self.bare_message = message


class LexError(LedgerError):
    """A line could not be split into fields (bad quoting, stray escape)."""


class ParseError(LedgerError):
    """A field could not be interpreted (bad date, bad amount, unknown column)."""


class AmountError(ParseError):
    """An amount string is malformed for the active locale."""


class DateError(ParseError):
    """A date string is malformed or out of range."""


class AccountError(LedgerError):
    """An account name is unknown or ambiguous."""


class RateNotFound(LedgerError):
    """No exchange rate is in effect for the currency on the requested date."""


class AllocationError(LedgerError):
    """Shares for an allocation are invalid (empty, negative, all zero)."""
