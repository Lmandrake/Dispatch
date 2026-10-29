"""Plain-text table rendering.

    render_table(["Key", "Pts"], [["WEB-1", 3]], align="lr")

produces::

    Key    Pts
    -----  ---
    WEB-1    3

Columns are separated by two spaces; each column is as wide as its widest
cell (header included).  ``align`` has one letter per column, ``l`` or
``r``; missing letters default to ``l``.  Trailing spaces are stripped from
every line.  With no rows, only the header and rule are printed.
"""


def _cell(value):
    if value is None:
        return ""
    return str(value)


def render_table(headers, rows, align=""):
    headers = [_cell(h) for h in headers]
    rows = [[_cell(c) for c in row] for row in rows]
    ncols = len(headers)
    for row in rows:
        if len(row) != ncols:
            raise ValueError(f"row has {len(row)} cells, expected {ncols}: {row!r}")
    widths = [len(h) for h in headers]
    for row in rows:
        for i, c in enumerate(row):
            widths[i] = max(widths[i], len(c))
    align = (align + "l" * ncols)[:ncols]

    def line(cells):
        out = []
        for c, w, a in zip(cells, widths, align):
            out.append(c.rjust(w) if a == "r" else c.ljust(w))
        return "  ".join(out).rstrip()

    lines = [line(headers), line(["-" * w for w in widths])]
    lines.extend(line(r) for r in rows)
    return "\n".join(lines)


def truncate(text, width):
    """``text`` cut to ``width`` characters, ending in ``...`` when cut."""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."
