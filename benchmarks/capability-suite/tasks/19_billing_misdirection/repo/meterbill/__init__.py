"""meterbill: usage-based billing and invoicing for Kettle Cloud.

The package turns raw metering feeds into signed-off invoices:

    meters/*      read usage records from CSV, JSON-lines and key=value logs
    periods       billing periods in each customer's own timezone
    catalog       the plan catalogue (base fees, metered charges, tiers)
    pricing       rating a quantity against a charge (per-unit, graduated,
                  volume, package, flat)
    subscriptions which plan a customer is on, and when it changed
    proration     day-based proration of base fees on mid-cycle changes
    discounts     coupons; credits: prepaid account credit
    fx            exchange rates and currency conversion
    tax           tax by jurisdiction, with per-component rounding rules
    invoice       assembling an invoice from all of the above
    render/*      text, CSV and JSON output
    dunning       reminders, late fees and suspension for unpaid invoices
    reconcile     the month-end reconciliation report
    pipeline      one billing run over a data directory

See docs/ for the business rules finance has signed off.
"""

__version__ = "3.4.1"
