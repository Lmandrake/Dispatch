"""A Markdown summary of an archive (``tsarc report``)."""
from . import types as T
from .render import format_float
from .stats import column_stats, time_stats
from .timeutil import format_ts


def _md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")
    return out


def _fmt(type_, v):
    if v is None:
        return ""
    if type_ == T.TS:
        return format_ts(v)
    if isinstance(v, float):
        return format_float(v)
    return str(v)


def markdown_report(reader, title=None):
    table = reader.table
    lines = [f"# {title or reader.path.name}", ""]
    lines.append(f"- format version: {reader.version}")
    lines.append(f"- rows: {reader.num_rows}")
    ts = time_stats(table)
    if ts:
        first, last, span, rate = ts
        lines.append(f"- time: {format_ts(first)} .. {format_ts(last)} ({span:g} s)")
    if reader.metadata:
        lines.append("- metadata: " + ", ".join(f"`{k}` = {v}" for k, v in reader.metadata.items()))
    lines.append("")
    lines.append("## Columns")
    lines.append("")
    rows = []
    for st in column_stats(table):
        mn = mx = ""
        if st.type != T.BOOL:
            mn, mx = _fmt(st.type, st.min), _fmt(st.type, st.max)
        rows.append([f"`{st.name}`", st.type, st.count, mn, mx,
                     _fmt(T.FLOAT, st.mean) if st.mean is not None else ""])
    lines.extend(_md_table(["column", "type", "count", "min", "max", "mean"], rows))
    lines.append("")
    return "\n".join(lines)
