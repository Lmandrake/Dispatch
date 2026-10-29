"""Command line: ``python3 -m ledgerkit.cli LEDGER [--rates FILE] [options]``."""

import argparse
import sys

from .dates import PERIOD_KINDS
from .errors import LedgerError
from .locales import known_locales
from .pipeline import read_text, run


def build_parser():
    p = argparse.ArgumentParser(prog="ledgerkit", description="Period-by-account ledger reports.")
    p.add_argument("ledger", help="ledger file")
    p.add_argument("--rates", help="exchange-rates file")
    p.add_argument("--period", choices=PERIOD_KINDS, default="month")
    p.add_argument("--format", dest="fmt", choices=("text", "csv", "summary"), default="text")
    p.add_argument("--locale", choices=known_locales(), help="input locale (default en_US)")
    p.add_argument("--display-locale", choices=known_locales(), help="output number style")
    p.add_argument("--depth", type=int, help="truncate accounts to N levels")
    p.add_argument("--title")
    p.add_argument("--tag", action="append", dest="tags", help="only postings with this tag")
    p.add_argument("--exclude-tag", action="append", dest="exclude_tags")
    p.add_argument("--account", action="append", dest="accounts",
                   help="only this account and its children")
    p.add_argument("--show-zero", action="store_true")
    p.add_argument("--parens", action="store_true", help="negatives as (1.00)")
    p.add_argument("--strict", action="store_true", help="unknown accounts are errors")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        ledger_text = read_text(args.ledger)
        rates_text = read_text(args.rates) if args.rates else None
        out = run(ledger_text, rates_text, period=args.period, fmt=args.fmt,
                  locale=args.locale, display_locale=args.display_locale, depth=args.depth,
                  title=args.title, tags=args.tags, exclude_tags=args.exclude_tags,
                  accounts=args.accounts, show_zero=args.show_zero, parens=args.parens,
                  strict=args.strict)
    except (OSError, LedgerError) as exc:
        print(f"ledgerkit: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
