"""The normalised usage record every feed is turned into."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class UsageRecord:
    event_id: str
    customer: str
    metric: str
    quantity: Decimal
    at: datetime           # aware, UTC
    source: str = ""       # feed file name
    line: int = 0          # line in the feed
    note: str = ""

    def identity(self):
        """What must agree for two records with one event id to be the same event."""
        return (self.customer, self.metric, self.quantity, self.at)


@dataclass(frozen=True)
class Reject:
    source: str
    line: int
    reason: str
    raw: str = ""

    def __str__(self):
        return f"{self.source}:{self.line}: {self.reason}"


@dataclass
class FeedResult:
    """Output of one feed reader."""

    source: str
    records: list = field(default_factory=list)
    rejects: list = field(default_factory=list)

    def reject(self, line, reason, raw=""):
        self.rejects.append(Reject(self.source, line, reason, raw.rstrip("\r\n")))

    def add(self, record):
        self.records.append(record)


def check_quantity(value):
    """Usage quantities are non-negative decimals; return Decimal or raise ValueError."""
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"quantity must be a decimal string or integer, got {value!r}")
    try:
        q = Decimal(str(value).strip().replace("_", ""))
    except Exception:
        raise ValueError(f"bad quantity {value!r}") from None
    if not q.is_finite():
        raise ValueError(f"bad quantity {value!r}")
    if q < 0:
        raise ValueError(f"negative quantity {value!r}")
    return q
