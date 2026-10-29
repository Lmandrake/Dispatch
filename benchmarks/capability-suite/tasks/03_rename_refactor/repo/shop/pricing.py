"""Order pricing."""
from decimal import Decimal, ROUND_HALF_UP

TAX_RATE = Decimal("0.08")


def _q(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def subtotal(lines):
    return sum((Decimal(str(price)) * qty for price, qty in lines), Decimal("0"))


def calc_total(lines, discount_pct=0, taxed=True):
    """Total for ``lines`` of (unit_price, qty) after discount, then tax."""
    s = subtotal(lines)
    s = s * (Decimal(100) - Decimal(discount_pct)) / Decimal(100)
    if taxed:
        s = s * (1 + TAX_RATE)
    return _q(s)
