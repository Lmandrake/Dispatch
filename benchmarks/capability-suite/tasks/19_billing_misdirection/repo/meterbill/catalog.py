"""The plan catalogue (data/catalog.toml).

    [metrics.<id>]          see metrics.py
    [plans.<id>]
    name = "Team"
    currency = "USD"        prices of the plan are in this currency
    base_fee = "199.00"     per billing period, prorated on changes
    [[plans.<id>.charges]]  one per metered metric
    metric = "api_calls"
    model = "graduated"     see pricing.py
    tiers = [ ... ]

A plan may be marked ``legacy = true``: existing subscriptions keep working,
but a subscription may not *switch to* a legacy plan.
"""

import tomllib
from dataclasses import dataclass

from . import currency as _cur
from .errors import ConfigError, UnknownPlan
from .metrics import MetricSet, parse_metric
from .money import ZERO, dec
from .pricing import parse_price, rate


@dataclass(frozen=True)
class Charge:
    metric: str
    price: object  # PriceSpec
    description: str = ""


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    currency: str
    base_fee: object  # Decimal
    charges: tuple
    legacy: bool = False

    def charge_for(self, metric):
        for c in self.charges:
            if c.metric == metric:
                return c
        return None

    def metrics(self):
        return [c.metric for c in self.charges]

    def rate(self, metric, quantity):
        c = self.charge_for(metric)
        if c is None:
            return None
        return rate(c.price, quantity)


class Catalog:
    def __init__(self, metrics, plans):
        self.metrics = metrics
        self._plans = dict(plans)

    def plan(self, pid):
        try:
            return self._plans[pid]
        except KeyError:
            raise UnknownPlan(f"unknown plan {pid!r}") from None

    def __contains__(self, pid):
        return pid in self._plans

    def plans(self):
        return [self._plans[k] for k in sorted(self._plans)]


def parse_catalog(text, *, source="catalog.toml"):
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML: {e}", source=source) from None
    raw_metrics = data.get("metrics", {})
    if not raw_metrics:
        raise ConfigError("no [metrics] defined", source=source)
    metrics = MetricSet({mid: parse_metric(mid, spec) for mid, spec in raw_metrics.items()})
    plans = {}
    for pid, spec in data.get("plans", {}).items():
        where = f"plan {pid}"
        if "currency" not in spec:
            raise ConfigError(f"{where}: currency is required", source=source)
        cur = _cur.get(spec["currency"]).code
        base = dec(str(spec.get("base_fee", "0")))
        if base < ZERO:
            raise ConfigError(f"{where}: base_fee must not be negative", source=source)
        charges = []
        seen = set()
        for i, c in enumerate(spec.get("charges", [])):
            cw = f"{where} charge {i + 1}"
            mid = c.get("metric")
            if mid not in metrics:
                raise ConfigError(f"{cw}: unknown metric {mid!r}", source=source)
            if mid in seen:
                raise ConfigError(f"{cw}: metric {mid} charged twice", source=source)
            seen.add(mid)
            charges.append(Charge(mid, parse_price(c, cw), str(c.get("description", ""))))
        plans[pid] = Plan(pid, str(spec.get("name", pid)), cur, base, tuple(charges), bool(spec.get("legacy", False)))
    if not plans:
        raise ConfigError("no [plans] defined", source=source)
    return Catalog(metrics, plans)
