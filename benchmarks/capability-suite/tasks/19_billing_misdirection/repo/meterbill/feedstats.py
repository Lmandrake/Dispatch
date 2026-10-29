"""Statistics per metering feed file, from an ``Ingested`` result.

For every file that was read, ``feed_stats`` reports how many records it
contributed (after de-duplication and the unknown-customer/metric checks),
how many each metric and customer account for, the first and last instant
seen, and how many lines were rejected, with a histogram of *reasons*.

Reject reasons carry details that differ line by line ("unknown customer
C99", "event api-1 conflicts with a.csv:3", "bad quantity 'x'").  The
histogram groups them by ``reason_class``: the reason with quoted strings,
ids and numbers replaced by a placeholder, so that all "unknown customer ..."
rejects count together.

Replays (exact duplicate events dropped silently by ingestion) are not
attributable to a file in the Ingested result; only their total is shown.
This module reads the result; it never re-parses or re-deduplicates a feed.
"""

import re
from dataclasses import dataclass, field

from .render.fmt import format_qty
from .timeutil import format_instant

_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_PATH_REF = re.compile(r"\S+\.(?:csv|jsonl|log):\d+")
_TOKEN_AFTER = re.compile(r"\b(customer|metric|event)\s+\S+")
_NUMBER = re.compile(r"\b\d+\b")


def reason_class(reason):
    """Normalise a reject reason so equal kinds of problem group together."""
    text = _QUOTED.sub("<value>", reason)
    text = _PATH_REF.sub("<ref>", text)
    text = _TOKEN_AFTER.sub(lambda m: f"{m.group(1)} <id>", text)
    return _NUMBER.sub("<n>", text)


@dataclass
class FeedStats:
    source: str
    records: int = 0
    first: object = None
    last: object = None
    by_metric: dict = field(default_factory=dict)      # metric -> record count
    by_customer: dict = field(default_factory=dict)    # customer -> record count
    quantity: dict = field(default_factory=dict)       # metric -> sum of quantities
    rejects: int = 0
    reject_reasons: dict = field(default_factory=dict)  # reason class -> count

    @property
    def lines_seen(self):
        return self.records + self.rejects

    @property
    def reject_rate_percent(self):
        """Rejects as a percentage of accepted + rejected lines, one decimal; "0.0" when empty."""
        if not self.lines_seen:
            return "0.0"
        return f"{self.rejects * 100 / self.lines_seen:.1f}"


def feed_stats(ingested):
    """A list of FeedStats, one per file in ``ingested.files`` (read order).

    Records and rejects whose source is not in ``files`` get their own entry
    appended at the end, so nothing is silently dropped.
    """
    stats = {name: FeedStats(name) for name in ingested.files}
    for r in ingested.records:
        st = stats.setdefault(r.source, FeedStats(r.source))
        st.records += 1
        st.by_metric[r.metric] = st.by_metric.get(r.metric, 0) + 1
        st.by_customer[r.customer] = st.by_customer.get(r.customer, 0) + 1
        st.quantity[r.metric] = st.quantity.get(r.metric, 0) + r.quantity
        if st.first is None or r.at < st.first:
            st.first = r.at
        if st.last is None or r.at > st.last:
            st.last = r.at
    for rej in ingested.rejects:
        st = stats.setdefault(rej.source, FeedStats(rej.source))
        st.rejects += 1
        key = reason_class(rej.reason)
        st.reject_reasons[key] = st.reject_reasons.get(key, 0) + 1
    return list(stats.values())


def overall_reject_histogram(stats):
    """reason class -> count over all files, most common first (ties alphabetical)."""
    total = {}
    for st in stats:
        for k, n in st.reject_reasons.items():
            total[k] = total.get(k, 0) + n
    return dict(sorted(total.items(), key=lambda kv: (-kv[1], kv[0])))


def _span(st):
    if st.first is None:
        return "-"
    return f"{format_instant(st.first)} .. {format_instant(st.last)}"


def render_feed_stats(stats, ingested=None, metrics=None):
    """Text table of the files, then per-file detail and the reject histogram.

    ``ingested`` adds the replay total; ``metrics`` (a MetricSet) formats
    summed quantities at each metric's precision.
    """
    if not stats:
        return "No feeds.\n"
    out = [f"{'file':<28}{'records':>9}{'rejects':>9}{'rej %':>7}{'customers':>11}  span (UTC)"]
    for st in stats:
        out.append(f"{st.source:<28}{st.records:>9}{st.rejects:>9}{st.reject_rate_percent:>7}"
                   f"{len(st.by_customer):>11}  {_span(st)}")
    out.append(f"{'TOTAL':<28}{sum(s.records for s in stats):>9}{sum(s.rejects for s in stats):>9}")
    if ingested is not None:
        out.append(f"replays dropped: {ingested.replays}")
    out.append("")
    for st in stats:
        out.append(f"{st.source}")
        if not st.by_metric:
            out.append("  (no accepted records)")
        for mid in sorted(st.by_metric):
            precision = metrics.get(mid).precision if metrics is not None else 0
            out.append(f"  {mid:<14}{st.by_metric[mid]:>8} records   sum {format_qty(st.quantity[mid], precision)}")
    hist = overall_reject_histogram(stats)
    out.append("")
    out.append("Reject reasons")
    if not hist:
        out.append("  none")
    for reason, n in hist.items():
        out.append(f"  {n:>5}  {reason}")
    return "\n".join(out) + "\n"
