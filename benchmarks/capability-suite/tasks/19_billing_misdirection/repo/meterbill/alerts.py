"""Usage alerts (docs/METERING.md, "Alerts").

Customers can ask to be warned when their usage in the current billing
period crosses a threshold.  data/alerts.csv:

    customer,metric,threshold

``check_alerts`` replays the period's records in time order and reports, per
alert, the first record at which the aggregated quantity (with the metric's
own aggregation: running sum, running max, or latest reading) reaches the
threshold.  An alert that is never reached is not reported.
"""

from dataclasses import dataclass

from .csvutil import read_rows
from .errors import ConfigError
from .money import dec


@dataclass(frozen=True)
class Alert:
    customer: str
    metric: str
    threshold: object


@dataclass(frozen=True)
class Fired:
    alert: Alert
    at: object
    value: object
    event_id: str


def parse_alerts(text, *, metrics=None, source="alerts.csv"):
    out = []
    for lineno, r in read_rows(text, required=("customer", "metric", "threshold"), source=source):
        if metrics is not None and r["metric"] not in metrics:
            raise ConfigError(f"line {lineno}: unknown metric {r['metric']!r}", source=source)
        t = dec(r["threshold"])
        if t <= 0:
            raise ConfigError(f"line {lineno}: threshold must be positive", source=source)
        out.append(Alert(r["customer"].upper(), r["metric"], t))
    return out


def check_alerts(alerts, records, period, metrics):
    fired = []
    for a in alerts:
        recs = sorted((r for r in records if r.customer == a.customer and r.metric == a.metric
                       and period.contains(r.at)), key=lambda r: r.at)
        agg = metrics.get(a.metric).aggregation
        value = None
        for r in recs:
            if agg == "sum":
                value = (value or 0) + r.quantity
            elif agg == "max":
                value = r.quantity if value is None else max(value, r.quantity)
            else:
                value = r.quantity
            if value >= a.threshold:
                fired.append(Fired(a, r.at, value, r.event_id))
                break
    return fired
