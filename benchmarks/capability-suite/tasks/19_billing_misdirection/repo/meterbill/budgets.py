"""Customer spend budgets (data/budgets.csv) for portal notifications.

    customer,currency,monthly_budget,warn_percent
    C03,USD,1000.00,80

After a billing run, ``budget_status`` compares each budgeted customer's
invoice total (pre-credit) with the budget, in the budget's currency
(converted at the invoice's rate day, rounded half-up):

    ok        below warn_percent of the budget
    warning   at or above warn_percent, not above the budget
    over      above the budget

A budget in a currency other than the invoice's is allowed (group finance
teams budget in USD).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .csvutil import read_rows
from .errors import ConfigError
from .money import Money, dec


@dataclass(frozen=True)
class Budget:
    customer: str
    amount: Money
    warn_percent: Decimal = Decimal(80)


@dataclass(frozen=True)
class BudgetStatus:
    budget: Budget
    spent: Money
    state: str

    @property
    def percent(self):
        if not self.budget.amount:
            return Decimal(0)
        return (self.spent.amount / self.budget.amount.amount * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def parse_budgets(text, *, source="budgets.csv"):
    out = []
    seen = set()
    for lineno, r in read_rows(text, required=("customer", "currency", "monthly_budget"),
                               optional=("warn_percent",), source=source):
        cid = r["customer"].upper()
        if cid in seen:
            raise ConfigError(f"line {lineno}: two budgets for {cid}", source=source)
        seen.add(cid)
        amount = dec(r["monthly_budget"])
        if amount <= 0:
            raise ConfigError(f"line {lineno}: budget must be positive", source=source)
        warn = dec(r["warn_percent"]) if r["warn_percent"] else Decimal(80)
        if not 0 < warn <= 100:
            raise ConfigError(f"line {lineno}: warn_percent must be in (0, 100]", source=source)
        out.append(Budget(cid, Money(amount, r["currency"]), warn))
    return out


def budget_status(budgets, invoices, converter):
    by_customer = {inv.customer.id: inv for inv in invoices}
    out = []
    for b in budgets:
        inv = by_customer.get(b.customer)
        if inv is None:
            continue
        spent = converter.convert(inv.total, b.amount.currency, inv.rate_day).rounded()
        if spent > b.amount:
            state = "over"
        elif spent.amount * 100 >= b.amount.amount * b.warn_percent:
            state = "warning"
        else:
            state = "ok"
        out.append(BudgetStatus(b, spent, state))
    return out
