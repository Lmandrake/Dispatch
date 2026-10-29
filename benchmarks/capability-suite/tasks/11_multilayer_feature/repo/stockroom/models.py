"""Domain models.

Every model is a frozen dataclass: services build changed copies with
``dataclasses.replace`` instead of mutating, so a repository can hand out
objects without worrying about callers editing them behind its back.
"""

from dataclasses import dataclass, field, replace

ORDER_OPEN = "open"
ORDER_FULFILLED = "fulfilled"
ORDER_CANCELLED = "cancelled"
ORDER_STATUSES = (ORDER_OPEN, ORDER_FULFILLED, ORDER_CANCELLED)


@dataclass(frozen=True)
class Item:
    """One stock-keeping unit.

    ``price_cents`` is the unit price in integer cents.  ``location`` is a
    free-form bin/shelf label ("" when unknown).  An item is "low" when its
    ``quantity`` is at or below ``reorder_level`` and ``reorder_level`` > 0.
    """

    sku: str
    name: str
    quantity: int = 0
    price_cents: int = 0
    location: str = ""
    reorder_level: int = 0
    created_at: str = ""
    updated_at: str = ""

    @property
    def value_cents(self):
        return self.quantity * self.price_cents

    @property
    def is_low(self):
        return self.reorder_level > 0 and self.quantity <= self.reorder_level

    def with_changes(self, **changes):
        return replace(self, **changes)


@dataclass(frozen=True)
class Order:
    """An outbound order for one SKU.

    Stock is only taken when the order is fulfilled; an open order merely
    *reserves* quantity (see ``InventoryService.available``).
    """

    id: int
    sku: str
    quantity: int
    customer: str = ""
    status: str = ORDER_OPEN
    created_at: str = ""
    closed_at: str = ""

    @property
    def is_open(self):
        return self.status == ORDER_OPEN

    def with_changes(self, **changes):
        return replace(self, **changes)


@dataclass(frozen=True)
class AuditEvent:
    """One line of the audit trail.

    ``seq`` starts at 1 and increases by one per event.  ``action`` is a
    dotted name such as ``item.added``; ``subject`` is the SKU, or
    ``order:<id>`` for order events.  ``details`` holds JSON-safe values.
    """

    seq: int
    timestamp: str
    action: str
    subject: str
    details: dict = field(default_factory=dict)
