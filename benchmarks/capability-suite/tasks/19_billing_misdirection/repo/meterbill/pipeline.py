"""One billing run: load a data directory, ingest feeds, build every invoice."""

from dataclasses import dataclass, field, replace

from .config import load_dataset
from .dunning import evaluate, late_fees_by_customer, suspended_customers
from .invoice import BillingContext, build_invoice
from .meters.ingest import load_feeds
from .numbering import issue_date
from .periods import billing_period, prev_cycle
from .reconcile import reconcile


@dataclass
class BillingRun:
    cycle: str
    dataset: object
    ingested: object
    converter: object
    invoices: list = field(default_factory=list)
    dunning: list = field(default_factory=list)

    def invoice(self, cid):
        for inv in self.invoices:
            if inv.customer.id == cid:
                return inv
        raise KeyError(cid)

    def reconciliation(self):
        return reconcile(self.invoices, self.ingested, self.converter)


def dunning_as_of(ds, cycle):
    """Dunning is evaluated on the earliest issue date of the cycle."""
    days = [issue_date(billing_period(cycle, c.anchor_day, c.timezone)) for c in ds.customers.billable()]
    return min(days)


def billed_in(ds, cust, cycle):
    """Whether ``cust`` gets an invoice for ``cycle`` (docs/SUBSCRIPTIONS.md)."""
    return cust.billable


def dunning_states(ds, cycle, conv):
    if not (ds.schedule and ds.receivables):
        return []
    return evaluate(ds.receivables, ds.schedule, dunning_as_of(ds, cycle), conv)


def context(ds, conv, states):
    return BillingContext(
        catalog=ds.catalog, subscriptions=ds.subscriptions, tax=ds.tax, converter=conv,
        coupons=ds.coupons, redemptions=ds.redemptions, grants=ds.grants,
        late_fees=late_fees_by_customer(states))


def invoice_for(ctx, cust, cycle, records, suspended):
    if cust.id in suspended and cust.status == "active":
        cust = replace(cust, status="suspended")
    return build_invoice(ctx, cust, cycle, records)


def run_billing(data_dir, cycle, *, customers=None):
    ds = load_dataset(data_dir)
    conv = ds.converter()
    ing = load_feeds(ds.feeds_dir, customers=ds.customers, metrics=ds.catalog.metrics)
    states = dunning_states(ds, cycle, conv)
    ctx = context(ds, conv, states)
    run = BillingRun(cycle, ds, ing, conv, dunning=states)
    suspended = set(suspended_customers(states))
    wanted = set(customers) if customers else None
    for cust in ds.customers:
        if wanted is not None and cust.id not in wanted:
            continue
        if not billed_in(ds, cust, cycle):
            continue
        run.invoices.append(invoice_for(ctx, cust, cycle, ing.records, suspended))
    return run
