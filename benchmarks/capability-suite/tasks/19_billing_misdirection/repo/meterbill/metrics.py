"""Metric definitions and per-period aggregation.

A metric names something we meter (``api_calls``, ``storage_gb``, ``seats``)
and says how the records of one billing period are combined into the billed
quantity:

    sum   total of all record quantities (API calls, GB transferred)
    max   the largest single reading (peak seats)
    last  the reading with the latest timestamp (end-of-period storage);
          ties broken by the later record in feed order

Quantities are Decimal.  ``unit`` is the singular display unit and
``precision`` the number of decimal places shown on the invoice (the billed
quantity itself is never rounded).
"""

from dataclasses import dataclass
from decimal import Decimal

from .errors import ConfigError, UnknownMetric

AGGREGATIONS = ("sum", "max", "last")


@dataclass(frozen=True)
class Metric:
    id: str
    name: str
    unit: str
    aggregation: str = "sum"
    precision: int = 0

    def aggregate(self, records):
        """Billed quantity of ``records`` (an iterable of UsageRecord)."""
        records = list(records)
        if not records:
            return Decimal(0)
        if self.aggregation == "sum":
            total = Decimal(0)
            for r in records:
                total += r.quantity
            return total
        if self.aggregation == "max":
            return max(r.quantity for r in records)
        if self.aggregation == "last":
            best = None
            for i, r in enumerate(records):
                key = (r.at, i)
                if best is None or key >= best[0]:
                    best = (key, r)
            return best[1].quantity
        raise ConfigError(f"metric {self.id}: unknown aggregation {self.aggregation!r}")


def parse_metric(mid, spec):
    if not isinstance(spec, dict):
        raise ConfigError(f"metric {mid}: expected an object")
    agg = spec.get("aggregation", "sum")
    if agg not in AGGREGATIONS:
        raise ConfigError(f"metric {mid}: aggregation must be one of {', '.join(AGGREGATIONS)}")
    precision = spec.get("precision", 0)
    if not isinstance(precision, int) or not 0 <= precision <= 6:
        raise ConfigError(f"metric {mid}: precision must be an integer 0-6")
    return Metric(
        id=mid,
        name=str(spec.get("name", mid)),
        unit=str(spec.get("unit", "unit")),
        aggregation=agg,
        precision=precision,
    )


class MetricSet:
    def __init__(self, metrics):
        self._m = dict(metrics)

    def get(self, mid):
        try:
            return self._m[mid]
        except KeyError:
            raise UnknownMetric(f"unknown metric {mid!r}") from None

    def __contains__(self, mid):
        return mid in self._m

    def __iter__(self):
        return iter(sorted(self._m.values(), key=lambda m: m.id))

    def ids(self):
        return sorted(self._m)
