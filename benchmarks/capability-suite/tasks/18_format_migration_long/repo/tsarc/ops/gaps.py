"""Finding gaps in the time column."""
from dataclasses import dataclass

from ..errors import QueryError


@dataclass(frozen=True)
class Gap:
    start: int      # timestamp of the row before the gap
    end: int        # timestamp of the row after the gap
    rows_before: int

    @property
    def length(self):
        return self.end - self.start


def find_gaps(table, threshold):
    """Gaps between consecutive (time-sorted) rows longer than ``threshold`` microseconds."""
    if threshold <= 0:
        raise QueryError("gap threshold must be positive")
    ts = sorted(table.time_values())
    out = []
    for i in range(1, len(ts)):
        if ts[i] - ts[i - 1] > threshold:
            out.append(Gap(ts[i - 1], ts[i], i))
    return out
