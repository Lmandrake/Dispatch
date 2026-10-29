"""Metering feeds.

Three feed formats are read (docs/METERING.md):

    *.csv     the API gateway export
    *.jsonl   the storage service's JSON-lines snapshots
    *.log     the seat service's key=value audit log

``ingest.load_feeds`` reads a directory of them, normalises units, removes
duplicates and returns the usable records plus the rejected ones.
"""

from .records import Reject, UsageRecord  # noqa: F401
