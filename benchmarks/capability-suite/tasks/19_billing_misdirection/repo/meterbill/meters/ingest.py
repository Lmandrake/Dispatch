"""Load every feed in a directory into one de-duplicated record set.

Rules (docs/METERING.md, "Ingestion"):

1. Files are read in name order; the reader is picked by extension (.csv,
   .jsonl, .log).  Other files are ignored.
2. A record for a customer that is not in the customer file, or for a
   metric that is not in the catalogue, is rejected.
3. An event id seen before is a replay or a conflicting duplicate
   (docs/METERING.md, "Ingestion").
"""

from dataclasses import dataclass, field
from pathlib import Path

from .csv_feed import read_csv_feed
from .jsonl_feed import read_jsonl_feed
from .kv_feed import read_kv_feed
from .records import Reject

READERS = {
    ".csv": read_csv_feed,
    ".jsonl": read_jsonl_feed,
    ".log": read_kv_feed,
}


@dataclass
class Ingested:
    records: list = field(default_factory=list)
    rejects: list = field(default_factory=list)
    replays: int = 0
    files: list = field(default_factory=list)

    def for_customer(self, cid):
        return [r for r in self.records if r.customer == cid]

    def by_metric(self, cid):
        out = {}
        for r in self.records:
            if r.customer == cid:
                out.setdefault(r.metric, []).append(r)
        return out


def read_feed(name, text):
    """Parse one feed's text with the reader for its extension."""
    reader = READERS.get(Path(name).suffix.lower())
    if reader is None:
        raise ValueError(f"no reader for {name}")
    return reader(text, source=Path(name).name)


def merge(results, *, customers=None, metrics=None):
    """Combine FeedResults (in order) into an Ingested, applying rules 2-3."""
    out = Ingested()
    for res in results:
        seen = {}
        out.files.append(res.source)
        out.rejects.extend(res.rejects)
        for rec in res.records:
            if customers is not None and rec.customer not in customers:
                out.rejects.append(Reject(rec.source, rec.line, f"unknown customer {rec.customer}"))
                continue
            if metrics is not None and rec.metric not in metrics:
                out.rejects.append(Reject(rec.source, rec.line, f"unknown metric {rec.metric}"))
                continue
            prior = seen.get(rec.event_id)
            if prior is not None:
                if prior.identity() == rec.identity():
                    out.replays += 1
                else:
                    out.rejects.append(Reject(
                        rec.source, rec.line,
                        f"event {rec.event_id} conflicts with {prior.source}:{prior.line}"))
                continue
            seen[rec.event_id] = rec
            out.records.append(rec)
    return out


def load_feeds(directory, *, customers=None, metrics=None):
    """Read every feed under ``directory`` (not recursive)."""
    d = Path(directory)
    results = []
    for path in sorted(d.iterdir()):
        if path.is_file() and path.suffix.lower() in READERS:
            results.append(read_feed(path.name, path.read_text(encoding="utf-8")))
    return merge(results, customers=customers, metrics=metrics)
