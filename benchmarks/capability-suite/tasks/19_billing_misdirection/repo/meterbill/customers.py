"""Customer master data (data/customers.csv).

Columns:

    id            short id, e.g. C07; unique
    name          legal name, printed on the invoice
    timezone      IANA zone; billing periods are local to it
    anchor_day    day of month the billing cycle starts (1-31, see periods.py)
    currency      invoice currency (ISO code)
    jurisdiction  region of the billing address (a tax.toml code)
    service_region  region where the service is used, optional
    tax_override  jurisdiction set by the tax team, optional
    tax_id        VAT/GST registration, optional; enables reverse charge
    email         billing contact
    terms_days    payment terms in days (default 30)
    status        active | suspended | closed (default active)
"""

import re
from dataclasses import dataclass

from . import currency as _cur
from .csvutil import read_rows
from .errors import ConfigError, UnknownCustomer
from .timeutil import zone

_ID = re.compile(r"^[A-Z][A-Z0-9]{1,11}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
STATUSES = ("active", "suspended", "closed")


@dataclass(frozen=True)
class Customer:
    id: str
    name: str
    timezone: str
    anchor_day: int
    currency: str
    jurisdiction: str
    tax_id: str = ""
    email: str = ""
    terms_days: int = 30
    status: str = "active"
    service_region: str = ""
    tax_override: str = ""

    @property
    def is_business(self):
        """A registered business (has a tax id)."""
        return bool(self.tax_id)

    @property
    def billable(self):
        return self.status in ("active", "suspended")


def parse_customers(text, *, source="customers.csv"):
    """Parse customers.csv text into a dict id -> Customer (file order kept)."""
    rows = read_rows(
        text,
        required=("id", "name", "timezone", "anchor_day", "currency", "jurisdiction"),
        optional=("tax_id", "email", "terms_days", "status", "service_region", "tax_override"),
        source=source,
    )
    out = {}
    for lineno, r in rows:
        cid = r["id"].upper()
        key = f"line {lineno}"
        if not _ID.match(cid):
            raise ConfigError(f"bad customer id {r['id']!r}", source=source, key=key)
        if cid in out:
            raise ConfigError(f"duplicate customer id {cid}", source=source, key=key)
        try:
            zone(r["timezone"])
        except ConfigError as e:
            raise ConfigError(str(e), source=source, key=key) from None
        try:
            anchor = int(r["anchor_day"])
        except ValueError:
            raise ConfigError(f"anchor_day {r['anchor_day']!r} is not a number", source=source, key=key) from None
        if not 1 <= anchor <= 31:
            raise ConfigError(f"anchor_day {anchor} out of range", source=source, key=key)
        cur = _cur.get(r["currency"]).code
        terms = int(r["terms_days"]) if r["terms_days"] else 30
        if terms < 0 or terms > 120:
            raise ConfigError(f"terms_days {terms} out of range", source=source, key=key)
        status = (r["status"] or "active").lower()
        if status not in STATUSES:
            raise ConfigError(f"unknown status {status!r}", source=source, key=key)
        email = r["email"]
        if email and not _EMAIL.match(email):
            raise ConfigError(f"bad email {email!r}", source=source, key=key)
        out[cid] = Customer(
            id=cid,
            name=r["name"],
            timezone=r["timezone"],
            anchor_day=anchor,
            currency=cur,
            jurisdiction=r["jurisdiction"].upper(),
            tax_id=r["tax_id"].replace(" ", "").upper(),
            email=email,
            terms_days=terms,
            status=status,
            service_region=r["service_region"].upper(),
            tax_override=r["tax_override"].upper(),
        )
    return out


class CustomerBook:
    """Lookup over parsed customers."""

    def __init__(self, customers):
        self._by_id = dict(customers)

    def __len__(self):
        return len(self._by_id)

    def __iter__(self):
        return iter(sorted(self._by_id.values(), key=lambda c: c.id))

    def __contains__(self, cid):
        return cid in self._by_id

    def get(self, cid):
        try:
            return self._by_id[cid]
        except KeyError:
            raise UnknownCustomer(f"unknown customer {cid!r}") from None

    def billable(self):
        return [c for c in self if c.billable]

    def ids(self):
        return sorted(self._by_id)
