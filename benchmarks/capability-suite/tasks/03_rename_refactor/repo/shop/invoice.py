from . import pricing


def render_invoice(customer, lines, discount_pct=0):
    total = pricing.calc_total(lines, discount_pct)
    rows = [f"{qty} x {price}" for price, qty in lines]
    return "\n".join([f"Invoice for {customer}", *rows, f"TOTAL {total}"])
