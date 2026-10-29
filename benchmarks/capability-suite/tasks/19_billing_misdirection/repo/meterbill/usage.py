"""Assigning usage records to billing periods and plan segments.

A record belongs to the period when ``period.start_utc <= at < period.end_utc``
(docs/PERIODS.md).  Inside the period it belongs to the plan segment whose
local days contain it; segment boundaries are local midnights, the first
segment starts at ``period.start_utc`` and the last one ends at
``period.end_utc``.

Records inside the period but in days with no plan (before the first
subscription row, or after a ``none`` row) are *unbilled*: they are reported
by the reconciliation, never charged.
"""

from dataclasses import dataclass, field

from .timeutil import local_midnight


@dataclass
class SegmentUsage:
    segment: object
    start_utc: object
    end_utc: object
    records: dict = field(default_factory=dict)   # metric -> [UsageRecord]

    def add(self, rec):
        self.records.setdefault(rec.metric, []).append(rec)

    def count(self):
        return sum(len(v) for v in self.records.values())


@dataclass
class PeriodUsage:
    period: object
    segments: list = field(default_factory=list)
    unbilled: list = field(default_factory=list)
    outside: int = 0      # records of the customer outside the period

    def billed_count(self):
        return sum(s.count() for s in self.segments)


def segment_bounds(segments, period):
    """(segment, start_utc, end_utc) for each segment of a period."""
    out = []
    for seg in segments:
        start = period.start_utc if seg.start == period.start else local_midnight(seg.start, period.tz)
        end = period.end_utc if seg.end == period.end else local_midnight(seg.end, period.tz)
        out.append((seg, start, end))
    return out


def assign(records, period, segments):
    """Split one customer's records over a period's segments."""
    pu = PeriodUsage(period)
    bounds = segment_bounds(segments, period)
    pu.segments = [SegmentUsage(seg, a, b) for seg, a, b in bounds]
    for rec in records:
        if not period.contains(rec.at):
            pu.outside += 1
            continue
        for su in pu.segments:
            if su.start_utc <= rec.at < su.end_utc:
                su.add(rec)
                break
        else:
            pu.unbilled.append(rec)
    return pu
