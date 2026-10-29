"""Tax by jurisdiction (data/tax.toml), per docs/TAX.md.

    [jurisdictions.DE]
    name = "Germany"
    rate = "0.19"
    rounding = "per_invoice"     # or "per_line"
    mode = "half_up"             # money.ROUNDING_MODES
    reverse_charge = true        # B2B customers with a tax id pay no VAT
    label = "VAT"

per_invoice: tax = round(taxable_total * rate, mode).

per_line: the invoice-level discount is first spread over the taxable lines
in proportion to their amounts (money.allocate), then each line's tax is
round((line - its share of the discount) * rate, mode) and the tax is the
sum of the line taxes.  The two methods can differ by a few minor units;
which one applies is a legal requirement of the jurisdiction, not a choice.

Reverse charge: when the jurisdiction has ``reverse_charge = true`` and the
customer has a tax id, the rate is zero and the invoice carries the
reverse-charge note instead.
"""

import tomllib
from dataclasses import dataclass
from decimal import Decimal

from .errors import ConfigError, TaxError
from .jurisdiction import resolve_jurisdiction
from .money import ROUNDING_MODES, ZERO, Money, allocate, dec, round_to

REVERSE_CHARGE_NOTE = "Reverse charge: VAT to be accounted for by the recipient."


@dataclass(frozen=True)
class TaxRule:
    code: str
    name: str
    rate: Decimal
    rounding: str = "per_invoice"
    mode: str = "half_up"
    reverse_charge: bool = False
    label: str = "Tax"

    def percent(self):
        """Rate as display text: Decimal('0.19') -> '19%', '0.08875' -> '8.875%'."""
        pct = (self.rate * 100).normalize()
        text = f"{pct:f}"
        return f"{text}%"


@dataclass(frozen=True)
class TaxResult:
    rule: TaxRule
    rate: Decimal          # effective rate (0 under reverse charge)
    taxable: Money
    tax: Money
    reverse_charged: bool = False
    line_taxes: tuple = ()

    @property
    def note(self):
        return REVERSE_CHARGE_NOTE if self.reverse_charged else ""


def parse_tax(text, *, source="tax.toml"):
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML: {e}", source=source) from None
    rules = {}
    for code, spec in data.get("jurisdictions", {}).items():
        try:
            rate = dec(str(spec["rate"]))
        except KeyError:
            raise ConfigError(f"{code}: rate is required", source=source) from None
        if not ZERO <= rate < 1:
            raise ConfigError(f"{code}: rate must be in [0, 1)", source=source)
        rounding = spec.get("rounding", "per_invoice")
        if rounding not in ("per_invoice", "per_line"):
            raise ConfigError(f"{code}: rounding must be per_invoice or per_line", source=source)
        mode = spec.get("mode", "half_up")
        if mode not in ROUNDING_MODES:
            raise ConfigError(f"{code}: unknown rounding mode {mode!r}", source=source)
        rules[code.upper()] = TaxRule(
            code=code.upper(),
            name=str(spec.get("name", code)),
            rate=rate,
            rounding=rounding,
            mode=mode,
            reverse_charge=bool(spec.get("reverse_charge", False)),
            label=str(spec.get("label", "Tax")),
        )
    if not rules:
        raise ConfigError("no jurisdictions defined", source=source)
    return rules


class TaxTable:
    def __init__(self, rules):
        self.rules = dict(rules)

    def rule(self, code):
        try:
            return self.rules[code.upper()]
        except KeyError:
            raise TaxError(f"unknown tax jurisdiction {code!r}") from None

    def compute(self, customer, lines, discount):
        """Tax for an invoice.

        ``lines``: rounded Money amounts of the taxable lines (invoice currency).
        ``discount``: the rounded, non-negative invoice-level discount, applied
        before tax (docs/DISCOUNTS.md).
        """
        rule = self.rule(resolve_jurisdiction(customer, self))
        cur = discount.currency
        subtotal = Money.zero(cur)
        for amount in lines:
            subtotal = subtotal + amount
        taxable = subtotal - discount
        if taxable.is_negative():
            raise TaxError("discount exceeds the taxable subtotal")
        if rule.reverse_charge and customer.is_business:
            return TaxResult(rule, ZERO, taxable, Money.zero(cur), True,
                             tuple(Money.zero(cur) for _ in lines))
        if rule.rounding == "per_invoice":
            tax = Money(round_to(taxable.amount * rule.rate, cur, rule.mode), cur)
            return TaxResult(rule, rule.rate, taxable, tax)
        # per_line
        positive = [a if not a.is_negative() else Money.zero(cur) for a in lines]
        if discount and any(positive):
            shares = allocate(discount, [a.amount for a in positive])
        else:
            shares = [Money.zero(cur) for _ in lines]
        line_taxes = []
        for amount, share in zip(lines, shares):
            net = amount - share
            line_taxes.append(Money(round_to(net.amount * rule.rate, cur, rule.mode), cur))
        tax = Money.zero(cur)
        for t in line_taxes:
            tax = tax + t
        return TaxResult(rule, rule.rate, taxable, tax, False, tuple(line_taxes))
