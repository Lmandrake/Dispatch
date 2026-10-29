"""Per-sensor summary statistics."""
import math
from dataclasses import dataclass


@dataclass
class SensorStats:
    sensor: int
    count: int
    first_ts: int
    last_ts: int
    minimum: float
    maximum: float
    mean: float
    calibrated_count: int

    @property
    def span(self):
        """Seconds between the first and last reading."""
        return self.last_ts - self.first_ts

    @property
    def rate(self):
        """Readings per second over the span, or None for a zero span."""
        if self.span <= 0:
            return None
        return (self.count - 1) / self.span


def summarize(records):
    """Return {sensor: SensorStats}, NaN values ignored for min/max/mean."""
    groups = {}
    for r in records:
        groups.setdefault(r.sensor, []).append(r)
    out = {}
    for sensor in sorted(groups):
        rs = groups[sensor]
        vals = [float(r.value) for r in rs if not (isinstance(r.value, float) and math.isnan(r.value))]
        out[sensor] = SensorStats(
            sensor=sensor,
            count=len(rs),
            first_ts=min(r.timestamp for r in rs),
            last_ts=max(r.timestamp for r in rs),
            minimum=min(vals) if vals else math.nan,
            maximum=max(vals) if vals else math.nan,
            mean=(math.fsum(vals) / len(vals)) if vals else math.nan,
            calibrated_count=sum(1 for r in rs if r.calibrated),
        )
    return out


def format_table(stats):
    lines = [f"{'sensor':>6} {'count':>7} {'min':>12} {'max':>12} {'mean':>12} {'rate/s':>9}"]
    for s in stats.values():
        rate = "-" if s.rate is None else f"{s.rate:.3f}"
        lines.append(
            f"{s.sensor:>6} {s.count:>7} {s.minimum:>12.4g} {s.maximum:>12.4g} {s.mean:>12.4g} {rate:>9}"
        )
    return "\n".join(lines)
