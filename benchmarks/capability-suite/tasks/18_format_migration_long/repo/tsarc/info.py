"""The report printed by ``tsarc info``."""
from .fileutil import human_size
from .metadata import format_lines
from .render import kv_lines
from .timeutil import format_ts


def info_lines(reader, path_text=None):
    """Lines describing an open archive.

    Layout::

        file: data.tsa
        version: 2
        size: 1234 bytes (1.2 KiB)
        rows: 100
        columns: 3
          ts    ts
          temp  float
          site  str
        range: 2026-03-01T00:00:00Z .. 2026-03-01T01:39:00Z
        metadata:
          source = lab
    """
    lines = [
        f"file: {path_text if path_text is not None else reader.path}",
        f"version: {reader.version}",
        f"size: {reader.size} bytes ({human_size(reader.size)})",
        f"rows: {reader.num_rows}",
        f"columns: {len(reader.schema)}",
    ]
    lines.extend("  " + line for line in reader.schema.describe())
    rng = reader.time_range()
    if rng is None:
        lines.append("range: -")
    else:
        lines.append(f"range: {format_ts(rng[0])} .. {format_ts(rng[1])}")
    lines.extend(format_lines(reader.metadata))
    return lines


def summary_pairs(reader):
    """Short key/value pairs (used by ``tsarc ls``)."""
    rng = reader.time_range()
    return [
        ("version", str(reader.version)),
        ("rows", str(reader.num_rows)),
        ("columns", reader.schema.to_text()),
        ("range", "-" if rng is None else f"{format_ts(rng[0])} .. {format_ts(rng[1])}"),
    ]


def summary_lines(reader):
    return kv_lines(summary_pairs(reader))
