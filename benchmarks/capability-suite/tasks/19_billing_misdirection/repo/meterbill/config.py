"""Loading a data directory.

A data directory holds:

    customers.csv  subscriptions.csv  catalog.toml  tax.toml  fx_rates.csv
    coupons.toml   redemptions.csv    credits.csv   dunning.toml
    receivables.csv
    feeds/         the metering feeds for the cycle(s)

coupons/redemptions/credits/dunning/receivables are optional.
"""

from dataclasses import dataclass
from pathlib import Path

from .catalog import parse_catalog
from .credits import parse_credits
from .customers import CustomerBook, parse_customers
from .discounts import parse_coupons, parse_redemptions
from .dunning import parse_receivables, parse_schedule
from .errors import ConfigError
from .fx import Converter, parse_rates
from .subscriptions import parse_subscriptions
from .jurisdiction import resolve_jurisdiction
from .tax import TaxTable, parse_tax


@dataclass
class DataSet:
    root: Path
    customers: CustomerBook
    catalog: object
    subscriptions: object
    tax: TaxTable
    rates: object
    coupons: dict
    redemptions: list
    grants: list
    schedule: list
    receivables: list

    @property
    def feeds_dir(self):
        return self.root / "feeds"

    def converter(self):
        return Converter(self.rates)


def _read(root, name, *, optional=False):
    p = root / name
    if not p.exists():
        if optional:
            return None
        raise ConfigError(f"missing {name}", source=str(root))
    return p.read_text(encoding="utf-8")


def load_dataset(root):
    root = Path(root)
    if not root.is_dir():
        raise ConfigError(f"not a directory: {root}")
    customers = CustomerBook(parse_customers(_read(root, "customers.csv")))
    catalog = parse_catalog(_read(root, "catalog.toml"))
    subs = parse_subscriptions(_read(root, "subscriptions.csv"), customers=customers, catalog=catalog)
    tax = TaxTable(parse_tax(_read(root, "tax.toml")))
    for c in customers:
        tax.rule(resolve_jurisdiction(c, tax))
    rates = parse_rates(_read(root, "fx_rates.csv"))
    text = _read(root, "coupons.toml", optional=True)
    coupons = parse_coupons(text) if text else {}
    text = _read(root, "redemptions.csv", optional=True)
    redemptions = parse_redemptions(text, coupons=coupons, customers=customers) if text else []
    text = _read(root, "credits.csv", optional=True)
    grants = parse_credits(text, customers=customers) if text else []
    text = _read(root, "dunning.toml", optional=True)
    schedule = parse_schedule(text) if text else []
    text = _read(root, "receivables.csv", optional=True)
    receivables = parse_receivables(text) if text else []
    return DataSet(root, customers, catalog, subs, tax, rates, coupons, redemptions, grants, schedule, receivables)
