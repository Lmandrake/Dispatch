"""Record-level operations used by the CLI: filter, merge, dedupe, sort."""
import heapq


def sort_key(rec):
    return (rec.timestamp, rec.sensor)


def is_sorted(records):
    prev = None
    for r in records:
        k = sort_key(r)
        if prev is not None and k < prev:
            return False
        prev = k
    return True


def filter_records(records, sensors=None, start=None, end=None, label_contains=None,
                   calibrated=None):
    """Yield records matching every given criterion.

    sensors        -- iterable of sensor ids to keep
    start, end     -- keep start <= timestamp < end
    label_contains -- substring that must occur in the label (case-sensitive)
    calibrated     -- True/False to keep only (un)calibrated readings
    """
    sensor_set = None if sensors is None else set(sensors)
    for r in records:
        if sensor_set is not None and r.sensor not in sensor_set:
            continue
        if start is not None and r.timestamp < start:
            continue
        if end is not None and r.timestamp >= end:
            continue
        if label_contains is not None and label_contains not in r.label:
            continue
        if calibrated is not None and r.calibrated != calibrated:
            continue
        yield r


def merge_sorted(*streams):
    """Merge several record lists, each already sorted by sort_key, stably."""
    return list(heapq.merge(*streams, key=sort_key))


def merge(*streams):
    """Merge record lists; sorted inputs are merged, unsorted ones sorted first."""
    prepared = []
    for s in streams:
        s = list(s)
        if not is_sorted(s):
            s = sorted(s, key=sort_key)
        prepared.append(s)
    return merge_sorted(*prepared)


def dedupe(records):
    """Drop records identical to an earlier one (all fields equal), keeping order."""
    seen = set()
    out = []
    for r in records:
        key = (r.sensor, r.timestamp, type(r.value).__name__, r.value, r.label, r.calibrated)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out
