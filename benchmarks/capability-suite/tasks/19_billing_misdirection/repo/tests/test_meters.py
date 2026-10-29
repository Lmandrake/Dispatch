from decimal import Decimal

from meterbill.meters.csv_feed import read_csv_feed
from meterbill.meters.ingest import merge
from meterbill.meters.jsonl_feed import read_jsonl_feed, to_gb
from meterbill.meters.kv_feed import parse_line, read_kv_feed, tokenize

D = Decimal

CSV = (
    "event_id,customer,metric,quantity,timestamp,note\n"
    "e1,c01,api_calls,100,2026-03-02T10:00:00Z,\n"
    "e2,C01,api_calls,250,2026-03-02T11:00:00+01:00,\n"
    "e3,C02,api_calls,1_000,1772445600,\n"
)


def test_csv_feed_basic():
    res = read_csv_feed(CSV, "gw.csv")
    assert [r.event_id for r in res.records] == ["e1", "e2", "e3"]
    assert res.records[0].customer == "C01"
    assert res.records[1].at.hour == 10
    assert res.records[2].quantity == D(1000)
    assert res.rejects == []


def test_csv_feed_other_column_order():
    text = "timestamp,quantity,metric,customer,event_id,note\n2026-03-02T10:00:00Z,7,api_calls,C03,x1,\n"
    res = read_csv_feed(text, "gw.csv")
    assert res.records[0].customer == "C03" and res.records[0].quantity == 7


def test_csv_feed_rejects_with_reasons():
    text = (CSV + "e4,C01,api_calls,-1,2026-03-02T10:00:00Z,\n"
            "e5,C01,api_calls,5,2026-03-02T10:00:00,\n"
            "e6,C01,api_calls,5\n")
    res = read_csv_feed(text, "gw.csv")
    assert len(res.records) == 3
    reasons = [r.reason for r in res.rejects]
    assert "negative" in reasons[0]
    assert "offset" in reasons[1]
    assert "fields" in reasons[2]
    assert [r.line for r in res.rejects] == [5, 6, 7]


def test_csv_feed_missing_header_column():
    res = read_csv_feed("event_id,customer,quantity\n", "gw.csv")
    assert res.records == [] and "header" in res.rejects[0].reason


def test_jsonl_units_and_timestamps():
    text = ('{"id": "s1", "customer": "C02", "metric": "storage_gb", "value": "512.5", "ts": 1772323200}\n'
            '{"id": "s2", "customer": "C02", "metric": "storage_gb", "value": "1500", "unit": "MB", "ts": 1772323200000}\n'
            '\n'
            '{"id": "s3", "customer": "C02", "metric": "storage_gb", "value": 2, "unit": "TB", "ts": "2026-03-01T00:00:00Z"}\n')
    res = read_jsonl_feed(text, "st.jsonl")
    assert [r.quantity for r in res.records] == [D("512.5"), D("1.500"), D(2000)]
    assert res.records[0].at == res.records[1].at == res.records[2].at


def test_jsonl_rejects_floats_and_junk():
    text = ('{"id": "s1", "customer": "C02", "metric": "storage_gb", "value": 1.5, "ts": 1772323200}\n'
            '[1, 2]\n'
            '{"id": "s2", "customer": "C02", "metric": "storage_gb", "value": "1", "unit": "PB", "ts": 1772323200}\n')
    res = read_jsonl_feed(text, "st.jsonl")
    assert res.records == [] and len(res.rejects) == 3
    assert to_gb(D(5), None) == D(5)


def test_kv_tokenize_and_parse():
    assert tokenize('a=1 b="two words" c="say \\"hi\\""') == ["a=1", "b=two words", 'c=say "hi"']
    stamp, pairs = parse_line('2026-03-02T09:00:00+01:00 event=se-1 cust=C02 metric=seats qty=12 by="ops bot"')
    assert stamp.startswith("2026-03-02") and pairs["by"] == "ops bot"


def test_kv_feed():
    text = ("# comment\n\n"
            "2026-03-02T09:00:00+01:00 event=se-1 cust=c02 metric=seats qty=12\n"
            "2026-03-02T09:00:00+01:00 event=se-2 cust=C02 metric=seats\n"
            "2026-03-02T09:00:00+01:00 event=se-3 cust=C02 metric=seats qty=3 qty=4\n")
    res = read_kv_feed(text, "seats.log")
    assert [r.event_id for r in res.records] == ["se-1"]
    assert res.records[0].customer == "C02"
    assert [r.line for r in res.rejects] == [4, 5]


def test_merge_replays_and_conflicts():
    a = read_csv_feed(CSV + "e1,C01,api_calls,100,2026-03-02T10:00:00Z,\n"
                            "e2,C01,api_calls,999,2026-03-02T10:00:00Z,\n", "a.csv")
    ing = merge([a], customers={"C01", "C02"}, metrics={"api_calls"})
    assert len(ing.records) == 3 and ing.replays == 1
    assert "conflicts" in ing.rejects[0].reason
    ing2 = merge([a], customers={"C01"}, metrics={"api_calls"})
    assert len(ing2.records) == 2 and "unknown customer" in ing2.rejects[0].reason
