"""Down-sampling by row."""
import random

from ..errors import QueryError


def every_nth(table, n, offset=0):
    """Rows ``offset, offset + n, offset + 2n, ...``."""
    if n < 1:
        raise QueryError("n must be at least 1")
    if offset < 0:
        raise QueryError("offset must not be negative")
    return table.take(range(offset, table.num_rows, n))


def reservoir(table, k, seed=0):
    """A uniform random sample of ``k`` rows (all rows if there are fewer), kept in
    their original order.  The same seed always gives the same sample."""
    if k < 0:
        raise QueryError("sample size must not be negative")
    rnd = random.Random(seed)
    chosen = []
    for i in range(table.num_rows):
        if len(chosen) < k:
            chosen.append(i)
        else:
            j = rnd.randint(0, i)
            if j < k:
                chosen[j] = i
    return table.take(sorted(chosen))
