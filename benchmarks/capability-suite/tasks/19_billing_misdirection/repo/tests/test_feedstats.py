"""Per-feed statistics."""

from decimal import Decimal

from meterbill.feedstats import feed_stats, overall_reject_histogram, reason_class, render_feed_stats
from meterbill.meters.ingest import Ingested, load_feeds, merge, read_feed
from meterbill.meters.records import Reject

from .helpers import DATA, catalog

A = """event_id,customer,metric,quantity,timestamp,note
a-1,C01,api_calls,10,2026-03-02T10:00:00Z,
a-2,C02,api_calls,5,2026-03-03T10:00:00Z,
a-3,C99,api_calls,5,2026-03-03T10:00:00Z,
a-4,C01,api_calls,x,2026-03-03T10:00:00Z,
a-1,C01,api_calls,10,2026-03-02T10:00:00Z,
"""
B = """event_id,customer,metric,quantity,timestamp,note
b-1,C01,nonsense,1,2026-03-04T10:00:00Z,
b-2,C02,api_calls,6,
"""


def ingest():
    results = [read_feed("a.csv", A), read_feed("b.csv", B)]
    return merge(results, customers={"C01": 1, "C02": 1}, metrics=catalog().metrics)


def test_reason_class_groups_details():
    assert reason_class("unknown customer C99") == reason_class("unknown customer C12")
    assert reason_class("bad quantity 'x'") == reason_class("bad quantity '-4'")
    assert reason_class("event a-2 conflicts with a.csv:3") == reason_class("event zz conflicts with b.csv:19")
    assert reason_class("5 fields, expected 6") == "<n> fields, expected <n>"


def test_per_file_counts_and_span():
    ing = ingest()
    st = {s.source: s for s in feed_stats(ing)}
    a, b = st["a.csv"], st["b.csv"]
    assert (a.records, b.records) == (2, 0)
    assert a.by_customer == {"C01": 1, "C02": 1} and a.by_metric == {"api_calls": 2}
    assert a.quantity["api_calls"] == Decimal(15)
    assert a.first.isoformat().startswith("2026-03-02") and a.last.isoformat().startswith("2026-03-03")
    assert b.first is None


def test_reject_histogram():
    ing = ingest()
    stats = feed_stats(ing)
    by = {s.source: s for s in stats}
    assert by["a.csv"].rejects == 2 and by["b.csv"].rejects == 2
    hist = overall_reject_histogram(stats)
    assert sum(hist.values()) == 4 and hist["unknown metric <id>"] == 1
    assert list(hist.values()) == sorted(hist.values(), reverse=True)
    assert ing.replays == 1


def test_reject_rate():
    ing = ingest()
    a = feed_stats(ing)[0]
    assert a.lines_seen == 4 and a.reject_rate_percent == "50.0"
    assert feed_stats(Ingested())[:] == []


def test_unlisted_source_is_not_dropped():
    ing = Ingested(rejects=[Reject("ghost.csv", 1, "boom")])
    stats = feed_stats(ing)
    assert [s.source for s in stats] == ["ghost.csv"] and stats[0].rejects == 1


def test_render_table():
    ing = ingest()
    text = render_feed_stats(feed_stats(ing), ing, catalog().metrics)
    assert "a.csv" in text and "replays dropped: 1" in text and "Reject reasons" in text
    assert "(no accepted records)" in text
    assert render_feed_stats([]) == "No feeds.\n"


def test_sample_data_totals_match_ingest():
    cat = catalog()
    ing = load_feeds(DATA / "feeds", metrics=cat.metrics)
    stats = feed_stats(ing)
    assert sum(s.records for s in stats) == len(ing.records)
    assert sum(s.rejects for s in stats) == len(ing.rejects)
    assert [s.source for s in stats] == ing.files
    text = render_feed_stats(stats, ing, cat.metrics)
    assert "2026-03-gateway-a.csv" in text
