"""Value types shared by the store, the caches and the pricing rules."""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Hashable


@dataclass(frozen=True)
class Record:
    """One version of one key in the store.

    ``version`` starts at 1 for a key's first write and increases by one on
    every later write to that key. ``deleted`` marks a tombstone.
    """

    key: Hashable
    value: Any
    version: int
    written_at: float
    deleted: bool = False

    def __post_init__(self):
        if self.version < 1:
            raise ValueError("versions start at 1")


@dataclass(frozen=True)
class Quote:
    """A computed price for ``qty`` units of ``sku`` in ``region``.

    Amounts are integer minor units (cents) of ``currency``.
    """

    sku: str
    region: str
    currency: str
    channel: str
    qty: int
    unit_cents: int
    total_cents: int
    price_version: int
    fx_version: int
    applied: tuple = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "sku": self.sku,
            "region": self.region,
            "currency": self.currency,
            "channel": self.channel,
            "qty": self.qty,
            "unit_cents": self.unit_cents,
            "total_cents": self.total_cents,
            "price_version": self.price_version,
            "fx_version": self.fx_version,
            "applied": list(self.applied),
        }


CENT = Decimal(1)


def to_cents(amount: Decimal) -> int:
    """Round a Decimal amount of minor units to an int, banker's rounding."""
    return int(amount.quantize(CENT, rounding=ROUND_HALF_EVEN))


def apply_basis_points(amount: Decimal, bp: int) -> Decimal:
    """Scale ``amount`` by ``bp`` basis points (100 bp = 1 %). Positive raises."""
    return amount * (Decimal(10000 + bp) / Decimal(10000))


def parse_rate(rate) -> Decimal:
    """FX rates are stored as strings ("0.9213") to keep them exact."""
    d = Decimal(str(rate))
    if d <= 0:
        raise ValueError(f"FX rate must be positive, got {rate!r}")
    return d
