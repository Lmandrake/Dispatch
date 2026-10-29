"""Data-directory lint (the "check" CLI command).

Loading a data directory already rejects malformed files.  ``lint`` adds
the cross-file checks that are warnings, not errors:

* a billable customer without any subscription row;
* a customer whose invoice currency has no FX quote on the cycle's dates;
* a coupon that no redemption uses;
* a redemption whose coupon has already run out before the cycle;
* a credit grant that has already expired before the cycle;
* a plan whose charges do not cover a metric that appears in the feeds for
  one of its customers (usage that will be silently free);
* feed rejects, summarised per file.
"""

from .discounts import active_coupons
from .errors import RateNotFound
from .periods import billing_period


def lint(ds, cycle, ingested=None):
    warnings = []
    subs_customers = set(ds.subscriptions.customers())
    for c in ds.customers.billable():
        if c.id not in subs_customers:
            warnings.append(f"customer {c.id} has no subscription")
        period = billing_period(cycle, c.anchor_day, c.timezone)
        try:
            ds.rates.per_usd(c.currency, period.last_day)
        except RateNotFound as e:
            warnings.append(f"customer {c.id}: {e}")
        for red in ds.redemptions:
            if red.customer == c.id and not active_coupons(ds.coupons, [red], c.id, cycle):
                coupon = ds.coupons[red.coupon]
                if coupon.duration != "forever" and red.first_cycle < cycle:
                    warnings.append(f"customer {c.id}: coupon {red.coupon} no longer active in {cycle}")
        for g in ds.grants:
            if g.customer == c.id and g.expires is not None and g.expires <= period.start:
                warnings.append(f"customer {c.id}: credit {g.grant_id} expired {g.expires.isoformat()}")
    used = {r.coupon for r in ds.redemptions}
    for code in sorted(ds.coupons):
        if code not in used:
            warnings.append(f"coupon {code} is never redeemed")
    if ingested is not None:
        for c in ds.customers.billable():
            period = billing_period(cycle, c.anchor_day, c.timezone)
            seen = {r.metric for r in ingested.for_customer(c.id) if period.contains(r.at)}
            for seg in ds.subscriptions.segments(c.id, period):
                plan = ds.catalog.plan(seg.plan)
                for m in sorted(seen - set(plan.metrics())):
                    warnings.append(f"customer {c.id}: plan {plan.id} does not charge {m}; that usage is free")
        per_file = {}
        for rj in ingested.rejects:
            per_file[rj.source] = per_file.get(rj.source, 0) + 1
        for f in sorted(per_file):
            warnings.append(f"{f}: {per_file[f]} rejected row(s)")
    return sorted(set(warnings), key=warnings.index)
