"""Table operations: resampling, merging, de-duplication, rolling windows, gaps,
as-of joins, partitioning and sampling.  Every operation takes and returns
:class:`~tsarc.table.Table` objects and never modifies its input."""
from .dedupe import dedupe
from .gaps import find_gaps
from .join import asof_join
from .merge import merge_tables
from .resample import resample
from .sample import every_nth, reservoir
from .window import rolling

__all__ = ["dedupe", "find_gaps", "asof_join", "merge_tables", "resample", "every_nth",
           "reservoir", "rolling"]
