"""Which tax jurisdiction applies to a customer (docs/TAX.md, "Jurisdiction").

A customer record can name up to three regions: ``jurisdiction`` (the
billing address, always present), ``service_region`` and ``tax_override``.
Which one wins is a tax-policy decision recorded in docs/TAX.md.

Regions are tax.toml codes: a country (``DE``) or a country-subdivision
(``US-TX``).  A subdivision that is not in the tax table falls back to its
country when the country is (``US-WA`` -> ``US``); otherwise the region is
unknown and the next candidate is tried.  If no candidate is known the
customer cannot be taxed and TaxError is raised.
"""

from .errors import TaxError

PRECEDENCE = ("tax_override", "jurisdiction", "service_region")

EU = frozenset("AT BE BG CY CZ DE DK EE ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK".split())


def country_of(region):
    return region.split("-", 1)[0]


def is_eu(region):
    return country_of(region) in EU


def known(region, table):
    """The tax-table code for ``region``, or None."""
    if not region:
        return None
    code = region.upper()
    if code in table.rules:
        return code
    country = country_of(code)
    if country != code and country in table.rules:
        return country
    return None


def candidates(customer):
    """(field, region) pairs in precedence order, empty fields left out."""
    out = []
    for name in PRECEDENCE:
        value = getattr(customer, name, "")
        if value:
            out.append((name, value.upper()))
    return out


def resolve_jurisdiction(customer, table):
    """Tax-table code of the jurisdiction that applies to ``customer``."""
    tried = []
    for name, region in candidates(customer):
        code = known(region, table)
        if code is not None:
            return code
        tried.append(f"{name}={region}")
    raise TaxError(f"customer {customer.id}: no known tax jurisdiction ({', '.join(tried) or 'none given'})")


def explain(customer, table):
    """Human-readable account of the resolution, for support."""
    lines = []
    chosen = None
    for name, region in candidates(customer):
        code = known(region, table)
        if code is None:
            lines.append(f"{name}: {region} (not in the tax table)")
            continue
        if chosen is None:
            chosen = code
            lines.append(f"{name}: {region} -> {code} (applies)")
        else:
            lines.append(f"{name}: {region} -> {code} (not used)")
    return lines
