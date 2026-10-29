from .pricing import calc_total


class Cart:
    def __init__(self):
        self.lines = []

    def add(self, price, qty=1):
        self.lines.append((price, qty))
        return self

    def total(self, discount_pct=0):
        return calc_total(self.lines, discount_pct=discount_pct)
