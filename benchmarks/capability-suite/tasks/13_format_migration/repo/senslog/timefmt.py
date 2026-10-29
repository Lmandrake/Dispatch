"""Timestamp formatting and parsing for human-facing output."""
import re
from datetime import datetime, timezone

_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$")


def format_ts(seconds):
    """Format integer epoch seconds as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC)."""
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(text):
    """Parse ``YYYY-MM-DDTHH:MM:SSZ`` (UTC) or a bare integer into epoch seconds."""
    text = text.strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    m = _ISO_RE.match(text)
    if not m:
        raise ValueError(f"bad timestamp: {text!r}")
    y, mo, d, h, mi, s = (int(g) for g in m.groups())
    dt = datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
    return int(dt.timestamp())
