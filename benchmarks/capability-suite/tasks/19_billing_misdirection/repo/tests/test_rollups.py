"""Hourly and daily usage rollups."""

from decimal import Decimal

from meterbill.csvutil import read_rows
from meterbill.pipeline import run_billing
from meterbill.rollups import daily, hourly, peak, render_rollups, rollups_to_csv, total_records

from .helpers import DATA, catalog, rec

D = Decimal
METRICS = catalog().metrics
TZ = {"A": "America/New_York", "B": "UTC", "J": "Asia/Tokyo"}


def test_daily_sum_uses_local_date():
    # 2026-03-05T03:30Z is still Mar 4 evening in New York (UTC-5)
    rs = [rec("A", "api_calls", 10, "2026-03-05T03:30:00Z"), rec("A", "api_calls", 5, "2026-03-05T12:00:00Z"),
          rec("A", "api_calls", 1, "2026-03-05T04:59:59Z")]
    out = daily(rs, TZ, METRICS)
    assert [(r.bucket, r.quantity, r.records) for r in out] == [("2026-03-04", D(11), 2), ("2026-03-05", D(5), 1)]


def test_daily_respects_aggregation_max_and_last():
    rs = [rec("B", "seats", 4, "2026-03-01T01:00:00Z"), rec("B", "seats", 9, "2026-03-01T02:00:00Z"),
          rec("B", "seats", 6, "2026-03-01T03:00:00Z"),
          rec("B", "storage_gb", 50, "2026-03-01T01:00:00Z"), rec("B", "storage_gb", 70, "2026-03-01T20:00:00Z"),
          rec("B", "storage_gb", 60, "2026-03-01T10:00:00Z")]
    got = {r.metric: r.quantity for r in daily(rs, TZ, METRICS)}
    assert got == {"seats": D(9), "storage_gb": D(70)}


def test_hourly_buckets_and_labels():
    rs = [rec("J", "api_calls", 1, "2026-03-05T14:10:00Z"), rec("J", "api_calls", 2, "2026-03-05T14:50:00Z"),
          rec("J", "api_calls", 4, "2026-03-05T15:00:00Z")]
    out = hourly(rs, TZ, METRICS)
    assert [(r.bucket, r.quantity) for r in out] == [("2026-03-05T23:00", D(3)), ("2026-03-06T00:00", D(4))]


def test_hourly_fall_back_keeps_two_distinct_01_hours():
    # New York falls back 2026-11-01: 05:30Z and 06:30Z are both 01:30 local
    rs = [rec("A", "api_calls", 1, "2026-11-01T05:30:00Z"), rec("A", "api_calls", 1, "2026-11-01T06:30:00Z")]
    out = hourly(rs, TZ, METRICS)
    assert [r.bucket for r in out] == ["2026-11-01T01:00", "2026-11-01T01:00"]
    assert len(daily(rs, TZ, METRICS)) == 1


def test_fill_gaps():
    rs = [rec("B", "api_calls", 1, "2026-03-01T10:00:00Z"), rec("B", "api_calls", 2, "2026-03-04T10:00:00Z")]
    out = daily(rs, TZ, METRICS, fill_gaps=True)
    assert [r.bucket for r in out] == ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04"]
    assert [r.records for r in out] == [1, 0, 0, 1]
    assert len(daily(rs, TZ, METRICS)) == 2


def test_peak_and_totals():
    rs = [rec("B", "api_calls", 1, "2026-03-01T10:00:00Z"), rec("B", "api_calls", 7, "2026-03-02T10:00:00Z"),
          rec("B", "api_calls", 3, "2026-03-03T10:00:00Z")]
    out = daily(rs, TZ, METRICS)
    assert peak(out).bucket == "2026-03-02" and total_records(out) == 3
    assert peak([]) is None


def test_csv_round_trip_and_precision():
    rs = [rec("B", "storage_gb", "12.5", "2026-03-01T10:00:00Z"), rec("B", "api_calls", 1234567, "2026-03-01T10:00:00Z")]
    text = rollups_to_csv(daily(rs, TZ, METRICS), METRICS)
    rows = {r["metric"]: r for _, r in read_rows(text, required=("customer", "metric", "bucket", "quantity", "records"))}
    assert rows["storage_gb"]["quantity"] == "12.500" and rows["api_calls"]["quantity"] == "1234567"
    assert text.splitlines()[0] == "customer,metric,bucket,quantity,records"


def test_render_and_empty():
    assert render_rollups([], METRICS) == "No usage.\n"
    out = render_rollups(daily([rec("B", "api_calls", 1500, "2026-03-01T10:00:00Z")], TZ, METRICS), METRICS)
    assert "1,500" in out and "2026-03-01" in out


def test_sample_data_daily_matches_period_total():
    run = run_billing(DATA, "2026-03", customers=["C01"])
    inv = run.invoice("C01")
    recs = [r for r in run.ingested.records if r.customer == "C01" and inv.period.contains(r.at)]
    tz = {"C01": "America/New_York"}
    rolls = [r for r in daily(recs, tz, METRICS) if r.metric == "api_calls"]
    assert sum(r.quantity for r in rolls) == sum(r.quantity for r in recs if r.metric == "api_calls")
