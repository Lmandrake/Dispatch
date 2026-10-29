"""Exception hierarchy for meterbill.

Every error raised on purpose by the package derives from BillingError, so a
billing run can tell "bad input" apart from programming errors.
"""


class BillingError(Exception):
    """Base class for all meterbill errors."""


class ConfigError(BillingError):
    """A data file (catalogue, customers, tax table, ...) is invalid."""

    def __init__(self, message, *, source=None, key=None):
        self.source = source
        self.key = key
        where = []
        if source:
            where.append(str(source))
        if key:
            where.append(str(key))
        prefix = ": ".join(where)
        super().__init__(f"{prefix}: {message}" if prefix else message)


class MeterFormatError(BillingError):
    """A metering record could not be parsed."""

    def __init__(self, message, *, source=None, line=None):
        self.source = source
        self.line = line
        loc = ""
        if source is not None:
            loc = f"{source}"
            if line is not None:
                loc += f":{line}"
            loc += ": "
        super().__init__(loc + message)


class UnknownCustomer(BillingError):
    """A record or subscription refers to a customer id that does not exist."""


class UnknownPlan(BillingError):
    """A subscription refers to a plan id missing from the catalogue."""


class UnknownMetric(BillingError):
    """A metered charge refers to a metric that is not defined."""


class RateNotFound(BillingError):
    """No exchange rate is in effect for a currency on a date."""

    def __init__(self, currency, on):
        self.currency = currency
        self.on = on
        super().__init__(f"no {currency} rate in effect on {on.isoformat()}")


class CurrencyMismatch(BillingError):
    """Two Money values of different currencies were combined."""

    def __init__(self, left, right):
        super().__init__(f"cannot combine {left} with {right}")


class TaxError(BillingError):
    """A customer's jurisdiction is unknown or its tax rule is invalid."""


class PeriodError(BillingError):
    """A billing period label or window is invalid."""


class DunningError(BillingError):
    """The dunning schedule or an invoice's payment state is inconsistent."""
