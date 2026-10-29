"""Plain-text table rendering for the CLI."""


def render_table(headers, rows, align=None):
    """Render ``rows`` (sequences of str) under ``headers`` as an aligned text table.

    ``align`` is a string with one character per column, ``l`` or ``r``
    (default: all left).  Columns are separated by two spaces; a line of
    dashes separates the header from the body.  Trailing spaces are stripped.
    """
    headers = [str(h) for h in headers]
    rows = [[str(c) for c in r] for r in rows]
    n = len(headers)
    for r in rows:
        if len(r) != n:
            raise ValueError(f"row has {len(r)} cells, table has {n} columns")
    if align is None:
        align = "l" * n
    if len(align) != n:
        raise ValueError("align must have one character per column")
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(c))

    def fmt(cells):
        out = []
        for c, w, a in zip(cells, widths, align):
            out.append(c.rjust(w) if a == "r" else c.ljust(w))
        return "  ".join(out).rstrip()

    lines = [fmt(headers), "  ".join("-" * w for w in widths)]
    lines.extend(fmt(r) for r in rows)
    return "\n".join(lines)


def format_float(value, digits=6):
    """Fixed short formatting used in tables: up to ``digits`` significant digits."""
    if value != value:
        return "nan"
    if value in (float("inf"), float("-inf")):
        return "inf" if value > 0 else "-inf"
    text = f"{value:.{digits}g}"
    if "e" not in text and "." not in text and abs(value) < 10 ** digits:
        return text
    return text


def kv_lines(pairs):
    """``key: value`` lines with keys padded to the same width."""
    if not pairs:
        return []
    width = max(len(k) for k, _ in pairs) + 1
    return [f"{(k + ':').ljust(width)} {v}" for k, v in pairs]
