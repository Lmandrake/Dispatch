"""Plan migration advice: is the customer on the cheapest plan for their usage?

Given the catalogue, a customer, the plan they are on and one cycle of
usage (``{metric: billed quantity}``, i.e. already aggregated), recommend
the cheapest *non-legacy* plan in the customer's *currency family* and say
how much they would have saved.

Currency family: plans priced in the customer's own invoice currency.  A
customer invoiced in EUR is only compared with EUR plans, so the advice is
not driven by exchange-rate noise.  Every plan is quoted with
``quotes.compare`` (the very same rating code as invoicing), in the
customer's currency, on the day ``on``, pre-tax.

The current plan is quoted even when it is legacy, because it is the baseline
to beat.  A legacy plan is never *recommended as a move*: it appears in the
result only as the plan to stay on, when no eligible plan is strictly
cheaper (a tie also means stay).
Savings are baseline total minus the recommended plan's total, never
negative.  This module does not look at contract commitments or notice
periods: it is a suggestion for a human to read.
"""

from dataclasses import dataclass

from .money import Money
from .quotes import compare, quote
from .render.fmt import format_money


@dataclass(frozen=True)
class MigrationAdvice:
    customer: str
    currency: str
    current: object           # Quote of the current plan
    recommended: object       # Quote of the plan to move to (== current when staying)
    savings: Money            # >= 0
    alternatives: tuple       # all eligible Quotes, cheapest first

    @property
    def should_switch(self):
        return self.recommended.plan != self.current.plan

    @property
    def savings_percent(self):
        """Savings as a percent of the current total, one decimal, "0.0" when the baseline is free."""
        base = self.current.total.amount
        if not base:
            return "0.0"
        return f"{self.savings.amount * 100 / base:.1f}"


def eligible_plans(catalog, currency):
    """Non-legacy plan ids whose price currency is ``currency``, sorted."""
    return [p.id for p in catalog.plans() if not p.legacy and p.currency == currency]


def recommend(catalog, customer, current_plan, usage, converter, on):
    """MigrationAdvice for ``customer`` currently on ``current_plan`` (UnknownPlan if absent)."""
    cur = customer.currency
    catalog.plan(current_plan)
    everyone = compare(catalog, usage, cur, converter, on, include_legacy=True)
    family = set(eligible_plans(catalog, cur))
    alternatives = tuple(q for q in everyone if q.plan in family)
    baseline = next((q for q in everyone if q.plan == current_plan), None) or quote(
        catalog, current_plan, usage, cur, converter, on)
    if not alternatives:
        return MigrationAdvice(customer.id, cur, baseline, baseline, Money.zero(cur), ())
    best = alternatives[0]
    if best.total >= baseline.total:
        best = baseline
    return MigrationAdvice(customer.id, cur, baseline, best, baseline.total - best.total, alternatives)


def render_advice(advice):
    """Text report for one customer."""
    cur = advice.currency
    out = [f"Plan review for {advice.customer} (pre-tax, {cur})",
           f"  Current plan:      {advice.current.plan:<14}{format_money(advice.current.total):>18}"]
    if advice.should_switch:
        out.append(f"  Recommended plan:  {advice.recommended.plan:<14}{format_money(advice.recommended.total):>18}")
        out.append(f"  Saving per cycle:  {format_money(advice.savings)} ({advice.savings_percent}%)")
    else:
        out.append("  Recommendation:    stay on the current plan")
    if advice.alternatives:
        out.append("  Eligible plans, cheapest first:")
        for q in advice.alternatives:
            mark = " <- current" if q.plan == advice.current.plan else ""
            out.append(f"    {q.plan:<14}{format_money(q.total):>18}{mark}")
    else:
        out.append(f"  No non-legacy plans are priced in {cur}.")
    return "\n".join(out) + "\n"
