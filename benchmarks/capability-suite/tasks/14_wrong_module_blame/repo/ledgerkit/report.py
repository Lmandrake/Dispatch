"""Build and render period-by-account reports.

This is the only module that rounds money.  Every displayed number is rounded
once, directly from the exact Decimal handed in, to the currency's display
places with ROUND_HALF_UP (``money.round_money``).  Never round twice (for
instance to MICRO and then to cents): ``1.0049999`` must show as ``1.00``.

Layout of ``render_text``::

    <title>
    <base currency> | <period> ... | Total
    -------------------------------------
    Expenses               1,234.57   ...   9,876.54
      Travel                 234.00   ...
        Air                  200.00   ...
    =====================================
    TOTAL                  1,234.57   ...

Account labels are indented two spaces per level below the top; numeric
columns are right-aligned to the widest cell (header included) of the column.
Zero cells are shown as ``-`` unless ``show_zero`` is set.
"""

from decimal import Decimal

from .accounts import split_name, truncate
from .locales import get_locale
from .models import Report, ReportRow
from .money import ZERO, group_digits, places_for, round_money

DASH = "-"
GAP = "  "


def format_money(value, places=2, locale=None, *, parens=False, plus=False):
    """Format a Decimal for display.

    Rounded to ``places`` decimals, half away from zero, grouped with the
    locale's display separators.  ``parens`` shows negatives as ``(1.00)``;
    ``plus`` prefixes positives with ``+``.  A value that rounds to zero is
    shown unsigned (``-0.004`` -> ``0.00``).
    """
    spec = get_locale(locale)
    rounded = round_money(Decimal(value), places)
    negative = rounded < 0
    if rounded == 0:
        negative = False
    text = f"{abs(rounded):.{places}f}"
    if places:
        whole, frac = text.split(".")
    else:
        whole, frac = text, ""
    whole = group_digits(whole, spec.display_group)
    body = whole + (spec.display_decimal + frac if frac else "")
    if negative:
        return f"({body})" if parens else f"-{body}"
    if plus and rounded > 0:
        return "+" + body
    return body


def build_report(totals, *, base_currency="USD", title="Report", depth=None,
                 periods=None, include_parents=True, notes=None):
    """A Report with one row per account (tree order) and a grand-total row.

    Cell values are the exact Decimal balances from ``totals``; nothing is
    rounded until rendering.
    """
    periods = list(periods) if periods is not None else list(totals.periods)
    names = totals.tree() if include_parents else totals.accounts()
    if depth:
        names = sorted({truncate(n, depth) for n in names})
    rows = []
    for name in names:
        level = len(split_name(name)) - 1
        cells = {p: totals.balance(name, p) for p in periods}
        rows.append(ReportRow(label=name, cells=cells, total=totals.balance(name),
                              indent=level))
    grand = ReportRow(label="TOTAL", cells={p: totals.grand(p) for p in periods},
                      total=totals.grand(), is_total=True)
    return Report(title=title, base_currency=base_currency, periods=periods,
                  rows=rows, grand=grand, notes=list(notes or []))


def _label(row, short):
    if row.is_total:
        return row.label
    name = split_name(row.label)[-1] if short else row.label
    return "  " * row.indent + name


def _cell(value, places, locale, show_zero, parens):
    if value == ZERO and not show_zero:
        return DASH
    return format_money(value, places, locale, parens=parens)


def render_rows(report, *, locale=None, show_zero=False, parens=False, short_labels=True):
    """The table as a list of rows of strings (header first, no rules)."""
    places = places_for(report.base_currency)
    header = [report.base_currency] + list(report.periods) + ["Total"]
    body = []
    for row in report.rows + [report.grand]:
        cells = [_cell(row.cells.get(p, ZERO), places, locale, show_zero, parens)
                 for p in report.periods]
        cells.append(_cell(row.total, places, locale, show_zero, parens))
        body.append([_label(row, short_labels)] + cells)
    return [header] + body


def render_text(report, *, locale=None, show_zero=False, parens=False, short_labels=True):
    """Plain-text table (see module docstring for the layout)."""
    table = render_rows(report, locale=locale, show_zero=show_zero, parens=parens,
                        short_labels=short_labels)
    ncols = len(table[0])
    widths = [max(len(r[i]) for r in table) for i in range(ncols)]
    lines = [report.title]

    def fmt(r):
        parts = [r[0].ljust(widths[0])]
        parts += [r[i].rjust(widths[i]) for i in range(1, ncols)]
        return GAP.join(parts).rstrip()

    lines.append(fmt(table[0]))
    rule_len = sum(widths) + len(GAP) * (ncols - 1)
    lines.append("-" * rule_len)
    for r in table[1:-1]:
        lines.append(fmt(r))
    lines.append("=" * rule_len)
    lines.append(fmt(table[-1]))
    for note in report.notes:
        lines.append(f"* {note}")
    return "\n".join(lines) + "\n"


def render_csv(report, *, places=None):
    """CSV with full account names; numbers rounded, ungrouped, ``.`` decimal."""
    import csv
    import io

    places = places_for(report.base_currency) if places is None else places
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["account"] + list(report.periods) + ["total"])
    for row in report.rows + [report.grand]:
        vals = [row.cells.get(p, ZERO) for p in report.periods] + [row.total]
        w.writerow([row.label] + [f"{round_money(v, places):.{places}f}" for v in vals])
    return buf.getvalue()


def summary_line(report, *, locale=None):
    """One line: ``TOTAL USD 1,234.57 over 3 periods``."""
    places = places_for(report.base_currency)
    amount = format_money(report.grand.total, places, locale)
    n = len(report.periods)
    return f"TOTAL {report.base_currency} {amount} over {n} period{'s' if n != 1 else ''}"
