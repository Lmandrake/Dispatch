"""The repository interface every backend implements.

Repositories are dumb stores: they do no validation and know nothing about
business rules.  Items are keyed by SKU, orders by integer id, and audit
events are an append-only list.  ``list_*`` methods return new lists, in a
stable order (items by SKU, orders by id, events by seq).

Backends that buffer writes must make them durable in ``commit()``; the
service layer calls ``commit()`` once at the end of every successful
mutating operation, and ``rollback()`` if the operation fails part-way.
"""

from abc import ABC, abstractmethod


class Repository(ABC):
    # ---- items -------------------------------------------------------
    @abstractmethod
    def get_item(self, sku):
        """Return the Item with this SKU, or None."""

    @abstractmethod
    def list_items(self):
        """All items, sorted by SKU."""

    @abstractmethod
    def save_item(self, item):
        """Insert or replace the item with ``item.sku``."""

    @abstractmethod
    def delete_item(self, sku):
        """Remove the item; return True if it existed."""

    # ---- orders ------------------------------------------------------
    @abstractmethod
    def get_order(self, order_id):
        """Return the Order with this id, or None."""

    @abstractmethod
    def list_orders(self):
        """All orders, sorted by id."""

    @abstractmethod
    def save_order(self, order):
        """Insert or replace the order with ``order.id``."""

    @abstractmethod
    def next_order_id(self):
        """Reserve and return the next order id (1, 2, 3, ...)."""

    # ---- audit -------------------------------------------------------
    @abstractmethod
    def append_event(self, event):
        """Append an AuditEvent."""

    @abstractmethod
    def list_events(self):
        """All audit events, sorted by seq."""

    # ---- transactions ------------------------------------------------
    def commit(self):
        """Make buffered writes durable.  Default: nothing to do."""

    def rollback(self):
        """Discard writes since the last commit.  Default: nothing to do."""

    # ---- conveniences built on the abstract methods ------------------
    def has_item(self, sku):
        return self.get_item(sku) is not None

    def open_orders_for(self, sku):
        return [o for o in self.list_orders() if o.sku == sku and o.is_open]

    def last_event_seq(self):
        events = self.list_events()
        return events[-1].seq if events else 0
