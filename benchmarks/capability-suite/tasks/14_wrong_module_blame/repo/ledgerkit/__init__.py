"""ledgerkit: multi-currency ledger files to period-by-account reports.

Pipeline: lexer -> parser -> normalize -> aggregate -> report.
"""

from .aggregate import Totals, aggregate
from .normalize import Normalizer, allocate, normalize
from .parser import parse_ledger
from .pipeline import load, load_files, report_for, run
from .rates import RateTable, load_rates
from .report import build_report, format_money, render_csv, render_text

__all__ = [
    "Normalizer", "RateTable", "Totals", "aggregate", "allocate", "build_report",
    "format_money", "load", "load_files", "load_rates", "normalize", "parse_ledger",
    "render_csv", "render_text", "report_for", "run",
]

__version__ = "0.7.2"
