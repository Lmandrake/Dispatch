"""Summary reports printed by ``stockroom report``."""

from collections import defaultdict

from stockroom.models import ORDER_STATUSES
from stockroom.money import format_price
from stockroom.table import render_table


def summary(service):
    """Headline numbers: item count, units, stock value, low-stock list."""
    items = service.repo.list_items()
    orders = service.repo.list_orders()
    units = sum(i.quantity for i in items)
    value = sum(i.value_cents for i in items)
    open_orders = [o for o in orders if o.is_open]
    reserved = sum(o.quantity for o in open_orders)
    low = [i for i in items if i.is_low]
    lines = [
        f"Items:        {len(items)}",
        f"Units:        {units}",
        f"Stock value:  {format_price(value)}",
        f"Open orders:  {len(open_orders)} ({reserved} units reserved)",
        f"Low stock:    {len(low)}",
    ]
    for i in low:
        lines.append(f"  {i.sku}  {i.quantity} on hand (reorder at {i.reorder_level})")
    return "\n".join(lines) + "\n"


def by_location(service):
    """One row per location: item count, units and value; "-" for no location."""
    groups = defaultdict(list)
    for item in service.repo.list_items():
        groups[item.location or "-"].append(item)
    rows = []
    for loc in sorted(groups, key=lambda s: (s == "-", s)):
        items = groups[loc]
        rows.append([loc, len(items), sum(i.quantity for i in items),
                     format_price(sum(i.value_cents for i in items))])
    return render_table(("Location", "Items", "Units", "Value"), rows, "lrrr") + "\n"


def order_status(service):
    """Count and units of orders per status, in ORDER_STATUSES order."""
    counts = {s: [0, 0] for s in ORDER_STATUSES}
    for o in service.repo.list_orders():
        counts[o.status][0] += 1
        counts[o.status][1] += o.quantity
    rows = [[s, c[0], c[1]] for s, c in counts.items()]
    return render_table(("Status", "Orders", "Units"), rows, "lrr") + "\n"


REPORTS = {
    "summary": summary,
    "locations": by_location,
    "orders": order_status,
}
