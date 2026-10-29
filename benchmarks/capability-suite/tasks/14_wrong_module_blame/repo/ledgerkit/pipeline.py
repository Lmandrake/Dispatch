"""End-to-end helpers: text or files in, Totals / Report / text out.

    ledger text --lexer/parser--> Ledger --normalize--> [Posting]
                --aggregate--> Totals --report--> Report --render--> text

``run`` is what the CLI calls; tests and notebooks usually call ``load`` and
``report_for`` directly.
"""

from dataclasses import dataclass
from pathlib import Path

from .aggregate import aggregate
from .normalize import normalize
from .parser import parse_ledger
from .rates import RateTable, load_rates
from .report import build_report, render_csv, render_text, summary_line


@dataclass
class Book:
    ledger: object
    rates: RateTable
    postings: list
    period: str

    @property
    def base(self):
        return self.rates.base


def read_text(path):
    return Path(path).read_text(encoding="utf-8")


def load(ledger_text, rates_text=None, *, period="month", locale=None, source="<memory>",
         strict=False):
    """Parse and normalise; returns a Book."""
    rates = load_rates(rates_text, source=f"{source}:rates") if rates_text else RateTable()
    ledger = parse_ledger(ledger_text, source=source, locale=locale,
                          base_currency=rates.base, strict=strict)
    postings = normalize(ledger, rates, period=period)
    return Book(ledger=ledger, rates=rates, postings=postings, period=period)


def load_files(ledger_path, rates_path=None, **kw):
    rates_text = read_text(rates_path) if rates_path else None
    return load(read_text(ledger_path), rates_text, source=str(ledger_path), **kw)


def totals_for(book, **filters):
    return aggregate(book.postings, **filters)


def report_for(book, *, title=None, depth=None, include_parents=True, notes=None, **filters):
    totals = aggregate(book.postings, **filters)
    if title is None:
        title = f"Ledger by {book.period}"
    return build_report(totals, base_currency=book.base, title=title, depth=depth,
                        include_parents=include_parents, notes=notes)


def run(ledger_text, rates_text=None, *, period="month", fmt="text", locale=None,
        display_locale=None, depth=None, title=None, tags=None, exclude_tags=None,
        accounts=None, show_zero=False, parens=False, strict=False):
    """Full pipeline to a string (``fmt`` is text, csv or summary)."""
    book = load(ledger_text, rates_text, period=period, locale=locale, strict=strict)
    report = report_for(book, title=title, depth=depth, tags=tags,
                        exclude_tags=exclude_tags, accounts=accounts)
    if fmt == "text":
        return render_text(report, locale=display_locale, show_zero=show_zero, parens=parens)
    if fmt == "csv":
        return render_csv(report)
    if fmt == "summary":
        return summary_line(report, locale=display_locale) + "\n"
    raise ValueError(f"unknown format {fmt!r}")
