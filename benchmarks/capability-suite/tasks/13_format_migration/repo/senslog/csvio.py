"""CSV export and import.

Columns, in order: sensor, timestamp, value, label, calibrated

* timestamp is written with timefmt.format_ts and read with timefmt.parse_ts
* value is written with repr() for floats and str() for ints; on import a
  value containing '.', 'e', 'E', 'inf' or 'nan' is a float, otherwise an int
* calibrated is written as 1 or 0
"""
import csv
import io

from .record import Record
from .timefmt import format_ts, parse_ts

COLUMNS = ["sensor", "timestamp", "value", "label", "calibrated"]


def _format_value(value):
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _parse_value(text):
    t = text.strip()
    low = t.lower()
    if any(c in t for c in ".eE") or "inf" in low or "nan" in low:
        return float(t)
    return int(t)


def _parse_bool(text):
    t = text.strip().lower()
    if t in ("1", "true", "yes", "y"):
        return True
    if t in ("0", "false", "no", "n", ""):
        return False
    raise ValueError(f"bad boolean: {text!r}")


def records_to_csv(records, fh, header=True):
    w = csv.writer(fh, lineterminator="\n")
    if header:
        w.writerow(COLUMNS)
    n = 0
    for r in records:
        w.writerow([r.sensor, format_ts(r.timestamp), _format_value(r.value), r.label,
                    1 if r.calibrated else 0])
        n += 1
    return n


def records_to_csv_text(records, header=True):
    buf = io.StringIO()
    records_to_csv(records, buf, header=header)
    return buf.getvalue()


class CsvImportError(ValueError):
    def __init__(self, line, message):
        super().__init__(f"line {line}: {message}")
        self.line = line


def records_from_csv(fh):
    """Parse CSV rows into Records.  A header row (first cell 'sensor') is skipped."""
    out = []
    reader = csv.reader(fh)
    for lineno, row in enumerate(reader, start=1):
        if not row or all(not c.strip() for c in row):
            continue
        if lineno == 1 and row[0].strip().lower() == "sensor":
            continue
        if len(row) < 3:
            raise CsvImportError(lineno, f"expected at least 3 columns, got {len(row)}")
        if len(row) > len(COLUMNS):
            raise CsvImportError(lineno, f"too many columns ({len(row)})")
        try:
            sensor = int(row[0])
            ts = parse_ts(row[1])
            value = _parse_value(row[2])
            label = row[3] if len(row) > 3 else ""
            calibrated = _parse_bool(row[4]) if len(row) > 4 else False
            out.append(Record(sensor, ts, value, label, calibrated))
        except (TypeError, ValueError) as exc:
            if isinstance(exc, CsvImportError):
                raise
            raise CsvImportError(lineno, str(exc)) from None
    return out


def records_from_csv_text(text):
    return records_from_csv(io.StringIO(text))
