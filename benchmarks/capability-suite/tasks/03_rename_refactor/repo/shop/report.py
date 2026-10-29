from .pricing import calc_total as _total


def daily_report(orders):
    """orders: list of (customer, lines). Returns {customer: total}."""
    out = {}
    for customer, lines in orders:
        out[customer] = out.get(customer, 0) + _total(lines, taxed=False)
    return out
